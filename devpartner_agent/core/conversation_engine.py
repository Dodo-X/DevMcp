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


def _track_write(operation: str, success: bool):
    """写入操作追踪（v8.5.6: 接入 WriteTracker）"""
    try:
        from devpartner_agent.services.cleanup_service import get_write_tracker
        tracker = get_write_tracker()
        if success:
            tracker.record_success(operation)
        else:
            tracker.record_failure(operation)
    except Exception:
        pass







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
        ai_analysis: str = "",
        trace_id: str = "",
        request_id: str = "",
        external_conv_id: str = "",
    ) -> dict:
        """""
        创建新会话，返回会话状态。

        v8.0 增强：
        - system_id: 多系统隔离标识，区分不同对接系统
        - user_raw_input: 用户原始输入，用于行为信号提取

        v9.1 增强：
        - ai_analysis: AI 对用户意图的分析推理过程（纯文本，系统异步分析）

        v9.3 增强：
        - trace_id: 外部调用链追踪ID（如 CodeBuddy 的 traceId）
        - request_id: 外部会话请求ID（如 CodeBuddy 的 conversationRequestId）
        - external_conv_id: 外部系统会话ID（如 CodeBuddy 的 conversationId）

        Returns:
            {"conversation_id": "...", "status": "active", ...}
        """""
        conv_id = f"conv_{uuid.uuid4().hex[:16]}"
        timestamp = datetime.now().isoformat()
        db = self._get_db()

        behavior_signals = {}

        db.query_local("""
            INSERT INTO conversations (
                conversation_id, timestamp, client, topic, task_type,
                user_intent, status, priority, created_at, updated_at,
                system_id, behavior_signals, user_raw_input, ai_analysis,
                trace_id, request_id, external_conv_id,
                total_steps, completed_steps
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """, (
            conv_id, timestamp, client, topic, task_type,
            user_intent, priority, timestamp, timestamp,
            system_id, json.dumps(behavior_signals, ensure_ascii=False),
            user_raw_input[:10000] if user_raw_input else "",
            ai_analysis[:50000] if ai_analysis else "",
            trace_id[:100] if trace_id else "",
            request_id[:100] if request_id else "",
            external_conv_id[:100] if external_conv_id else "",
        ))

        # v9.1.1: 异步 LLM 分析 ai_analysis → 填充 behavior_signals（替代硬编码关键词匹配）
        if ai_analysis:
            self._schedule_behavior_signals_extraction(
                conv_id, ai_analysis, user_raw_input or "", topic, task_type
            )

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
        ai_reasoning: str = "",
        user_requirement: str = "",
        commands_executed: str = "",
    ) -> dict:
        """""
        记录对话中的单个子任务步骤。

        包含：并发检测 → FK 自保护 → 步骤写入 → 异步任务提交

        v8.4 提纯字段:
        - ai_reasoning: AI 对用户需求的推测过程
        - user_requirement: 用户原始需求
        - commands_executed: 执行的命令及说明

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
                "SELECT step_id FROM conversation_steps WHERE conversation_id = ? AND input_data LIKE ? LIMIT 1",
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
            "ai_reasoning": ai_reasoning[:50000] if ai_reasoning else "",
            "user_requirement": user_requirement[:10000] if user_requirement else "",
            "commands_executed": commands_executed[:50000] if commands_executed else "",
            "recorded_at": datetime.now().isoformat(),
        }

        try:
            self._insert_step(db, step_id, conversation_id, step_name, step_input)
            _track_write("insert_step", success=True)
        except Exception as e:
            error_msg = str(e)
            if "FOREIGN KEY" in error_msg.upper():
                result = self._fk_self_repair(
                    db, conversation_id, step_name, step_id,
                    step_type, content, files_list, symptom,
                    root_cause, solution, kp_list, user_question,
                    client_request_id, ai_reasoning,
                    user_requirement, commands_executed,
                )
                if result is not None:
                    _track_write("insert_step", success=True)
                    return result
            _track_write("insert_step", success=False)
            raise

        # 更新会话总步骤数
        total = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversation_steps WHERE conversation_id = ?",
            (conversation_id,),
        )[0]["cnt"]
        db.query_local("""
            UPDATE conversations SET total_steps = ?, updated_at = ?
            WHERE conversation_id = ?
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
            "ai_reasoning": ai_reasoning[:50000] if ai_reasoning else "",
            "user_requirement": user_requirement[:10000] if user_requirement else "",
            "commands_executed": commands_executed[:50000] if commands_executed else "",
        }

        task_id = queue.submit_task(
            task_type="step_analysis",
            payload=task_payload,
            priority=8,
            estimated_memory_mb=100,
        )

        if task_id:
            _track_write("submit_task", success=True)
        else:
            _track_write("submit_task", success=False)
            logger.warning(f"⚠️ 任务提交返回空 task_id: {conversation_id}/{step_name}")
            # 标记 step 状态为 pending_retry，由 TaskTimeoutScheduler 后续扫描处理
            try:
                db.query_local("""
                    UPDATE conversation_steps SET
                        status = 'pending_retry',
                        error_message = 'Task queue submit returned empty task_id',
                        retry_count = 0
                    WHERE step_id = ?
                """, (step_id,))
            except Exception:
                pass

        return {
            "success": True,
            "step_id": step_id,
            "task_id": task_id,
            "queued": True,
            "conversation_id": conversation_id,
            "total_steps": total,
        }

    def _insert_step(self, db, step_id, conversation_id, step_name, step_input):
        """写入 conversation_steps 表（v9.2: depends_on 字段已删除）"""
        # 从 input_data 中提取 step_type（AI 传的值），而非硬编码 'analysis'
        actual_step_type = step_input.get("step_type", "general") if isinstance(step_input, dict) else "general"
        db.query_local("""
            INSERT INTO conversation_steps (
                step_id, conversation_id, conversations_id, step_order, step_type,
                step_name, status, input_data, max_retries,
                timeout_seconds, priority, created_at
            ) VALUES (?, ?,
                (SELECT id FROM conversations WHERE conversation_id = ?),
                (SELECT COALESCE(MAX(step_order), 0) + 1 FROM conversation_steps WHERE conversation_id = ?),
                ?, ?, 'pending', ?, 3, 300, 5, ?
            )
        """, (
            step_id, conversation_id, conversation_id, conversation_id,
            actual_step_type,
            step_name, json.dumps(step_input, ensure_ascii=False),
            datetime.now().isoformat(),
        ))

        db.query_local("""
            UPDATE conversation_steps SET started_at = ? WHERE step_id = ?
        """, (datetime.now().isoformat(), step_id))

    def _fk_self_repair(
        self, db, conversation_id, step_name, step_id,
        step_type, content, files_list, symptom,
        root_cause, solution, kp_list, user_question,
        client_request_id="", ai_reasoning="",
        user_requirement="", commands_executed="",
    ) -> Optional[dict]:
        """FK 约束自修复 — 如果 FOREIGN KEY 失败，自动尝试修复并重试"""
        try:
            cursor = db._local_conn.cursor()

            cursor.execute("""""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique
                ON conversations(conversation_id)
            """)

            exists = cursor.execute(
                "SELECT id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()

            if not exists:
                ts = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO conversations (conversation_id, timestamp, client, topic, task_type, status, priority, created_at, updated_at)
                    VALUES (?, ?, 'codebuddy', ?, 'general', 'active', 'medium', ?, ?)
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
                "client_request_id": client_request_id or "",
                "ai_reasoning": ai_reasoning[:50000] if ai_reasoning else "",
                "user_requirement": user_requirement[:10000] if user_requirement else "",
                "commands_executed": commands_executed[:50000] if commands_executed else "",
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
        ai_summary: str = "",
    ) -> dict:
        """
        对话结束时调用（v9.1 重构: AI 传 ai_summary 文本分析 + 系统从 DB 读结构化数据）。

        职责（薄层，立即返回）:
          1. 更新 conversations 状态为 completed
          2. 将 ai_summary 写入 self_reflection 字段
          3. 提交 conversation_finalize 异步任务（payload: conversation_id + ai_summary）
          4. 异步软删除关联任务

        Worker 会合并:
          - AI 传递的文本分析（ai_summary）
          - SQLite 结构化数据（conversations + conversation_steps 表）
        双向互补，做完整全局分析。

        Returns:
            {"success": true, "conversation_id": "...", "analysis_queued": true, ...}
        """
        db = self._get_db()
        queue = self._get_task_queue()
        now = datetime.now().isoformat()

        # 标记会话为已完成
        db.query_local("""
            UPDATE conversations SET
                status = 'completed', completed_at = ?, updated_at = ?
            WHERE conversation_id = ? AND status != 'completed'
        """, (now, now, conversation_id))

        # 标记总结已生成
        db.query_local("""
            UPDATE conversations SET summary_generated = 1, updated_at = ?
            WHERE conversation_id = ?
        """, (now, conversation_id))

        # v9.1: 将 AI 的最终分析总结写入 self_reflection 字段
        if ai_summary:
            db.query_local("""
                UPDATE conversations SET self_reflection = ?, updated_at = ?
                WHERE conversation_id = ?
            """, (ai_summary[:100000], now, conversation_id))

        # 提交全局分析任务 — payload 传 conversation_id + ai_summary
        # Worker 从 SQLite 读取结构化数据，与 AI 文本分析合并
        task_id = queue.submit_task(
            task_type="conversation_finalize",
            payload={
                "conversation_id": conversation_id,
                "finalized_at": now,
                "ai_summary": ai_summary[:100000] if ai_summary else "",
            },
            priority=10,
            estimated_memory_mb=200,
        )

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
        """用 LLM 改写问题为多个同义扩展查询（v8.5: 使用 prompts/ 外部 Prompt）"""
        try:
            from prompts import run_analysis, AnalysisTask
            from prompts._common import parse_json

            task = AnalysisTask(
                name="question_expand",
                description="技术问题同义扩展查询",
                prompt_template="""将以下技术问题改写为3个同义扩展查询词。

问题：{question}

请输出 JSON 格式：
```json
{{"queries": ["扩展词1", "扩展词2", "扩展词3"]}}
```
只输出 JSON。""",
                parser=parse_json,
                max_tokens=256,
                input_truncate=1000,
            )
            result = run_analysis(task, question=question)
            if result and isinstance(result, dict):
                return result.get("queries", [])[:3]
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
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if not conv:
            return None

        steps = db.query_local("""
            SELECT * FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order ASC
        """, (conversation_id,))

        # v9.5.1 修复: total_steps/completed_steps 可能为 None（旧数据/迁移不完整）
        total = conv[0].get("total_steps") or 0
        completed = conv[0].get("completed_steps") or 0
        return {
            "conversation": dict(conv[0]),
            "steps": [dict(s) for s in steps],
            "progress": {
                "total": total,
                "completed": completed,
                "percentage": round(
                    completed / max(1, total) * 100, 1
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
                "SELECT id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            if existing:
                return True

            ts = datetime.now().isoformat()
            db.query_local("""
                INSERT INTO conversations (
                    conversation_id, timestamp, client, topic, task_type,
                    status, priority, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', 'medium', ?, ?)
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
        db.query_local("""
            UPDATE conversation_steps SET status = 'running', started_at = ?
            WHERE step_id = ?
        """, (start_time.isoformat(), step_id))

        try:
            result = self._dispatch_step_execution(step)

            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            knowledge_ids = result.get("knowledge_point_ids", [])

            db.query_local("""
                UPDATE conversation_steps SET
                    status = 'completed', output_data = ?, error_message = NULL,
                    knowledge_point_ids = ?, completed_at = ?, duration_ms = ?, retry_count = 0
                WHERE step_id = ?
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
                db.query_local("""
                    UPDATE conversation_steps SET
                        status = 'pending', error_message = ?, retry_count = ?
                    WHERE step_id = ?
                """, (str(e), new_retry_count, step_id))

                return {
                    "status": "retry_scheduled",
                    "step_id": step_id,
                    "retry_count": new_retry_count,
                    "max_retries": max_retries,
                    "error": str(e),
                }
            else:
                db.query_local("""
                    UPDATE conversation_steps SET
                        status = 'failed', error_message = ?, completed_at = ?
                    WHERE step_id = ?
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

        # v9.3.6: 统一走 llm_engine.apply_user_traits()，不再旁路 INSERT
        from devpartner_agent.core.llm_engine import get_llm_engine
        llm = get_llm_engine()
        result = llm.apply_user_traits(user_traits, source="profile_step")

        return {"output": {"traits_extracted": result.get("skills", 0)}, "knowledge_point_ids": []}

    def _execute_system_optimize_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行系统优化建议步骤"""
        llm = self._get_llm()
        system_data = input_data.get("system_data", {})
        suggestions = llm.generate_self_improvement_suggestions(system_data)

        if suggestions:
            db = self._get_db()
            for suggestion in suggestions:
                db.query_local("""
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

        completed = db.query_local("""
            SELECT COUNT(*) as cnt FROM conversation_steps
            WHERE conversation_id = ? AND status = 'completed'
        """, (conversation_id,))[0]["cnt"]

        total = db.query_local("""
            SELECT COUNT(*) as cnt FROM conversation_steps
            WHERE conversation_id = ?
        """, (conversation_id,))[0]["cnt"]

        db.query_local("""
            UPDATE conversations SET
                completed_steps = ?, total_steps = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (completed, total, datetime.now().isoformat(), conversation_id))

        # v9.5.1: 加 None 防护（COUNT(*) 理论上不会返回 None，但防御性编程）
        if (completed or 0) >= (total or 0) and (total or 0) > 0:
            self.complete_conversation(conversation_id)

    def complete_conversation(self, conversation_id: str):
        """标记会话为已完成"""
        db = self._get_db()
        db.query_local("""
            UPDATE conversations SET
                status = 'completed', completed_at = , updated_at = 
            WHERE conversation_id =  AND status != 'completed'
        """, (datetime.now().isoformat(), datetime.now().isoformat(), conversation_id))
        logger.info(f"🎉 会话完成: {conversation_id}")

    def fail_conversation(self, conversation_id: str, error: str = "Unknown error"):
        """标记会话为失败"""
        db = self._get_db()
        db.query_local("""
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
        """步骤分析任务处理器（v9.5.1: 支持进度报告）"""
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
        ai_reasoning = payload.get("ai_reasoning", "")
        user_requirement = payload.get("user_requirement", "")
        commands_executed = payload.get("commands_executed", "")

        # v9.5.1: 任务队列注入的进度回调
        task_id = payload.get("_task_id", "")
        on_progress = payload.get("_progress_callback")

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
                if on_progress:
                    on_progress(0.05, "", f"正在分析步骤: {step_name[:50]}")
                llm_result = llm.analyze_step_content(
                    step_name=step_name, step_type=step_type,
                    content=content, symptom=symptom,
                    root_cause=root_cause, solution=solution,
                    ai_reasoning=ai_reasoning,
                    user_requirement=user_requirement,
                    commands_executed=commands_executed,
                )
                if on_progress:
                    on_progress(0.9, "", f"步骤分析完成: {step_name[:50]}")
                if llm_result:
                    results["llm_analyzed"] = True
                    results["step_summary"] = llm_result.get("step_summary", "")
                    results["skill_domains"] = llm_result.get("skill_domains", [])
                    results["difficulty"] = llm_result.get("difficulty", "medium")
                    results["problem_solving_pattern"] = llm_result.get("problem_solving_pattern", {})
                    results["thinking_patterns"] = llm_result.get("thinking_patterns", [])
                    results["commands_used"] = llm_result.get("commands_used", [])
                    results["complexity_level"] = llm_result.get("complexity_level", "simple")
                    results["key_insights"] = llm_result.get("key_insights", [])
                    results["improvement_suggestions"] = llm_result.get("improvement_suggestions", [])
                    results["related_tools"] = llm_result.get("related_tools", [])

                    extracted_kp = llm_result.get("knowledge_points", [])
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
        """对话全局分析任务处理器（v9.5.1: 支持进度报告）。

        数据源:
          - payload.ai_summary: AI 传递的最终分析总结（文本）
          - SQLite conversations 表: 会话元数据（topic, system_id, ai_analysis 等）
          - SQLite conversation_steps 表: 各步骤的 input_data/ai_reasoning
        """
        from devpartner_agent.services.knowledge_extractor import get_knowledge_extractor

        conversation_id = payload.get("conversation_id", "")
        ai_summary = payload.get("ai_summary", "")  # v9.1: AI 传递的文本分析
        on_progress = payload.get("_progress_callback")  # v9.5.1: 进度回调
        db = self._get_db()

        results = {
            "conversation_id": conversation_id,
            "traits_updated": 0,
            "decisions_recorded": 0,
            "quality_score": 0,
            "llm_deep_analyzed": False,
        }

        # ── v9.0: 从 SQLite 读取 conversation 全量元数据 ──
        # v9.2: 废弃字段 (decisions/problems/solutions/files_touched) 已从表删除
        conv_full = {}
        try:
            conv_row = db.query_local(
                "SELECT topic, system_id, client, user_raw_input, self_reflection, "
                "task_type, actions, skill_domains, complexity, ai_analysis "
                "FROM conversations WHERE conversation_id = ?",
                (conversation_id,)
            )
            if conv_row:
                conv_full = conv_row[0]
        except Exception:
            pass

        # 从 DB 解析各字段
        # v9.2: decisions 字段已删除，key_decisions 改为空列表（可从 steps 聚合重建）
        topic = conv_full.get("topic", "") or ""
        system_id = conv_full.get("system_id", "default") or "default"
        client = conv_full.get("client", "unknown") or "unknown"
        user_raw_input = conv_full.get("user_raw_input", "") or ""
        # v9.1: self_reflection 已由 finalize_conversation 写入 ai_summary；若 payload 也有则以 payload 为准
        self_reflection = ai_summary or conv_full.get("self_reflection", "") or ""
        ai_analysis_from_db = conv_full.get("ai_analysis", "") or ""
        key_decisions = []

        # ── v9.0: 从 conversation_steps 聚合 summary ──
        summary_parts = []
        try:
            all_steps = db.query_local(
                "SELECT step_name, step_type, status, input_data, output_data, created_at "
                "FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order",
                (conversation_id,)
            )
            for s in (all_steps or []):
                input_raw = s.get("input_data", "")
                if input_raw:
                    try:
                        input_dict = json.loads(input_raw) if isinstance(input_raw, str) else input_raw
                        content = input_dict.get("content", "")
                        if content:
                            summary_parts.append(f"[{s.get('step_name','')}]: {content[:500]}")
                    except Exception:
                        pass
        except Exception:
            pass
        summary = "\n".join(summary_parts)

        # ── v9.0: 从 conversation_steps 聚合 user_traits（AI已通过record_step写入）──
        user_traits = {}
        try:
            trait_rows = db.query_local(
                "SELECT input_data FROM conversation_steps "
                "WHERE conversation_id = ? AND input_data LIKE '%user_traits%' "
                "ORDER BY step_order",
                (conversation_id,)
            )
            for tr in (trait_rows or []):
                input_raw = tr.get("input_data", "")
                if input_raw:
                    try:
                        input_dict = json.loads(input_raw) if isinstance(input_raw, str) else input_raw
                        ut = input_dict.get("user_traits", {})
                        if ut and isinstance(ut, dict):
                            for k, v in ut.items():
                                if k not in user_traits:
                                    user_traits[k] = v
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            llm = self._get_llm()
            if llm and llm.is_available():
                if on_progress:
                    on_progress(0.1, "", "正在加载步骤数据...")
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

                if on_progress:
                    on_progress(0.2, "", "正在进行四维深度分析...")

                deep_result = llm.analyze_conversation_deep(
                    summary=summary, self_reflection=self_reflection,
                    user_traits=user_traits, key_decisions=key_decisions,
                    steps_summary=steps_summary,
                    topic=topic,
                    system_id=system_id,
                    ai_analysis=ai_analysis_from_db,  # v9.1: AI 的意图分析推理
                    ai_summary=ai_summary,  # v9.1: AI 的最终分析总结
                    client=client,
                    user_raw_input=user_raw_input,
                )

                if on_progress:
                    on_progress(0.7, "", "深度分析完成，正在入库...")
                    results["llm_deep_analyzed"] = True
                    results["business_knowledge"] = deep_result.get("business_knowledge", {})
                    results["user_profile"] = deep_result.get("user_profile", {})
                    results["technical_decisions"] = deep_result.get("technical_decisions", {})
                    results["knowledge_graph"] = deep_result.get("knowledge_graph", {})
                    results["overall_assessment"] = deep_result.get("overall_assessment", "")

                    # v9.0: 业务知识入库
                    biz_kps = (deep_result.get("business_knowledge", {}) or {}).get("knowledge_points", [])
                    for kp in biz_kps[:10]:
                        db.query_local("""
                            INSERT INTO improvement_log (
                                timestamp, category, suggestion, priority, status, conversations_id
                            ) VALUES (?, 'business_knowledge', ?, 'medium', 'pending',
                                (SELECT id FROM conversations WHERE conversation_id = ?)
                            )
                        """, (datetime.now().isoformat(),
                              f"业务知识: {kp.get('title', '')} | {kp.get('desc', '')}",
                              conversation_id))

                    # v9.0: 用户画像核心发现入库
                    up_core = (deep_result.get("user_profile", {}) or {}).get("core_findings", {})
                    if up_core:
                        db.query_local("""
                            INSERT INTO improvement_log (
                                timestamp, category, suggestion, priority, status, conversations_id
                            ) VALUES (?, 'user_profile', ?, 'low', 'pending',
                                (SELECT id FROM conversations WHERE conversation_id = ?)
                            )
                        """, (datetime.now().isoformat(),
                              json.dumps(up_core, ensure_ascii=False)[:500],
                              conversation_id))
        except Exception as e:
            logger.warning(f"LLM 深层对话分析失败（非致命）: {e}")

        results["system_context_extracted"] = False
        try:
            # v9.2: files_touched 字段已从 conversations 表删除，改为从 conversation_steps 聚合
            tech_signals, architecture_signals, business_signals, new_discoveries = [], [], [], []
            try:
                steps_files = db.query_local(
                    "SELECT input_data FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order",
                    (conversation_id,)
                )
                seen_files = set()
                for s in (steps_files or []):
                    try:
                        sd = json.loads(s.get("input_data", "{}"))
                        fc = sd.get("files_changed", "")
                        if fc:
                            fc_list = json.loads(fc) if isinstance(fc, str) else (fc if isinstance(fc, list) else [fc])
                            for f in fc_list:
                                if f and f not in seen_files:
                                    seen_files.add(f)
                                    tech_signals.append({"file": f, "type": "file_touched"})
                    except (json.JSONDecodeError, TypeError):
                        pass
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
                if on_progress:
                    on_progress(0.8, "", "正在生成系统优化建议...")
                llm = self._get_llm()
                suggestions = llm.generate_self_improvement_suggestions({
                    "reflection": self_reflection, "summary": summary,
                    "conversation_id": conversation_id,
                    "llm_deep_analysis": {
                        "business_knowledge": results.get("business_knowledge", {}),
                        "user_profile": results.get("user_profile", {}),
                        "technical_decisions": results.get("technical_decisions", {}),
                        "knowledge_graph": results.get("knowledge_graph", {}),
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
        try:
            if on_progress:
                on_progress(0.9, "", "正在提取知识...")
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

            # v8.5.0: MD 文件生成移至定时总结（日/周/月/年），finalize 阶段仅提取知识入库
        except Exception as e:
            logger.warning(f"知识提取失败（非致命）: {e}")

        overall = results.get('overall_assessment', '')
        biz_count = len((results.get('business_knowledge', {}) or {}).get('knowledge_points', []))
        kg_count = len((results.get('knowledge_graph', {}) or {}).get('knowledge_points', []))
        summary_stats = (
            f"业务知识={biz_count}条, "
            f"知识图谱={kg_count}条"
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
        # v9.3.6: 统一走 llm_engine.apply_user_traits()，不再旁路 INSERT
        from devpartner_agent.core.llm_engine import get_llm_engine
        llm = get_llm_engine()
        result = llm.apply_user_traits(user_traits, source="profile_update")
        return {"output": {"traits_extracted": result.get("skills", 0)}}

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
                        "skill_level": result.get("user_traits", {}).get("skill_level", "intermediate"),
                        "sub_skills": ", ".join(sub_skills) if sub_skills else "",
                        "evidence": result.get("summary", ""),
                        "conversation_ids": conv_id,
                        "hours_spent": 0.0,
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

        return {"summary": "pending", "skill_domains": [], "complexity": "simple",
                "confidence": 0.0, "analysis_method": "pending_llm", "user_traits": {}}



    def get_known_domains(self) -> dict:
        """获取已知的技能领域映射（v8.5: 从 DB 动态查询，不再硬编码）"""
        try:
            db = self._get_db()
            rows = db.query_local(
                "SELECT DISTINCT domain, tags FROM knowledge_points WHERE domain != '' AND type = 'skill'"
            )
            if rows:
                domains = {}
                for row in rows:
                    domain = row.get("domain", "")
                    tags = row.get("tags", "[]")
                    if isinstance(tags, str):
                        try:
                            tags = json.loads(tags)
                        except Exception:
                            tags = [tags]
                    if domain and domain not in domains:
                        domains[domain] = tags if isinstance(tags, list) else []
                if domains:
                    return domains
        except Exception:
            pass
        # 降级：从 user_skills 表推断
        try:
            db = self._get_db()
            rows = db.query_local("SELECT DISTINCT skill_name FROM user_skills LIMIT 20")
            if rows:
                domains = {}
                for row in rows:
                    name = row.get("skill_name", "")
                    if name:
                        domains[name] = [name.lower()]
                if domains:
                    return domains
        except Exception:
            pass
        return {}

    def _schedule_behavior_signals_extraction(self, conv_id: str, ai_analysis: str,
                                                user_raw_input: str, topic: str,
                                                task_type: str):
        """v9.1.1: 异步提交 LLM 任务分析 ai_analysis → behavior_signals"""
        try:
            from prompts.user_profile import TASK_BEHAVIOR_SIGNALS
            tq = self._get_task_queue()
            if tq:
                tq.enqueue(
                    "behavior_signals_extraction",
                    {
                        "conversation_id": conv_id,
                        "ai_analysis": ai_analysis[:4000],
                        "user_raw_input": user_raw_input[:2000],
                        "topic": topic,
                        "task_type": task_type,
                        "prompt_name": TASK_BEHAVIOR_SIGNALS.name,
                    },
                    priority=5,  # 低优先级，不阻塞主流程
                )
                logger.debug(f"已调度 behavior_signals 提取任务: {conv_id}")
        except Exception as e:
            logger.debug(f"调度 behavior_signals 提取失败（非致命）: {e}")

# ────────────────────────────────────────────────
    # 来自 auto_analyzer.py 的方法
# ────────────────────────────────────────────────

    def analyze_pending_conversations(self, db, limit: int = 10) -> dict:
        """批量分析未处理的对话（v9.2: raw_json 字段已删除，改用 ai_analysis）"""
        conversations = db.query_local(
            "SELECT id, conversation_id, topic, task_type, ai_analysis, self_reflection "
            "FROM conversations WHERE analyzed = 0 "
            "ORDER BY timestamp ASC LIMIT ?",
            (limit,)
        )

        analyzed_count = 0

        for conv in conversations:
            conv_id = conv.get("id")
            conv_biz_id = conv.get("conversation_id", "")
            raw_content = conv.get("ai_analysis", "") or conv.get("self_reflection", "")
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

    def handle_behavior_signals_extraction(self, payload: dict) -> dict:
        """v9.1.1: LLM 分析 ai_analysis → 更新 behavior_signals 字段"""
        conv_id = payload.get("conversation_id", "")
        ai_analysis = payload.get("ai_analysis", "")
        user_raw_input = payload.get("user_raw_input", "")
        topic = payload.get("topic", "")
        task_type = payload.get("task_type", "")

        if not conv_id or not ai_analysis:
            return {"error": "缺少必要字段", "conversation_id": conv_id}

        try:
            llm = self._get_llm()
            if not llm or not llm.is_available():
                logger.debug(f"LLM 不可用，跳过 behavior_signals 提取: {conv_id}")
                return {"conversation_id": conv_id, "skipped": True, "reason": "llm_unavailable"}

            from prompts.user_profile import TASK_BEHAVIOR_SIGNALS
            raw = llm.execute_task(
                TASK_BEHAVIOR_SIGNALS,
                ai_analysis=ai_analysis,
                user_raw_input=user_raw_input,
                topic=topic,
                task_type=task_type,
                input_length=len(user_raw_input),
                has_code_block="```" in user_raw_input,
                has_question_mark=("?" in user_raw_input or "？" in user_raw_input),
            )
            parsed = TASK_BEHAVIOR_SIGNALS.parser(raw) if TASK_BEHAVIOR_SIGNALS.parser else {}

            if parsed and not parsed.get("parse_error"):
                db = self._get_db()
                db.query_local(
                    "UPDATE conversations SET behavior_signals = ? WHERE conversation_id = ?",
                    (json.dumps(parsed, ensure_ascii=False), conv_id),
                )
                logger.debug(f"behavior_signals 已更新: {conv_id}")
                return {"conversation_id": conv_id, "updated": True}
            else:
                logger.warning(f"behavior_signals 解析失败: {conv_id}")
                return {"conversation_id": conv_id, "updated": False, "reason": "parse_error"}
        except Exception as e:
            logger.error(f"behavior_signals 提取失败: {conv_id}: {e}")
            return {"conversation_id": conv_id, "error": str(e)}

    def handle_daily_summary(self, payload: dict) -> dict:
        """v9.5.1: 日报生成 handler（替代 Scheduler 同步调用）"""
        from devpartner_agent.skills.daily_summary import (
            generate_daily_summary, get_daily_work_data,
            _check_llm_available, _write_pending_analysis,
        )

        target_date = payload.get("target_date", datetime.now().strftime("%Y-%m-%d"))
        on_progress = payload.get("_progress_callback")
        trigger_time_str = payload.get("trigger_time", datetime.now().isoformat())
        trigger_time = datetime.fromisoformat(trigger_time_str) if trigger_time_str else datetime.now()

        db = self._get_db()

        if on_progress:
            on_progress(0.05, "", f"日报生成: 检查 LLM 可用性...")

        # v8.1: 先检查 LLM 是否可用
        llm_ok, llm_reason = _check_llm_available()
        if not llm_ok:
            raw_data = get_daily_work_data(date_str=target_date, fallback_to_log=True)
            if raw_data.get("conversations") or raw_data.get("stats"):
                _write_pending_analysis(
                    db=db,
                    analysis_type="daily_summary",
                    source_date=target_date,
                    raw_data=raw_data,
                    missing_dimensions=["summary", "experience", "skills", "knowledge", "self_analysis"],
                    error_message=llm_reason,
                )
                logger.warning(f"⏸️ LLM 不可用 ({llm_reason})，每日总结数据已暂存 pending_analyses")
            else:
                logger.info("ℹ️ 今日无对话数据，跳过每日总结")
            return {"success": True, "method": "pending", "reason": llm_reason}

        if on_progress:
            on_progress(0.15, "", f"日报生成: 正在获取 {target_date} 数据...")

        result = generate_daily_summary(date_str=target_date, use_llm=True)

        if not result.get("success"):
            logger.warning(f"⚠️ 每日总结生成失败: {result.get('error', 'unknown')}")
            return {"success": False, "error": result.get("error", "unknown")}

        if result.get("analysis_method") == "none":
            logger.info("ℹ️ 今日无对话数据，跳过每日总结")
            return {"success": True, "method": "none"}

        summary_data = result.get("summary", {})
        method = result.get("analysis_method", "unknown")

        # v8.1: 仅 LLM 分析成功时才写入 improvement_log
        if method == "llm" and result.get("llm_available"):
            if on_progress:
                on_progress(0.8, "", "日报生成: 正在写入 improvement_log...")
            db.insert_improvement_with_dimensions(
                category="daily_profile_summary",
                dimensions={
                    "summary_type": "daily",
                    "date": target_date,
                    "total_conversations": summary_data.get("total_conversations", 0),
                    "analysis_method": method,
                    "llm_available": True,
                    "generated_by": "scheduler_daily",
                },
                priority="low",
            )

            conv_count = summary_data.get("total_conversations", 0)
            logger.info(f"✅ 每日工作总结完成: {conv_count} 条对话, 方式={method}")

            if on_progress:
                on_progress(0.9, "", "日报生成: 正在导出 MD...")
            try:
                from devpartner_agent.services.vault_exporter import get_vault_exporter
                exporter = get_vault_exporter()
                report_path = exporter.export_daily_report(target_date, result)
                if report_path:
                    logger.info(f"📅 日报已导出到 Calendar: {report_path}")
            except Exception as export_err:
                logger.warning(f"⚠️ 日报 MD 导出失败: {export_err}")
        else:
            # LLM 返回了结果但不是 LLM 模式（rules_fallback），暂存
            raw_data = get_daily_work_data(date_str=target_date, fallback_to_log=True)
            if raw_data.get("conversations") or raw_data.get("stats"):
                _write_pending_analysis(
                    db=db,
                    analysis_type="daily_summary",
                    source_date=target_date,
                    raw_data=raw_data,
                    missing_dimensions=["summary", "experience", "skills", "knowledge", "self_analysis"],
                    error_message=f"LLM 分析返回非预期模式: {method}",
                )
                logger.warning(f"⚠️ LLM 分析异常 (method={method})，数据已暂存 pending_analyses")

        if on_progress:
            on_progress(1.0, "", "日报生成完成")

        return {"success": True, "method": method, "conversation_count": summary_data.get("total_conversations", 0)}


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
    queue.register_handler("behavior_signals_extraction", engine.handle_behavior_signals_extraction)
    queue.register_handler("daily_summary", engine.handle_daily_summary)

    logger.info("📝 对话域任务处理器已注册 (8 个)")