"""""
对话引擎 (v7.5)
================
对话生命周期的统一入口，集中处理所有对话相关业务逻辑。

职责：
  - start_conversation: 创建会话
  - record_step: 记录步骤（含并发检测、FK 自修复）
  - finalize_conversation: 全局总结 + 异步分析
  - question_with_context: 知识检索（含 LLM 语义扩展）
  - execute_single_step: 执行/重试单个步骤
  - create_knowledge_point: 创建知识点记录
  - update_completed_steps: 更新会话已完成步骤数
  - get_system_health: 获取系统健康状态
  - analyze_and_store: 分析对话并存入数据库（兼容旧接口）

合并来源：
  - services/conversation.py → 本文件
  - services/conversation_analyzer.py → 本文件

设计原则：
  - server.py 只做 MCP 薄入口（参数校验 → 调用 Engine → 返回 JSON）
  - 所有 DB 操作、异步任务提交、LLM 调用都在本块
  - 单例模式，线程安全
"""""
import json
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from devpartner_agent.core.llm_prompts import (
    USER_TRAITS_SCHEMA,
    PROJECT_STRATEGY,
    FEW_SHOT_EXAMPLES,
    ANALYSIS_GUIDELINES,
)

logger = logging.getLogger(__name__)


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepType(str, Enum):
    ANALYSIS = "analysis"
    KNOWLEDGE_GEN = "knowledge_gen"
    USER_PROFILE = "user_profile"
    SYSTEM_OPTIMIZE = "system_optimize"


def _safe_json_parse(val, default):
    if not val:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def _extract_behavior_signals(user_raw_input: str) -> dict:
    """
    从用户原始输入中规则化提取行为信号（v8.0）

    不依赖 LLM，纯规则提取，确保关键信号不丢失。
    LLM 增强分析在每日画像合并时进行。
    """
    if not user_raw_input:
        return {}

    signals = {
        "input_length": len(user_raw_input),
        "has_code_block": "```" in user_raw_input,
        "has_question_mark": "?" in user_raw_input or "？" in user_raw_input,
        "has_error_keyword": any(
            kw in user_raw_input
            for kw in ["error", "Error", "错误", "异常", "报错", "失败", "failed", "exception", "traceback"]
        ),
        "has_debug_keyword": any(
            kw in user_raw_input
            for kw in ["debug", "调试", "排查", "定位", "排查问题", "为什么", "why"]
        ),
        "has_design_keyword": any(
            kw in user_raw_input
            for kw in ["设计", "架构", "方案", "design", "architecture", "如何实现", "怎么实现"]
        ),
        "has_optimize_keyword": any(
            kw in user_raw_input
            for kw in ["优化", "性能", "optimize", "performance", "加速", "提升"]
        ),
        "has_learn_keyword": any(
            kw in user_raw_input
            for kw in ["学习", "理解", "learn", "教程", "入门", "怎么用", "如何使用"]
        ),
        "language_hints": [],
    }

    lang_patterns = {
        "python": ["python", "pip", "django", "flask", "fastapi", "pytorch", "pandas"],
        "javascript": ["javascript", "js", "typescript", "ts", "react", "vue", "node"],
        "java": ["java", "spring", "maven", "gradle", "jvm"],
        "sql": ["sql", "mysql", "postgresql", "sqlite", "query"],
        "docker": ["docker", "kubernetes", "k8s", "container", "compose"],
    }
    for lang, patterns in lang_patterns.items():
        if any(p in user_raw_input.lower() for p in patterns):
            signals["language_hints"].append(lang)

    return signals




class ConversationEngine:
    """对话引擎 — 对话生命周期的统一业务入口"""

    def __init__(self):
        self._lock = threading.Lock()

    def _get_db(self):
        from devpartner_agent.core.database import get_db
        return get_db()

    def _get_task_queue(self):
        from devpartner_agent.services.task_queue import get_task_queue
        return get_task_queue()

    def _get_llm(self):
        from devpartner_agent.core.llm_engine import get_llm_engine
        return get_llm_engine()

# ────────────────────────────────────────────────
    # start_conversation
# ────────────────────────────────────────────────

    def start_conversation(
        self,
        client: str = "unknown",
        topic: str = "",
        task_type: str = "general",
        user_intent: str = "",
        priority: str = "medium",
        system_id: str = "default",
        user_raw_input: str = "",
        agent_context: str = "",
    ) -> dict:
        """""
        创建新会话，返回会话状态。

        v8.0 增强：
        - system_id: 多系统隔离标识，区分不同对接系统
        - user_raw_input: 用户原始输入，用于行为信号提取
        - agent_context: agent上下文摘要

        Returns:
            {"conversation_id": "...", "status": "active", ...}
        """""
        conv_id = f"conv_{uuid.uuid4().hex[:16]}"
        timestamp = datetime.now().isoformat()
        db = self._get_db()

        behavior_signals = _extract_behavior_signals(user_raw_input)

        db.query_local("""""
            INSERT INTO conversations (
                conversation_id, timestamp, client, topic, task_type,
                user_intent, status, priority, created_at, updated_at,
                system_id, behavior_signals, user_raw_input
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
        """, (
            conv_id, timestamp, client, topic, task_type,
            user_intent, priority, timestamp, timestamp,
            system_id, json.dumps(behavior_signals, ensure_ascii=False),
            user_raw_input[:10000] if user_raw_input else "",
        ))

        if system_id != "default":
            self._ensure_system_registered(db, system_id, client, timestamp)

        logger.info(f"✓ 创建会话: {conv_id} | 客户端 {client} | 系统 {system_id} | 主题: {topic}")

        return self.get_conversation_status(conv_id)

# ────────────────────────────────────────────────
    # record_step
# ────────────────────────────────────────────────

    def record_step(
        self,
        conversation_id: str,
        step_name: str,
        step_type: str = "general",
        content: str = "",
        files_changed: str = "",
        symptom: str = "",
        root_cause: str = "",
        solution: str = "",
        knowledge_points: str = "",
        user_question: str = "",
        client_request_id: str = "",
    ) -> dict:
        """""
        记录对话中的单个子任务步骤。

        包含：并发检测 → FK 自保护 → 步骤写入 → 异步任务提交

        Returns:
            {"success": true, "step_id": "...", "task_id": "...", ...}
        """""
        db = self._get_db()
        queue = self._get_task_queue()

        # FK 自保护 — 确保会话父记录存在
        self._ensure_conversation_exists(
            conversation_id,
            client="codebuddy",
                    topic=step_name[:200] or "自动创建的会话",
        )

        # 并发检测
        if client_request_id:
            existing = db.query_local(
                "SELECT step_id FROM conversation_steps WHERE conversation_id =  AND input_data LIKE  LIMIT 1",
                (conversation_id, f"%{client_request_id}%"),
            )
            if existing:
                return {
                    "success": True,
                    "step_id": existing[0]["step_id"],
                    "duplicate": True,
                    "message": "Step already recorded (idempotent)",
                    "conversation_id": conversation_id,
                }

        # 解析参数
        files_list = _safe_json_parse(files_changed, [])
        kp_list = _safe_json_parse(knowledge_points, [])

        # 创建步骤
        step_id = f"{conversation_id}_step_{datetime.now().strftime('%H%M%S%f')}"

        step_input = {
            "step_name": step_name,
            "step_type": step_type,
            "content": content[:100000] if content else "",
            "files_changed": files_list,
            "symptom": symptom[:50000] if symptom else "",
            "root_cause": root_cause[:50000] if root_cause else "",
            "solution": solution[:50000] if solution else "",
            "knowledge_points": kp_list,
            "user_question": user_question[:10000] if user_question else "",
            "client_request_id": client_request_id or "",
            "recorded_at": datetime.now().isoformat(),
        }

        try:
            self._insert_step(db, step_id, conversation_id, step_name, step_input)
        except Exception as e:
            error_msg = str(e)
            if "FOREIGN KEY" in error_msg.upper():
                result = self._fk_self_repair(
                    db, conversation_id, step_name, step_id,
                    step_type, content, files_list, symptom,
                    root_cause, solution, kp_list, user_question,
                )
                if result is not None:
                    return result
            raise

        # 更新会话总步骤数
        total = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversation_steps WHERE conversation_id = ",
            (conversation_id,),
        )[0]["cnt"]
        db.query_local("""""
            UPDATE conversations SET total_steps = , updated_at = 
            WHERE conversation_id = 
        """, (total, datetime.now().isoformat(), conversation_id))

        # 提交异步分析任务
        task_payload = {
            "conversation_id": conversation_id,
            "step_id": step_id,
            "step_name": step_name,
            "step_type": step_type,
            "content": content[:100000] if content else "",
            "knowledge_points": kp_list,
            "files_changed": files_list,
            "symptom": symptom[:50000] if symptom else "",
            "root_cause": root_cause[:50000] if root_cause else "",
            "solution": solution[:50000] if solution else "",
        }

        task_id = queue.submit_task(
            task_type="step_analysis",
            payload=task_payload,
            priority=8,
            estimated_memory_mb=100,
        )

        return {
            "success": True,
            "step_id": step_id,
            "task_id": task_id,
            "queued": True,
            "conversation_id": conversation_id,
            "total_steps": total,
        }

    def _insert_step(self, db, step_id, conversation_id, step_name, step_input):
        """写入 conversation_steps 表"""
        db.query_local("""""
            INSERT INTO conversation_steps (
                step_id, conversation_id, step_order, step_type,
                step_name, status, input_data, max_retries,
                timeout_seconds, priority, depends_on, created_at
            ) VALUES (, ,
                (SELECT COALESCE(MAX(step_order), 0) + 1 FROM conversation_steps WHERE conversation_id = ),
                'analysis', , 'pending', , 3, 300, 5, '', 
            )
        """, (
            step_id, conversation_id, conversation_id,
            step_name, json.dumps(step_input, ensure_ascii=False),
            datetime.now().isoformat(),
        ))

        db.query_local("""""
            UPDATE conversation_steps SET started_at =  WHERE step_id = 
        """, (datetime.now().isoformat(), step_id))

    def _fk_self_repair(
        self, db, conversation_id, step_name, step_id,
        step_type, content, files_list, symptom,
        root_cause, solution, kp_list, user_question,
    ) -> Optional[dict]:
        """FK 约束自修复 — 如果 FOREIGN KEY 失败，自动尝试修复并重试"""
        try:
            cursor = db._local_conn.cursor()

            cursor.execute("""""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique
                ON conversations(conversation_id)
            """)

            exists = cursor.execute(
                "SELECT id FROM conversations WHERE conversation_id = ",
                (conversation_id,),
            ).fetchone()

            if not exists:
                ts = datetime.now().isoformat()
                cursor.execute("""""
                    INSERT INTO conversations (conversation_id, timestamp, client, topic, task_type, status, priority, created_at, updated_at)
                    VALUES (, , 'codebuddy', , 'general', 'active', 'medium', , )
                """, (
                    conversation_id, ts,
                    step_name[:200] if step_name else "自动创建",
                    ts, ts,
                ))
                db._local_conn.commit()
                logger.info(f"FK 自修复 自动创建 conversations 记录 {conversation_id}")

            step_id = f"{conversation_id}_step_{datetime.now().strftime('%H%M%S%f')}"
            step_input = {
                "step_name": step_name,
                "step_type": step_type,
                "content": content[:100000] if content else "",
                "files_changed": files_list,
                "symptom": symptom[:50000] if symptom else "",
                "root_cause": root_cause[:50000] if root_cause else "",
                "solution": solution[:50000] if solution else "",
                "knowledge_points": kp_list,
                "user_question": user_question[:10000] if user_question else "",
                "recorded_at": datetime.now().isoformat(),
            }
            self._insert_step(db, step_id, conversation_id, step_name, step_input)

            logger.info(f"FK 自修复后重试成功: {step_id}")
            return {
                "success": True,
                "step_id": step_id,
                "auto_repaired": True,
                "conversation_id": conversation_id,
            }
        except Exception as retry_err:
            logger.error(f"FK 自修复失败 {retry_err}")
            return None

# ────────────────────────────────────────────────
    # finalize_conversation
# ────────────────────────────────────────────────

    def finalize_conversation(
        self,
        conversation_id: str,
        summary: str = "",
        user_traits: str = "",
        key_decisions: str = "",
        self_reflection: str = "",
    ) -> dict:
        """""
        对话结束时调用，提交全局总结并触发全面分析。

        Returns:
            {"success": true, "conversation_id": "...", "analysis_queued": true, ...}
        """""
        db = self._get_db()
        queue = self._get_task_queue()

        decisions_list = _safe_json_parse(key_decisions, [])
        traits_data = _safe_json_parse(user_traits, {})

        # 更新 conversations 表
        db.query_local("""""
            UPDATE conversations SET
                self_reflection = ,
                updated_at = 
            WHERE conversation_id = 
        """, (self_reflection[:50000] if self_reflection else "", datetime.now().isoformat(), conversation_id))

        if decisions_list:
            db.query_local("""""
                UPDATE conversations SET decisions = 
                WHERE conversation_id = 
            """, (json.dumps(decisions_list, ensure_ascii=False)[:50000], conversation_id))

        # 提交全局分析任务
        final_payload = {
            "conversation_id": conversation_id,
            "summary": summary[:50000] if summary else "",
            "user_traits": traits_data,
            "key_decisions": decisions_list,
            "self_reflection": self_reflection[:50000] if self_reflection else "",
            "finalized_at": datetime.now().isoformat(),
        }

        task_id = queue.submit_task(
            task_type="conversation_finalize",
            payload=final_payload,
            priority=10,
            estimated_memory_mb=200,
        )

        # 标记会话为已完成
        db.query_local("""""
            UPDATE conversations SET
                status = 'completed', completed_at = , updated_at = 
            WHERE conversation_id =  AND status != 'completed'
        """, (datetime.now().isoformat(), datetime.now().isoformat(), conversation_id))

        # 标记总结已生成
        db.query_local("""""
            UPDATE conversations SET summary_generated = 1, updated_at = 
            WHERE conversation_id = 
        """, (datetime.now().isoformat(), conversation_id))

        # 异步软删除
        def _soft_delete():
            try:
                from devpartner_agent.services.cleanup_service import get_cleanup_service
                cs = get_cleanup_service()
                cs.soft_delete_conversation_tasks(conversation_id)
            except Exception as e:
                logger.warning(f"软删除失败（非致命）: {e}")

        threading.Thread(target=_soft_delete, daemon=True).start()

        return {
            "success": True,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "analysis_queued": True,
            "analysis_dimensions": [
                "技术决策链分析",
                "用户画像更新",
                "知识图谱构建",
                "系统优化建议",
                "对话质量评估",
            ],
        }

# ────────────────────────────────────────────────
    # question_with_context
# ────────────────────────────────────────────────

    def question_with_context(
        self,
        question: str,
        project_name: str = "",
        category: str = "",
        limit: int = 5,
    ) -> dict:
        """""
        基于知识库的智能问答（含 LLM 语义扩展）。

        Returns:
            {"success": true, "results": [...], "expanded_queries": [...], ...}
        """""
        db = self._get_db()

        # 构建查询条件
        conditions = []
        params = []

        if category and category in ("skill", "business"):
            conditions.append("kp.type = ")
            params.append(category)

        if project_name:
            conditions.append("(kp.type = 'business' AND kp.domain = )")
            params.append(project_name)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 绗竴杞細绮剧 LIKE 鎼滅储
        search_term = f"%{question}%"
        sql = f"""""
            SELECT kp.knowledge_id, kp.title, kp.content, kp.type, kp.domain,
                   kp.tags, kp.category, kp.difficulty, kp.usage_count, kp.created_at
            FROM knowledge_points kp
            WHERE {where_clause}
              AND (kp.title LIKE  OR kp.content LIKE )
            ORDER BY kp.usage_count DESC, kp.created_at DESC
            LIMIT 
        """""
        params_ext = list(params) + [search_term, search_term, limit]
        rows = db.query_local(sql, tuple(params_ext))

        # 第二轮：LLM 语义扩展（无精确匹配时）
        expanded_queries = []
        if not rows:
            expanded_queries = self._expand_question_with_llm(question)

        if not rows and expanded_queries:
            or_clauses = []
            expanded_params = list(params)
            for eq in expanded_queries:
                or_clauses.append("(kp.title LIKE  OR kp.content LIKE )")
                expanded_params.extend([f"%{eq}%", f"%{eq}%"])
            expanded_sql = f"""""
                SELECT kp.knowledge_id, kp.title, kp.content, kp.type, kp.domain,
                       kp.tags, kp.category, kp.difficulty, kp.usage_count, kp.created_at
                FROM knowledge_points kp
                WHERE {where_clause}
                  AND ({" OR ".join(or_clauses)})
                ORDER BY kp.usage_count DESC, kp.created_at DESC
                LIMIT 
            """""
            expanded_params.append(limit)
            rows = db.query_local(expanded_sql, tuple(expanded_params))

        # 第三轮：兜底返回最相关记录
        if not rows:
            fallback_params = list(params) + [limit]
            sql_fallback = f"""""
                SELECT kp.knowledge_id, kp.title, kp.content, kp.type, kp.domain,
                       kp.tags, kp.category, kp.difficulty, kp.usage_count, kp.created_at
                FROM knowledge_points kp
                WHERE {where_clause}
                ORDER BY kp.usage_count DESC, kp.created_at DESC
                LIMIT 
            """""
            rows = db.query_local(sql_fallback, tuple(fallback_params))

        # 格式化结果
        results = []
        for row in (rows or []):
            tags = row.get("tags", "[]")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = [tags]

            content = row.get("content", "")
            summary = content[:300] + "..." if len(content) > 300 else content

            results.append({
                "knowledge_id": row["knowledge_id"],
                "title": row["title"],
                "summary": summary,
                "type": row.get("type", "skill"),
                "domain": row.get("domain", ""),
                "tags": tags,
                "category": row.get("category", ""),
                "difficulty": row.get("difficulty", "medium"),
                "usage_count": row.get("usage_count", 0),
            })

        return {
            "success": True,
            "question": question,
            "project_name": project_name,
            "category_filter": category,
            "expanded_queries": expanded_queries,
            "total": len(results),
            "results": results,
        }

    def _expand_question_with_llm(self, question: str) -> List[str]:
        """用 LLM 改写问题为多个同义扩展查询"""
        try:
            llm = self._get_llm()
            if not llm or not llm.is_available():
                return []

            expand_prompt = (
                f"请将以下技术问题改写为3个同义扩展查询词（每条3-5个词，只输出关键词，不要编号和解释）：\n{question}"
            )
            raw = llm.infer(expand_prompt, max_tokens=256)
            if raw and len(raw.strip()) > 5:
                return [
                    line.strip().lstrip("0123456789.-) ")
                    for line in raw.strip().split("\n")
                    if line.strip() and len(line.strip()) > 1
                ][:3]
        except Exception:
            pass
        return []

# ────────────────────────────────────────────────
    # 通用辅助方法
# ────────────────────────────────────────────────

    def get_conversation_status(self, conversation_id: str) -> Optional[dict]:
        """获取会话详细状态"""
        db = self._get_db()

        conv = db.query_local(
            "SELECT * FROM conversations WHERE conversation_id = ",
            (conversation_id,),
        )
        if not conv:
            return None

        steps = db.query_local("""""
            SELECT * FROM conversation_steps WHERE conversation_id =  ORDER BY step_order ASC
        """, (conversation_id,))

        return {
            "conversation": dict(conv[0]),
            "steps": [dict(s) for s in steps],
            "progress": {
                "total": conv[0]["total_steps"],
                "completed": conv[0]["completed_steps"],
                "percentage": round(
                    conv[0]["completed_steps"] / max(1, conv[0]["total_steps"]) * 100, 1
                ),
            },
        }

    def _ensure_conversation_exists(
        self, conversation_id: str, client: str = "codebuddy", topic: str = ""
    ) -> bool:
        """FK 自保护 — 确保会话父记录存在"""
        db = self._get_db()
        try:
            existing = db.query_local(
                "SELECT id FROM conversations WHERE conversation_id = ",
                (conversation_id,),
            )
            if existing:
                return True

            ts = datetime.now().isoformat()
            db.query_local("""""
                INSERT INTO conversations (
                    conversation_id, timestamp, client, topic, task_type,
                    status, priority, created_at, updated_at
                ) VALUES (, , , , , 'active', 'medium', , )
            """, (conversation_id, ts, client, topic, "general", ts, ts))
            logger.info(f"ensure_conversation_exists: 创建会话 {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"ensure_conversation_exists 失败: {e}")
            return False

    def _ensure_system_registered(self, db, system_id: str, client: str, timestamp: str):
        """确保对接系统已注册到 connected_systems 表（v8.0）"""
        try:
            existing = db.query_local(
                "SELECT system_id FROM connected_systems WHERE system_id = ?",
                (system_id,),
            )
            if existing:
                db.query_local(
                    "UPDATE connected_systems SET last_active = ?, conversation_count = conversation_count + 1 WHERE system_id = ?",
                    (timestamp, system_id),
                )
            else:
                db.query_local(
                    "INSERT INTO connected_systems (system_id, system_type, display_name, first_connected, last_active, conversation_count) VALUES (?, ?, ?, ?, ?, 1)",
                    (system_id, client, client, timestamp, timestamp),
                )
        except Exception as e:
            logger.warning(f"系统注册失败（非致命）: {e}")

# ────────────────────────────────────────────────
    # 来自 conversation_manager.py 的方法
# ────────────────────────────────────────────────

    def execute_single_step(self, step_id: str, force_retry: bool = False) -> Dict[str, Any]:
        """执行或重试单个步骤"""
        db = self._get_db()

        steps = db.query_local("SELECT * FROM conversation_steps WHERE step_id = ", (step_id,))
        if not steps:
            raise ValueError(f"Step not found: {step_id}")

        step = steps[0]
        current_status = step["status"]

        if current_status == StepStatus.COMPLETED.value and not force_retry:
            return {"status": "already_completed", "step_id": step_id}

        if current_status == StepStatus.RUNNING.value and not force_retry:
            return {"status": "already_running", "step_id": step_id}

        start_time = datetime.now()
        db.query_local("""""
            UPDATE conversation_steps SET status = 'running', started_at = 
            WHERE step_id = 
        """, (start_time.isoformat(), step_id))

        try:
            result = self._dispatch_step_execution(step)

            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            knowledge_ids = result.get("knowledge_point_ids", [])

            db.query_local("""""
                UPDATE conversation_steps SET
                    status = 'completed', output_data = , error_message = NULL,
                    knowledge_point_ids = , completed_at = , duration_ms = , retry_count = 0
                WHERE step_id = 
            """, (
                json.dumps(result.get("output", {}), ensure_ascii=False),
                ",".join(knowledge_ids) if knowledge_ids else None,
                end_time.isoformat(), duration_ms, step_id,
            ))

            self.update_completed_steps(step["conversation_id"])

            logger.info(f"✓ 步骤执行成功: {step_id} | 耗时: {duration_ms}ms")

            return {
                "status": "success",
                "step_id": step_id,
                "duration_ms": duration_ms,
                "output": result.get("output", {}),
                "knowledge_points_created": len(knowledge_ids),
            }

        except Exception as e:
            logger.error(f"✗ 步骤执行失败: {step_id} | 错误: {e}", exc_info=True)

            new_retry_count = step["retry_count"] + 1
            max_retries = step["max_retries"]

            if new_retry_count < max_retries:
                db.query_local("""""
                    UPDATE conversation_steps SET
                        status = 'pending', error_message = , retry_count = 
                    WHERE step_id = 
                """, (str(e), new_retry_count, step_id))

                return {
                    "status": "retry_scheduled",
                    "step_id": step_id,
                    "retry_count": new_retry_count,
                    "max_retries": max_retries,
                    "error": str(e),
                }
            else:
                db.query_local("""""
                    UPDATE conversation_steps SET
                        status = 'failed', error_message = , completed_at = 
                    WHERE step_id = 
                """, (str(e), datetime.now().isoformat(), step_id))

                return {
                    "status": "failed",
                    "step_id": step_id,
                    "error": str(e),
                    "retried": new_retry_count,
                }

    def _dispatch_step_execution(self, step: dict) -> Dict[str, Any]:
        """根据步骤类型分发执行逻辑"""
        step_type = step["step_type"]
        input_data = json.loads(step["input_data"]) if step["input_data"] else {}

        if step_type == StepType.ANALYSIS.value:
            return self._execute_analysis_step(step, input_data)
        elif step_type == StepType.KNOWLEDGE_GEN.value:
            return self._execute_knowledge_generation_step(step, input_data)
        elif step_type == StepType.USER_PROFILE.value:
            return self._execute_user_profile_step(step, input_data)
        elif step_type == StepType.SYSTEM_OPTIMIZE.value:
            return self._execute_system_optimize_step(step, input_data)
        else:
            raise ValueError(f"Unknown step type: {step_type}")

    def _execute_analysis_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行对话分析步骤"""
        llm = self._get_llm()
        content = input_data.get("content", "")
        source = input_data.get("source", "unknown")
        client = input_data.get("client", "unknown")

        analysis_result = llm.analyze_conversation(content, source, client)

        if analysis_result:
            return {"output": analysis_result, "knowledge_point_ids": []}
        else:
            raise RuntimeError("LLM analysis failed or returned empty result")

    def _execute_knowledge_generation_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行知识点生成步骤"""
        analysis_output = input_data.get("analysis_output", {})
        skill_domains = analysis_output.get("skill_domains", [])
        knowledge_ids = []

        for domain_info in skill_domains:
            domain = domain_info.get("domain", "General")
            sub_skills = domain_info.get("sub_skills", [])

            for skill in sub_skills:
                kp_id = self.create_knowledge_point(
                    title=f"[{domain}] {skill}",
                    content=f"技能点: {skill}\n领域: {domain}\n来源: 自动提取\n时间: {datetime.now().isoformat()}",
                    category="skill",
                    domain=domain,
                    tags=[domain, skill],
                    source_type="step",
                    source_id=step["step_id"],
                )
                if kp_id:
                    knowledge_ids.append(kp_id)

        return {
            "output": {"knowledge_generated": len(knowledge_ids)},
            "knowledge_point_ids": knowledge_ids,
        }

    def _execute_user_profile_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行用户画像更新步骤"""
        analysis_output = input_data.get("analysis_output", {})
        user_traits = analysis_output.get("user_traits", {})

        db = self._get_db()
        skills_observed = user_traits.get("skills_observed", [])
        for skill in skills_observed:
            db.query_local("""""
                INSERT OR IGNORE INTO user_skills (
                    timestamp, skill_domain, skill_level, sub_skills,
                    evidence, last_updated
                ) VALUES (, 'intermediate', , , )
            """, (
                datetime.now().isoformat(),
                skill,
                json.dumps([skill], ensure_ascii=False),
                f"自动检测自会话 {step['conversation_id']}",
                datetime.now().isoformat(),
            ))

        return {"output": {"traits_extracted": len(skills_observed)}, "knowledge_point_ids": []}

    def _execute_system_optimize_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行系统优化建议步骤"""
        llm = self._get_llm()
        system_data = input_data.get("system_data", {})
        suggestions = llm.generate_self_improvement_suggestions(system_data)

        if suggestions:
            db = self._get_db()
            for suggestion in suggestions:
                db.query_local("""""
                    INSERT INTO improvement_log (
                        timestamp, category, suggestion, priority,
                        status, conversations_id
                    ) VALUES (, , , , 'pending',
                        (SELECT id FROM conversations WHERE conversation_id = )
                    )
                """, (
                    datetime.now().isoformat(),
                    suggestion.get("category", "general"),
                    suggestion.get("suggestion", ""),
                    suggestion.get("priority", "medium"),
                    step["conversation_id"],
                ))

            return {"output": {"suggestions_generated": len(suggestions)}, "knowledge_point_ids": []}
        else:
            return {"output": {"suggestions_generated": 0}, "knowledge_point_ids": []}

    def create_knowledge_point(
        self,
        title: str,
        content: str,
        category: str,
        domain: str,
        tags: list,
        source_type: str = "system",
        source_id: str = "",
    ) -> Optional[str]:
        """创建知识点记录（委托给 database.insert_knowledge_point）"""
        db = self._get_db()
        kp_id = db.insert_knowledge_point(
            title=title, content=content, category=category,
            domain=domain, tags=tags, source_type=source_type,
            source_id=source_id,
        )
        if kp_id:
            logger.info(f"📕 创建知识点 {kp_id} | {title}")
        return kp_id

    def update_completed_steps(self, conversation_id: str):
        """更新会话的已完成步骤数"""
        db = self._get_db()

        completed = db.query_local("""""
            SELECT COUNT(*) as cnt FROM conversation_steps
            WHERE conversation_id =  AND status = 'completed'
        """, (conversation_id,))[0]["cnt"]

        total = db.query_local("""""
            SELECT COUNT(*) as cnt FROM conversation_steps
            WHERE conversation_id = 
        """, (conversation_id,))[0]["cnt"]

        db.query_local("""""
            UPDATE conversations SET
                completed_steps = , total_steps = , updated_at = 
            WHERE conversation_id = 
        """, (completed, total, datetime.now().isoformat(), conversation_id))

        if completed >= total and total > 0:
            self.complete_conversation(conversation_id)

    def complete_conversation(self, conversation_id: str):
        """标记会话为已完成"""
        db = self._get_db()
        db.query_local("""""
            UPDATE conversations SET
                status = 'completed', completed_at = , updated_at = 
            WHERE conversation_id =  AND status != 'completed'
        """, (datetime.now().isoformat(), datetime.now().isoformat(), conversation_id))
        logger.info(f"🎉 会话完成: {conversation_id}")

    def fail_conversation(self, conversation_id: str, error: str = "Unknown error"):
        """标记会话为失败"""
        db = self._get_db()
        db.query_local("""""
            UPDATE conversations SET
                status = 'failed', updated_at = , self_reflection = 
            WHERE conversation_id =  AND status NOT IN ('completed', 'failed')
        """, (datetime.now().isoformat(), error, conversation_id))
        logger.error(f"✗ 会话失败: {conversation_id} | 原因: {error}")

    def get_system_health(self) -> dict:
        """获取系统健康状态"""
        return {
            "active_conversations": 0,
            "running_tasks": 0,
            "concurrency_limit": 3,
            "estimated_memory_usage_mb": 0.0,
            "max_memory_limit_mb": 2048.0,
            "memory_utilization_percent": 0.0,
        }

    # ══════════════════════════════════════════════════════════
    # 任务处理器（v8.0: 从 task_queue 解耦，各模块管理自己的业务逻辑）
    # ══════════════════════════════════════════════════════════

    def handle_step_analysis(self, payload: dict) -> dict:
        """步骤分析任务处理器"""
        step_start = datetime.now()
        conversation_id = payload.get("conversation_id", "")
        step_id = payload.get("step_id", "")
        step_name = payload.get("step_name", "")
        content = payload.get("content", "")
        knowledge_points = payload.get("knowledge_points", [])
        files_changed = payload.get("files_changed", [])
        step_type = payload.get("step_type", "general")
        symptom = payload.get("symptom", "")
        root_cause = payload.get("root_cause", "")
        solution = payload.get("solution", "")

        db = self._get_db()

        results = {
            "step_id": step_id,
            "knowledge_points_created": 0,
            "skill_domains": [],
            "files_indexed": len(files_changed),
            "llm_analyzed": False,
        }

        try:
            llm = self._get_llm()
            if llm and llm.is_available():
                llm_result = llm.analyze_step_content(
                    step_name=step_name, step_type=step_type,
                    content=content, symptom=symptom,
                    root_cause=root_cause, solution=solution,
                )
                if llm_result:
                    results["llm_analyzed"] = True
                    results["thinking_patterns"] = llm_result.get("thinking_patterns", [])
                    results["commands_used"] = llm_result.get("commands_used", [])
                    results["syntax_points"] = llm_result.get("syntax_points", [])
                    results["complexity_level"] = llm_result.get("complexity_level", "simple")
                    results["key_decision"] = llm_result.get("key_decision", "")

                    extracted_kp = llm_result.get("extracted_knowledge", [])
                    if extracted_kp:
                        for kp in extracted_kp:
                            db.insert_knowledge_point(
                                title=kp.get("title", "LLM提取知识点"),
                                content=kp.get("desc", ""),
                                category="llm_extracted",
                                domain=kp.get("domain", "General"),
                                tags=kp.get("tags", [step_type]),
                                source_type="step_llm",
                                source_id=step_id,
                            )
                        results["llm_knowledge_points"] = len(extracted_kp)
                    else:
                        results["llm_knowledge_points"] = 0
        except Exception as e:
            logger.warning(f"LLM 步骤分析失败（非致命）: {e}")

        kp_ids = []
        if knowledge_points:
            for kp in knowledge_points:
                kp_id = db.insert_knowledge_point(
                    title=kp.get("title", "未命名知识点"),
                    content=kp.get("desc", ""),
                    category="step_extracted",
                    domain=kp.get("domain", "General"),
                    tags=kp.get("tags", [step_type]),
                    source_type="step",
                    source_id=step_id,
                )
                if kp_id:
                    kp_ids.append(kp_id)
            results["knowledge_points_created"] = len(kp_ids)

        actual_duration_ms = int((datetime.now() - step_start).total_seconds() * 1000)
        db.query_local("""
            UPDATE conversation_steps SET
                status = 'completed', output_data = ?,
                knowledge_point_ids = ?,
                completed_at = ?, duration_ms = ?
            WHERE step_id = ?
        """, (
            json.dumps(results, ensure_ascii=False),
            json.dumps(kp_ids, ensure_ascii=False) if kp_ids else "",
            datetime.now().isoformat(),
            actual_duration_ms,
            step_id
        ))

        completed = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversation_steps WHERE conversation_id = ? AND status = 'completed'",
            (conversation_id,)
        )[0]["cnt"]
        total = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversation_steps WHERE conversation_id = ?",
            (conversation_id,)
        )[0]["cnt"]
        db.query_local(
            "UPDATE conversations SET completed_steps = ?, total_steps = ?, updated_at = ? WHERE conversation_id = ?",
            (completed, total, datetime.now().isoformat(), conversation_id)
        )

        logger.info(f"📋 Step analysis done: {step_id} | KP: {results['knowledge_points_created']} | LLM: {results['llm_analyzed']}")
        return results

    def handle_conversation_finalize(self, payload: dict) -> dict:
        """对话全局分析任务处理器"""
        from devpartner_agent.services.knowledge_extractor import get_knowledge_extractor
        from devpartner_agent.services.vault_exporter import get_vault_exporter

        conversation_id = payload.get("conversation_id", "")
        summary = payload.get("summary", "")
        user_traits = payload.get("user_traits", {})
        key_decisions = payload.get("key_decisions", [])
        self_reflection = payload.get("self_reflection", "")

        db = self._get_db()

        results = {
            "conversation_id": conversation_id,
            "traits_updated": 0,
            "decisions_recorded": 0,
            "quality_score": 0,
            "llm_deep_analyzed": False,
        }

        try:
            llm = self._get_llm()
            if llm and llm.is_available():
                steps_rows = db.query_local(
                    "SELECT step_name, step_type, status, output_data, created_at "
                    "FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order",
                    (conversation_id,)
                )
                steps_summary = []
                deep_result = None

                for row in (steps_rows or []):
                    step_info = {"name": row.get("step_name", ""), "type": row.get("step_type", ""),
                                 "status": row.get("status", ""), "created_at": row.get("created_at", "")}
                    output = row.get("output_data", "")
                    if output:
                        try:
                            output_dict = json.loads(output)
                            step_info["thinking_patterns"] = output_dict.get("thinking_patterns", [])
                            step_info["complexity"] = output_dict.get("complexity_level", "")
                        except Exception:
                            pass
                    steps_summary.append(step_info)

                deep_result = llm.analyze_conversation_deep(
                    summary=summary, self_reflection=self_reflection,
                    user_traits=user_traits, key_decisions=key_decisions,
                    steps_summary=steps_summary,
                )

                if deep_result:
                    results["llm_deep_analyzed"] = True
                    results["system_issues"] = deep_result.get("system_issues", [])
                    results["system_deficiencies"] = deep_result.get("system_deficiencies", [])
                    results["user_insights"] = deep_result.get("user_insights", [])
                    results["recurring_patterns"] = deep_result.get("recurring_patterns", [])
                    results["overall_assessment"] = deep_result.get("overall_assessment", "")
                    results["risk_areas"] = deep_result.get("risk_areas", [])
                    results["positive_patterns"] = deep_result.get("positive_patterns", [])

                    for issue in (results.get("system_issues") or [])[:5]:
                        db.query_local("""
                            INSERT INTO improvement_log (
                                timestamp, category, suggestion, priority, status, conversations_id
                            ) VALUES (?, 'system_issue', ?, ?, 'pending',
                                (SELECT id FROM conversations WHERE conversation_id = ?)
                            )
                        """, (datetime.now().isoformat(),
                              f"系统问题: {issue.get('issue', '')} | 根因: {issue.get('root_cause', '')}",
                              issue.get("severity", "medium"), conversation_id))

                    for insight in (results.get("user_insights") or [])[:5]:
                        db.query_local("""
                            INSERT INTO improvement_log (
                                timestamp, category, suggestion, priority, status, conversations_id
                            ) VALUES (?, 'user_insight', ?, 'low', 'pending',
                                (SELECT id FROM conversations WHERE conversation_id = ?)
                            )
                        """, (datetime.now().isoformat(),
                              f"用户观察: {insight.get('observation', '')} | 模式: {insight.get('pattern', '')}",
                              conversation_id))
        except Exception as e:
            logger.warning(f"LLM 深层对话分析失败（非致命）: {e}")

        results["system_context_extracted"] = False
        try:
            system_id = "default"
            conv_row = db.query_local(
                "SELECT system_id FROM conversations WHERE conversation_id = ?", (conversation_id,)
            )
            if conv_row:
                system_id = conv_row[0].get("system_id", "default") or "default"

            tech_signals, architecture_signals, business_signals, new_discoveries = [], [], [], []
            try:
                ft_rows = db.query_local(
                    "SELECT files_touched FROM conversations WHERE conversation_id = ?", (conversation_id,)
                )
                if ft_rows:
                    ft_raw = ft_rows[0].get("files_touched", "[]")
                    files_touched = json.loads(ft_raw) if isinstance(ft_raw, str) else (ft_raw or [])
                    for f in files_touched[:10]:
                        tech_signals.append({"file": f, "type": "file_touched"})
            except Exception:
                pass

            if tech_signals or architecture_signals or business_signals or new_discoveries:
                db.query_local("""
                    INSERT INTO system_context_fragments (
                        conversation_id, system_id, tech_signals, architecture_signals,
                        business_signals, new_discoveries, confidence, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (conversation_id, system_id,
                      json.dumps(tech_signals, ensure_ascii=False),
                      json.dumps(architecture_signals, ensure_ascii=False),
                      json.dumps(business_signals, ensure_ascii=False),
                      json.dumps(new_discoveries, ensure_ascii=False),
                      0.5 + (0.3 if results.get("llm_deep_analyzed") else 0.0),
                      datetime.now().isoformat()))
                results["system_context_extracted"] = True
        except Exception as e:
            logger.warning(f"系统认知片段提取失败（非致命）: {e}")

        if key_decisions:
            for decision in key_decisions:
                db.query_local("""
                    INSERT INTO improvement_log (
                        timestamp, category, suggestion, priority, status, conversations_id
                    ) VALUES (?, 'decision', ?, 'medium', 'pending',
                        (SELECT id FROM conversations WHERE conversation_id = ?)
                    )
                """, (datetime.now().isoformat(),
                      f"决策: {decision.get('decision', '')} | 原因: {decision.get('reason', '')}",
                      conversation_id))
            results["decisions_recorded"] = len(key_decisions)

        if self_reflection or results.get("llm_deep_analyzed"):
            try:
                llm = self._get_llm()
                suggestions = llm.generate_self_improvement_suggestions({
                    "reflection": self_reflection, "summary": summary,
                    "conversation_id": conversation_id,
                    "llm_deep_analysis": {
                        "system_issues": results.get("system_issues", []),
                        "system_deficiencies": results.get("system_deficiencies", []),
                        "recurring_patterns": results.get("recurring_patterns", []),
                        "risk_areas": results.get("risk_areas", []),
                        "overall_assessment": results.get("overall_assessment", ""),
                    },
                })
                if suggestions:
                    for s in suggestions:
                        db.query_local("""
                            INSERT INTO improvement_log (
                                timestamp, category, suggestion, priority, status, conversations_id
                            ) VALUES (?, ?, ?, ?, 'pending',
                                (SELECT id FROM conversations WHERE conversation_id = ?)
                            )
                        """, (datetime.now().isoformat(), s.get("category", "general"),
                              s.get("suggestion", ""), s.get("priority", "medium"), conversation_id))
                    results["optimization_suggestions"] = len(suggestions)
            except Exception as e:
                logger.error(f"系统优化建议生成失败: {e}")

        results["skill_extracted"] = 0
        results["business_extracted"] = 0
        results["vault_exported"] = 0
        try:
            extractor = get_knowledge_extractor()
            extract_result = extractor.extract_all(
                conversation_id=conversation_id,
                conversation_text=summary,
                key_decisions=key_decisions,
                source_session_id=conversation_id,
            )
            results["skill_extracted"] = extract_result.get("skill_extracted", 0)
            results["business_extracted"] = extract_result.get("business_extracted", 0)
            results["knowledge_ids"] = extract_result.get("knowledge_ids", [])

            exporter = get_vault_exporter()
            vault_result = exporter.export_batch(
                conversation_id=conversation_id, summary=summary,
                key_decisions=key_decisions, steps_summary=[],
                knowledge_ids=extract_result.get("knowledge_ids", []),
            )
            results["vault_exported"] = (
                vault_result.get("skills_exported", 0) +
                vault_result.get("business_exported", 0)
            )
        except Exception as e:
            logger.warning(f"知识提取/Vault导出失败（非致命）: {e}")

        overall = results.get('overall_assessment', '')
        summary_stats = (
            f"系统问题={len(results.get('system_issues', []))}个, "
            f"不足={len(results.get('system_deficiencies', []))}个, "
            f"风险={len(results.get('risk_areas', []))}个"
        )

        if overall:
            llm_actions = f"LLM深层分析: {overall[:500]}"
            db.query_local("""
                UPDATE conversations SET analyzed = 1, updated_at = ?,
                    actions = CASE WHEN actions IS NULL OR actions = ''
                        THEN ? ELSE actions || ' | LLM_DEEP: ' || ? END
                WHERE conversation_id = ?
            """, (datetime.now().isoformat(), llm_actions, summary_stats, conversation_id))
        else:
            db.query_local("""
                UPDATE conversations SET analyzed = 1, updated_at = ?
                WHERE conversation_id = ?
            """, (datetime.now().isoformat(), conversation_id))

        try:
            reviewed = db.query_local("""
                UPDATE improvement_log SET status = 'reviewed'
                WHERE conversations_id = (
                    SELECT id FROM conversations WHERE conversation_id = ?
                ) AND status = 'pending'
            """, (conversation_id,))
            reviewed_count = reviewed if isinstance(reviewed, int) else (reviewed.rowcount if hasattr(reviewed, 'rowcount') else 0)
            if reviewed_count > 0:
                results["improvements_reviewed"] = reviewed_count
        except Exception:
            pass

        logger.info(f"🎉 对话全局分析完成: {conversation_id}")
        return results

    def handle_conversation_analysis(self, payload: dict) -> dict:
        """批量执行对话的所有待分析步骤"""
        conversation_id = payload.get("conversation_id")
        if not conversation_id:
            raise ValueError("Missing conversation_id")

        status_info = self.get_conversation_status(conversation_id)
        if not status_info:
            raise ValueError(f"Conversation not found: {conversation_id}")

        steps = status_info["steps"]
        total_steps = len(steps)
        results = []

        try:
            from devpartner_agent.services.callback_registry import get_callback_registry
            registry = get_callback_registry()

            for i, step in enumerate(steps):
                if step["status"] in ["pending", "failed"]:
                    registry.trigger_step_start(
                        conversation_id=conversation_id,
                        step_id=step["step_id"],
                        step_name=step.get("step_name", "Unknown"),
                    )

                    step_result = self.execute_single_step(step["step_id"])
                    results.append(step_result)

                    registry.trigger_step_complete(
                        conversation_id=conversation_id,
                        step_id=step["step_id"],
                        result=step_result,
                    )

                    progress_pct = ((i + 1) / total_steps) * 100
                    registry.trigger_progress(
                        conversation_id=conversation_id,
                        percentage=progress_pct,
                        message=f"步骤 {i + 1}/{total_steps}: {step.get('step_name', 'Unknown')}",
                    )

                    if step_result["status"] == "failed":
                        self.fail_conversation(conversation_id, f"Step failed: {step['step_id']}")
                        registry.trigger_error(conversation_id=conversation_id,
                                               error_message=f"Step failed: {step['step_id']}")
                        break
        except ImportError:
            for step in steps:
                if step["status"] in ["pending", "failed"]:
                    step_result = self.execute_single_step(step["step_id"])
                    results.append(step_result)
                    if step_result["status"] == "failed":
                        self.fail_conversation(conversation_id, f"Step failed: {step['step_id']}")
                        break

        return {
            "conversation_id": conversation_id,
            "steps_executed": len(results),
            "final_status": self.get_conversation_status(conversation_id)["conversation"]["status"],
        }

    def handle_profile_update(self, payload: dict) -> dict:
        """用户画像更新任务处理器"""
        user_traits = payload.get("user_traits", {})
        conversation_id = payload.get("conversation_id", "unknown")
        db = self._get_db()

        skills_observed = user_traits.get("skills_observed", [])
        for skill in skills_observed:
            db.query_local("""
                INSERT OR IGNORE INTO user_skills (
                    timestamp, skill_domain, skill_level, sub_skills,
                    evidence, last_updated
                ) VALUES (?, 'intermediate', ?, ?, ?)
            """, (
                datetime.now().isoformat(), skill,
                json.dumps([skill], ensure_ascii=False),
                f"自动检测自会话 {conversation_id}", datetime.now().isoformat(),
            ))
        return {"output": {"traits_extracted": len(skills_observed)}}

    def handle_knowledge_extraction(self, payload: dict) -> dict:
        """知识提取任务处理器"""
        content = payload.get("content", "")
        domain = payload.get("domain", "General")

        if not content.strip():
            return {"knowledge_extracted": 0, "error": "Empty content"}

        db = self._get_db()
        kp_id = db.insert_knowledge_point(
            title=f"[{domain}] 自动提取知识点",
            content=content[:2000],
            category="concept",
            domain=domain,
            tags=[domain, "auto-extracted"],
            source_type="task",
        )
        return {"knowledge_extracted": 1 if kp_id else 0, "knowledge_id": kp_id}

    def handle_system_optimization(self, payload: dict) -> dict:
        """系统优化建议生成任务处理器"""
        system_data = payload.get("system_data", {})
        improvement_history = payload.get("improvement_history", [])

        llm = self._get_llm()
        suggestions = llm.generate_self_improvement_suggestions(system_data, improvement_history)

        return {
            "suggestions_generated": len(suggestions) if suggestions else 0,
            "suggestions": suggestions or [],
        }

# ────────────────────────────────────────────────
    # 来自 conversation_analyzer.py 的方法
# ────────────────────────────────────────────────

    def analyze_and_store(self, content: str, source: str = "unknown",
                          client: str = "unknown", conversation_id: str = "") -> dict:
        """分析对话并存入数据库（直接更新 conversations 表）"""
        result = self.analyze(content, source, client)
        db = self._get_db()
        conv_id = conversation_id or datetime.now().strftime("%Y%m%d%H%M%S%f")

        try:
            skill_domains_str = json.dumps(result.get("skill_domains", []), ensure_ascii=False)
            complexity = result.get("complexity", "simple")
            db.query_local(
                "UPDATE conversations SET skill_domains = ?, complexity = ?, analyzed = 1 "
                "WHERE conversation_id = ?",
                (skill_domains_str, complexity, conv_id),
            )

            for domain_info in result.get("skill_domains", []):
                domain = domain_info.get("domain", "")
                sub_skills = domain_info.get("sub_skills", [])

                if domain:
                    db.upsert_user_skills(domain, {
                        "skill_level": self._estimate_skill_level(
                            domain, result.get("complexity", "simple"),
                            result.get("confidence", 0.5)
                        ),
                        "sub_skills": ", ".join(sub_skills) if sub_skills else "",
                        "evidence": result.get("summary", ""),
                        "conversation_ids": conv_id,
                        "hours_spent": self._estimate_time_spent(
                            result.get("complexity", "simple"), len(content)
                        ),
                        "growth_trend": "stable",
                    })

            user_traits = result.get("user_traits")
            if user_traits and isinstance(user_traits, dict) and result.get("confidence", 0) > 0.7:
                try:
                    llm = self._get_llm()
                    llm.apply_user_traits(user_traits, f"conv:{source}", conv_id)
                except Exception as e:
                    logger.debug(f"用户画像融合失败: {e}")

        except Exception as e:
            logger.error(f"对话存档失败: {e}", exc_info=True)

        return result

    def analyze(self, content: str, source: str = "unknown",
                client: str = "unknown") -> dict:
        """分析对话内容（主入口 — 委托 LLM）"""
        try:
            llm = self._get_llm()
            if llm and llm.is_available():
                logger.debug(f"使用 LLM 分析对话 [{source}:{client}]")
                result = llm.analyze_conversation(content, source, client)

                if result and result.get("confidence", 0) > 0.5:
                    result["analysis_version"] = "v7.5_llm"
                    result["analyzer_type"] = "unified_llm"
                    return result

                logger.warning("LLM 分析置信度过低，降级到简化模式")

        except Exception as e:
            logger.error(f"LLM 分析失败: {e}")

        return self._fallback_analysis(content, source, client)

    def _fallback_analysis(self, content: str, source: str, client: str) -> dict:
        """极简降级方案（LLM 不可用时的保底逻辑）"""
        content_lower = content.lower()

        simple_domains = {
            "Python": ["python", "django", "flask", "fastapi"],
            "前端": ["react", "vue", "javascript", "typescript"],
                "数据库": ["sql", "mysql", "redis", "mongodb"],
            "DevOps": ["docker", "git", "linux", "nginx"],
        }

        domains = []
        for domain, keywords in simple_domains.items():
            matched = [kw for kw in keywords if kw in content_lower]
            if matched:
                domains.append({
                    "domain": domain,
                    "sub_skills": matched[:3],
                    "match_score": 0.5,
                    "evidence": "基础关键词匹配",
                })

        complexity = "complex" if len(content) > 2000 else ("multi_step" if len(content) > 500 else "simple")

        return {
            "summary": content[:100] + ("..." if len(content) > 100 else ""),
            "skill_domains": sorted(domains, key=lambda x: x["match_score"], reverse=True)[:3],
            "complexity": complexity,
                    "complexity_reason": "基于内容长度的简单估算",
            "user_feedback": {"has_feedback": False, "types": [], "severity": "none"},
            "tool_gaps": [],
            "user_traits": {},
            "confidence": 0.3,
            "analysis_method": "fallback_simple_rules",
            "analysis_version": "v7.5_fallback",
        }

    def _estimate_skill_level(self, domain: str, complexity: str, confidence: float) -> str:
        base_level = "beginner"
        if confidence > 0.8:
            if complexity == "complex":
                base_level = "advanced"
            elif complexity == "multi_step":
                base_level = "intermediate"
        elif confidence > 0.6:
            if complexity in ("multi_step", "complex"):
                base_level = "intermediate"
        return base_level

    def _estimate_time_spent(self, complexity: str, content_length: int) -> float:
        if complexity == "complex":
            return min(content_length / 1000, 2.0)
        elif complexity == "multi_step":
            return min(content_length / 2000, 1.0)
        else:
            return 0.2

    def get_known_domains(self) -> dict:
        """获取已知的技能领域映射"""
        return {
            "Python": ["python", "django", "flask", "fastapi"],
            "前端": ["react", "vue", "javascript", "typescript"],
            "数据库": ["sql", "mysql", "redis", "mongodb"],
            "DevOps": ["docker", "git", "linux", "nginx"],
        }

# ────────────────────────────────────────────────
    # 来自 auto_analyzer.py 的方法
# ────────────────────────────────────────────────

    def analyze_pending_conversations(self, db, limit: int = 10) -> dict:
        """批量分析未处理的对话（v8.0: 从 conversations 表直接查询 analyzed=0 的记录）"""
        conversations = db.query_local(
            "SELECT id, conversation_id, topic, task_type, raw_json "
            "FROM conversations WHERE analyzed = 0 "
            "ORDER BY timestamp ASC LIMIT ?",
            (limit,)
        )

        analyzed_count = 0

        for conv in conversations:
            conv_id = conv.get("id")
            conv_biz_id = conv.get("conversation_id", "")
            raw_content = conv.get("raw_json", "")
            conv_topic = conv.get("topic", "")

            if not raw_content:
                db.query_local(
                    "UPDATE conversations SET analyzed = 1, skill_domains = '[]', complexity = 'simple' "
                    "WHERE id = ?",
                    (conv_id,)
                )
                analyzed_count += 1
                continue

            try:
                content = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
                analysis = self.analyze(content)

                skill_domains = analysis.get("skill_domains", [])
                complexity = analysis.get("complexity", "simple")
                user_feedback = analysis.get("user_feedback", {})

                skill_domains_str = json.dumps(skill_domains, ensure_ascii=False)
                feedback_type_str = json.dumps(user_feedback.get("types", []), ensure_ascii=False)

                db.query_local(
                    "UPDATE conversations SET skill_domains = ?, complexity = ?, "
                    "feedback_type = ?, analyzed = 1 WHERE id = ?",
                    (skill_domains_str, complexity, feedback_type_str, conv_id),
                )
                analyzed_count += 1

                if user_feedback.get("has_feedback") and user_feedback.get("severity") in ("high", "medium"):
                    try:
                        db.insert_improvement(
                            category="user_feedback_signal",
                            suggestion=f"对话 [{conv_topic}] 检测到用户反馈信号: "
                                       f"{user_feedback.get('types', [])} (严重度 {user_feedback.get('severity', '')})",
                            priority="high" if user_feedback.get("severity") == "high" else "medium",
                            conversations_id=conv_id,
                        )
                    except Exception:
                        pass

                for domain_info in skill_domains:
                    domain = domain_info.get("domain", "")
                    sub_skills = domain_info.get("sub_skills", [])
                    if domain:
                        try:
                            db.upsert_user_skills(domain, {
                                "skill_level": "intermediate" if complexity in ("complex", "multi_step") else "beginner",
                                "sub_skills": ", ".join(sub_skills) if sub_skills else "",
                                "evidence": f"auto_analyzer: {conv_topic[:100]}",
                                "conversation_ids": conv_biz_id,
                                "hours_spent": 0.2 if complexity == "simple" else 0.5 if complexity == "multi_step" else 1.0,
                                "growth_trend": "stable",
                            })
                        except Exception:
                            pass

                user_traits = analysis.get("user_traits")
                if user_traits and isinstance(user_traits, dict):
                    try:
                        self.apply_user_traits(user_traits, "auto_analyzer:llm", conv_id)
                    except Exception:
                        pass

            except Exception as e:
                db.query_local(
                    "UPDATE conversations SET analyzed = 1, skill_domains = '[]', complexity = 'simple' "
                    "WHERE id = ?",
                    (conv_id,)
                )
                analyzed_count += 1
                try:
                    db.insert_improvement(
                        category="auto_analyzer_error",
                        suggestion=f"自动分析 conversation#{conv_id} 失败: {str(e)[:300]}",
                        priority="low",
                    )
                except Exception:
                    pass

        if analyzed_count > 0:
            try:
                db.log_evolution(
                    change_type="auto_analyze",
                    description=f"自动分析完成: {analyzed_count} 条存档已分析",
                    files_changed="conversations,user_skills",
                    version="7.5.0",
                )
            except Exception:
                pass

        return {
            "analyzed": analyzed_count,
            "timestamp": datetime.now().isoformat(),
        }

    def analyze_single_conversation(self, db, conversations_id: int) -> dict:
        """分析单条对话"""
        conv_data = db.get_conversation_with_relations(conversations_id)
        if not conv_data:
            return {"error": f"conversations#{conversations_id} 不存在"}

        conversation = conv_data.get("conversation", {})
        raw_content = conversation.get("raw_json", "")
        if not raw_content:
            return {"error": f"conversations#{conversations_id} 没有原始对话数据"}

        return self.analyze_pending_conversations(db, limit=1)

# ────────────────────────────────────────────────
    # 来自 user_profile_service.py 的方法
# ────────────────────────────────────────────────

    def apply_user_traits(self, traits: dict, source: str = "unknown",
                          conversation_id: Optional[int] = None) -> dict:
        """将用户特征融合到 MCP 数据层"""
        if not traits or not isinstance(traits, dict):
            logger.warning("收到空的用户特征数据")
            return {"skills": 0, "improvements": 0}

        try:
            llm = self._get_llm()
            logger.info(f"融合用户特征 [{source}] - 技能数: {len(traits.get('skills_observed', []))}")
            result = llm.apply_user_traits(traits, source, conversation_id)
            return result
        except Exception as e:
            logger.error(f"用户画像融合失败: {e}", exc_info=True)
            return {"error": str(e), "skills": 0, "improvements": 0}

    def request_user_profile_analysis(
        self,
        analysis_scope: str = "recent",
        client_context: Optional[dict] = None,
    ) -> dict:
        """请求客户端进行用户画像分析"""
        db = self._get_db()

        recent_conversations = db.get_recent_conversations(limit=5)

        return {
            "analysis_request": {
                "scope": analysis_scope,
                "timestamp": datetime.now().isoformat(),
                "client_context": client_context or {},
            },
            "recent_data": recent_conversations[:3] if recent_conversations else [],
            "user_traits_schema": USER_TRAITS_SCHEMA,
            "project_strategy": PROJECT_STRATEGY,
            "few_shot_examples": FEW_SHOT_EXAMPLES,
            "analysis_guidelines": ANALYSIS_GUIDELINES,
        }

    def query_user_profile(
        self,
        dimensions: Optional[list[str]] = None,
        time_range: Optional[str] = None,
    ) -> dict:
        """查询用户画像数据"""
        db = self._get_db()

        skills_data = db.query_all_user_skills() or []

        behavior_data = []
        mistakes_data = []
        strengths_data = []
        learning_data = []

        for skill in skills_data:
            skill_name = skill.get("skill_name", "")
            if any(kw in skill_name.lower() for kw in ["习惯", "沟通", "决策", "情绪"]):
                behavior_data.append(skill)
            elif any(kw in skill_name.lower() for kw in ["错误", "问题", "不足"]):
                mistakes_data.append(skill)
            elif any(kw in skill_name.lower() for kw in ["优势", "强项", "擅长"]):
                strengths_data.append(skill)
            else:
                learning_data.append(skill)

        result = {
            "query_timestamp": datetime.now().isoformat(),
            "total_records": len(skills_data),
            "dimensions_available": {
                "skills": learning_data,
                "behavior": behavior_data,
                "mistakes": mistakes_data,
                "strengths": strengths_data,
                "learning_progress": learning_data[-5:] if learning_data else [],
            },
        }

        if dimensions:
            filtered = {k: v for k, v in result["dimensions_available"].items()
                        if k in (dimensions or [])}
            result["dimensions_available"] = filtered

        return result


_engine_instance: Optional[ConversationEngine] = None
_engine_lock = threading.Lock()


def get_conversation_engine() -> ConversationEngine:
    """获取全局对话引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ConversationEngine()
    return _engine_instance

def register_conversation_tools(mcp):
    """注册对话域的 MCP 工具（4 个核心工具已在 server.py 直接注册，此处为空壳保持一致性）"""
    pass


def register_task_handlers():
    """向 task_queue 注册对话域的所有任务处理器（v8.0 handler 注册机制）"""
    from devpartner_agent.services.task_queue import get_task_queue
    engine = get_conversation_engine()
    queue = get_task_queue()

    queue.register_handler("step_analysis", engine.handle_step_analysis)
    queue.register_handler("conversation_finalize", engine.handle_conversation_finalize)
    queue.register_handler("conversation_analysis", engine.handle_conversation_analysis)
    queue.register_handler("profile_update", engine.handle_profile_update)
    queue.register_handler("knowledge_extraction", engine.handle_knowledge_extraction)
    queue.register_handler("system_optimization", engine.handle_system_optimization)

    logger.info("📝 对话域任务处理器已注册 (6 个)")