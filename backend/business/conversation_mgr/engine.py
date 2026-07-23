"""
对话引擎 v9.10.1
=================
分层重构版本：DB/数据构造/埋点下沉到 dao/builder/tracker 层。
Engine 只做核心业务编排，不写任何 SQL 字符串。

职责：
  - start_conversation: 创建会话
  - record_step: 记录步骤
  - finalize_conversation: 全局总结 + 异步分析编排
  - execute_single_step: 执行/重试单个步骤
  - create_knowledge_point: 创建知识点
  - update_completed_steps: 更新会话已完成步骤数
  - get_system_health: 获取系统健康状态
  - get_known_domains: 获取已知技能领域

设计原则：
  - 所有 DB 操作通过 dao 层
  - 所有数据构造通过 builder 层
  - 所有埋点通过 tracker 层
  - 任务处理器在 handlers/ 子包中
"""

import logging
import threading
import uuid
from datetime import datetime
from typing import Any

from backend.business.conversation_mgr.builder import (
    DataBuilder,
    safe_json_parse,
)
from backend.business.conversation_mgr.constants import (
    DEFAULT_CLIENT,
    DEFAULT_SYSTEM_ID,
    DEFAULT_TASK_TYPE,
    MAX_RETRIES,
    TASK_MEM_MB,
    TASK_PRIORITY,
    TRUNC_RULES,
)
from backend.business.conversation_mgr.dao import ConversationDAO
from backend.business.conversation_mgr.tracker import (
    calc_duration_ms,
    log_step,
    track_write,
)
from backend.core.data_types.enums import StepStatus, StepType

logger = logging.getLogger(__name__)

# 模块级导入缓存
_builder = DataBuilder()


class ConversationEngine:
    """对话引擎 — 核心业务编排层（v9.10.1 瘦身重构）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._dao: ConversationDAO | None = None

    @property
    def dao(self) -> ConversationDAO:
        """懒加载 DAO"""
        if self._dao is None:
            self._dao = ConversationDAO(self._get_db())
        return self._dao

    # ══════════════════════════════════════════════════════════
    # 依赖获取
    # ══════════════════════════════════════════════════════════

    def _get_db(self):
        from backend.core.database.base_conn import get_db

        return get_db()

    def _get_task_queue(self):
        from backend.core.task_queue_kernel.queue_client import get_task_queue

        return get_task_queue()

    def _get_llm(self):
        from backend.core.llm_kernel.base_client import get_llm_engine

        return get_llm_engine()

    # ══════════════════════════════════════════════════════════
    # 对外 API
    # ══════════════════════════════════════════════════════════

    def start_conversation(
        self,
        client: str = DEFAULT_CLIENT,
        topic: str = "",
        task_type: str = DEFAULT_TASK_TYPE,
        user_intent: str = "",
        system_id: str = DEFAULT_SYSTEM_ID,
        user_raw_input: str = "",
        ai_analysis: str = "",
    ) -> dict:
        """创建新会话，返回会话状态。"""
        conv_id = f"conv_{uuid.uuid4().hex[:16]}"
        timestamp = datetime.now().isoformat()
        db = self._get_db()

        db.query_local(
            "INSERT INTO conversations ("
            "conversation_id, timestamp, client, topic, task_type,"
            "user_intent, status, created_at, updated_at,"
            "system_id, user_raw_input, ai_analysis,"
            "total_steps, completed_steps"
            ") VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, 0, 0)",
            (
                conv_id,
                timestamp,
                client,
                topic,
                task_type,
                user_intent,
                timestamp,
                timestamp,
                system_id,
                (user_raw_input or "")[: TRUNC_RULES["raw_input"]],
                (ai_analysis or "")[: TRUNC_RULES["ai_analysis"]],
            ),
        )

        if system_id != DEFAULT_SYSTEM_ID:
            self.dao.ensure_system_registered(system_id, client, timestamp)

        log_step(conv_id, "", f"创建会话 | 客户端 {client} | 系统 {system_id} | 主题: {topic}")
        return self.get_conversation_status(conv_id)

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
        """记录对话中的单个子任务步骤。"""
        db = self._get_db()
        queue = self._get_task_queue()
        dao = self.dao

        # FK 自保护
        dao.ensure_conversation_exists(
            conversation_id,
            client=DEFAULT_CLIENT,
            topic=step_name[: TRUNC_RULES["topic"]] or "自动创建的会话",
        )

        # 并发检测
        if client_request_id:
            existing_step_id = dao.check_duplicate_step(conversation_id, client_request_id)
            if existing_step_id:
                return {
                    "success": True,
                    "step_id": existing_step_id,
                    "duplicate": True,
                    "message": "Step already recorded (idempotent)",
                    "conversation_id": conversation_id,
                }

        # 创建步骤
        step_id = f"{conversation_id}_step_{datetime.now().strftime('%H%M%S%f')}"
        step_input = _builder.build_step_input(
            step_name=step_name,
            step_type=step_type,
            content=content,
            files_changed=files_changed,
            symptom=symptom,
            root_cause=root_cause,
            solution=solution,
            knowledge_points=knowledge_points,
            user_question=user_question,
            client_request_id=client_request_id,
            ai_reasoning=ai_reasoning,
            user_requirement=user_requirement,
            commands_executed=commands_executed,
        )

        try:
            dao.insert_step(step_id, conversation_id, step_name, step_input)
            track_write("insert_step", success=True)
        except Exception as e:
            error_msg = str(e)
            if "FOREIGN KEY" in error_msg.upper():
                result = self._fk_self_repair(
                    conversation_id,
                    step_name,
                    step_type,
                    content,
                    files_changed,
                    symptom,
                    root_cause,
                    solution,
                    knowledge_points,
                    user_question,
                    client_request_id,
                    ai_reasoning,
                    user_requirement,
                    commands_executed,
                )
                if result is not None:
                    track_write("insert_step", success=True)
                    return result
            track_write("insert_step", success=False)
            raise

        # 更新计数
        total, _ = dao.sync_step_counts(conversation_id)

        # 提交异步分析任务
        task_payload = _builder.build_task_payload(
            conversation_id,
            step_id,
            step_name,
            step_type,
            content=content,
            knowledge_points=knowledge_points,
            files_changed=files_changed,
            symptom=symptom,
            root_cause=root_cause,
            solution=solution,
            ai_reasoning=ai_reasoning,
            user_requirement=user_requirement,
            commands_executed=commands_executed,
        )

        task_id = queue.submit_task(
            task_type="step_analysis",
            payload=task_payload,
            priority=TASK_PRIORITY["step_analysis"],
            estimated_memory_mb=TASK_MEM_MB["step_analysis"],
        )

        if task_id:
            track_write("submit_task", success=True)
        else:
            track_write("submit_task", success=False)
            logger.warning(f"⚠️ 任务提交返回空 task_id: {conversation_id}/{step_name}")
            try:
                dao.mark_step_pending_retry(
                    step_id,
                    "Task queue submit returned empty task_id",
                )
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

    def _fk_self_repair(
        self,
        conversation_id: str,
        step_name: str = "",
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
    ) -> dict | None:
        """FK 约束自修复"""
        try:
            dao = self.dao
            dao.fk_repair_create_index()

            if not dao.fk_repair_check_exists(conversation_id):
                dao.fk_repair_create_conversation(conversation_id, step_name)
                logger.info(f"FK 自修复 自动创建 conversations 记录 {conversation_id}")

            step_id = f"{conversation_id}_step_{datetime.now().strftime('%H%M%S%f')}"
            step_input = _builder.build_step_input(
                step_name=step_name,
                step_type=step_type,
                content=content,
                files_changed=files_changed,
                symptom=symptom,
                root_cause=root_cause,
                solution=solution,
                knowledge_points=knowledge_points,
                user_question=user_question,
                client_request_id=client_request_id,
                ai_reasoning=ai_reasoning,
                user_requirement=user_requirement,
                commands_executed=commands_executed,
            )
            dao.insert_step(step_id, conversation_id, step_name, step_input)
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

    def finalize_conversation(
        self,
        conversation_id: str,
        ai_summary: str = "",
    ) -> dict:
        """对话结束时调用。薄层，立即返回。"""
        dao = self.dao
        queue = self._get_task_queue()
        now = datetime.now().isoformat()

        if ai_summary:
            dao.update_self_reflection(conversation_id, ai_summary, now)

        # 提交全局分析任务
        task_id = queue.submit_task(
            task_type="conversation_finalize",
            payload={
                "conversation_id": conversation_id,
                "finalized_at": now,
                "ai_summary": ai_summary[: TRUNC_RULES["ai_summary"]] if ai_summary else "",
            },
            priority=TASK_PRIORITY["conversation_finalize"],
            estimated_memory_mb=TASK_MEM_MB["conversation_finalize"],
        )

        # 异步软删除
        def _soft_delete():
            try:
                from backend.business.data_cleanup.cleanup_service import get_cleanup_service

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

    # ══════════════════════════════════════════════════════════
    # 查询方法
    # ══════════════════════════════════════════════════════════

    def get_conversation_status(self, conversation_id: str) -> dict | None:
        """获取会话详细状态"""
        dao = self.dao

        conv = dao.get_conversation(conversation_id)
        if not conv:
            return None

        steps = dao.get_steps(conversation_id)
        total = conv.get("total_steps") or 0
        completed = conv.get("completed_steps") or 0

        return {
            "conversation": conv,
            "steps": [dict(s) for s in steps],
            "progress": {
                "total": total,
                "completed": completed,
                "percentage": round(completed / max(1, total) * 100, 1),
            },
        }

    def get_system_health(self) -> dict:
        """获取系统健康状态"""
        return self.dao.get_system_health()

    def get_known_domains(self) -> dict:
        """获取已知的技能领域映射"""
        try:
            domains = self.dao.get_known_domains_from_kp()
            if domains:
                return domains
        except Exception:
            pass
        try:
            domains = self.dao.get_known_domains_from_skills()
            if domains:
                return domains
        except Exception:
            pass
        return {}

    # ══════════════════════════════════════════════════════════
    # 步骤执行
    # ══════════════════════════════════════════════════════════

    def execute_single_step(self, step_id: str, force_retry: bool = False) -> dict[str, Any]:
        """执行或重试单个步骤"""
        dao = self.dao

        step = dao.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")

        current_status = step["status"]

        if current_status == StepStatus.COMPLETED.value and not force_retry:
            return {"status": "already_completed", "step_id": step_id}

        if current_status == StepStatus.RUNNING.value and not force_retry:
            return {"status": "already_running", "step_id": step_id}

        start_time = datetime.now()
        dao.update_step_status(
            step_id=step_id,
            status="running",
            completed_at=start_time.isoformat(),
        )

        try:
            result = self._dispatch_step_execution(step)
            end_time = datetime.now()
            duration_ms = calc_duration_ms(start_time)

            knowledge_ids = result.get("knowledge_point_ids", [])

            dao.update_step_status(
                step_id=step_id,
                status="completed",
                output_data=result.get("output", {}),
                error_message=None,
                completed_at=end_time.isoformat(),
                duration_ms=duration_ms,
                retry_count=0,
            )

            self.update_completed_steps(step["conversation_id"])
            log_step(step["conversation_id"], step_id, f"步骤执行成功 | 耗时: {duration_ms}ms")

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
            max_retries = step.get("max_retries", MAX_RETRIES)

            if new_retry_count < max_retries:
                dao.update_step_status(
                    step_id=step_id,
                    status="pending",
                    error_message=str(e),
                    retry_count=new_retry_count,
                )
                return {
                    "status": "retry_scheduled",
                    "step_id": step_id,
                    "retry_count": new_retry_count,
                    "max_retries": max_retries,
                    "error": str(e),
                }
            else:
                dao.update_step_status(
                    step_id=step_id,
                    status="failed",
                    error_message=str(e),
                    completed_at=datetime.now().isoformat(),
                )
                return {
                    "status": "failed",
                    "step_id": step_id,
                    "error": str(e),
                    "retried": new_retry_count,
                }

    def _dispatch_step_execution(self, step: dict) -> dict[str, Any]:
        """根据步骤类型分发执行逻辑"""
        step_type = step["step_type"]
        input_data = safe_json_parse(step.get("input_data", ""), {})

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

    def _execute_analysis_step(self, step: dict, input_data: dict) -> dict[str, Any]:
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

    def _execute_knowledge_generation_step(self, step: dict, input_data: dict) -> dict[str, Any]:
        """执行知识点生成步骤"""
        dao = self.dao
        analysis_output = input_data.get("analysis_output", {})
        skill_domains = analysis_output.get("skill_domains", [])
        knowledge_ids = []

        for domain_info in skill_domains:
            domain = domain_info.get("domain", "General")
            sub_skills = domain_info.get("sub_skills", [])

            for skill in sub_skills:
                kp_id = dao.insert_knowledge_point(
                    title=f"[{domain}] {skill}",
                    content=f"技能点: {skill}\n领域: {domain}\n来源: 自动提取\n时间: {datetime.now().isoformat()}",
                    category="skill",
                    domain=domain,
                    tags=[domain, skill],
                    source_id=step["step_id"],
                )
                if kp_id:
                    knowledge_ids.append(kp_id)

        return {
            "output": {"knowledge_generated": len(knowledge_ids)},
            "knowledge_point_ids": knowledge_ids,
        }

    def _execute_user_profile_step(self, step: dict, input_data: dict) -> dict[str, Any]:
        """执行用户画像更新步骤"""
        analysis_output = input_data.get("analysis_output", {})
        user_traits = analysis_output.get("user_traits", {})

        from backend.core.llm_kernel.base_client import get_llm_engine

        llm = get_llm_engine()
        result = llm.apply_user_traits(user_traits, source="profile_step")

        return {"output": {"traits_extracted": result.get("skills", 0)}, "knowledge_point_ids": []}

    def _execute_system_optimize_step(self, step: dict, input_data: dict) -> dict[str, Any]:
        """执行系统优化建议步骤"""
        llm = self._get_llm()
        system_data = input_data.get("system_data", {})
        suggestions = llm.generate_self_improvement_suggestions(system_data)

        if suggestions:
            db = self._get_db()
            for suggestion in suggestions:
                db.query_local(
                    "INSERT INTO improvement_log ("
                    "timestamp, category, suggestion, priority, status, conversations_id"
                    ") VALUES (?, ?, ?, ?, 'pending', "
                    "(SELECT id FROM conversations WHERE conversation_id = ?))",
                    (
                        datetime.now().isoformat(),
                        suggestion.get("category", "general"),
                        suggestion.get("suggestion", ""),
                        suggestion.get("priority", "medium"),
                        step["conversation_id"],
                    ),
                )

            return {
                "output": {"suggestions_generated": len(suggestions)},
                "knowledge_point_ids": [],
            }
        else:
            return {"output": {"suggestions_generated": 0}, "knowledge_point_ids": []}

    # ══════════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════════

    def create_knowledge_point(
        self,
        title: str,
        content: str,
        category: str,
        domain: str,
        tags: list,
        source_id: str = "",
    ) -> str | None:
        """创建知识点记录"""
        kp_id = self.dao.insert_knowledge_point(
            title=title,
            content=content,
            category=category,
            domain=domain,
            tags=tags,
            source_id=source_id,
        )
        if kp_id:
            logger.info(f"📕 创建知识点 {kp_id} | {title}")
        return kp_id

    def update_completed_steps(self, conversation_id: str):
        """更新会话的已完成步骤数"""
        self.dao.sync_step_counts(conversation_id)

    def fail_conversation(self, conversation_id: str, error: str = "Unknown error"):
        """标记会话为失败"""
        self.dao.fail_conversation(conversation_id, error)
        logger.error(f"✗ 会话失败: {conversation_id} | 原因: {error}")

    def _cascade_check_conversation_complete(self, conversation_id: str):
        """级联检查 — 所有 step 完成时记录日志"""
        try:
            dao = self.dao
            completed, total, failed = dao.get_step_completion_stats(conversation_id)

            if total == 0:
                return

            if failed > 0:
                logger.info(
                    f"[级联检查] {conversation_id}: step {completed}/{total} (failed={failed})，"
                    f"等待 AI 调用 finalize"
                )
                return

            if completed < total:
                logger.debug(
                    f"[级联检查] {conversation_id}: step {completed}/{total}，等待剩余 step"
                )
                return

            logger.info(
                f"[级联检查] {conversation_id}: step 全部完成({completed}/{total})，"
                f"等待 AI 调用 finalize_conversation"
            )
        except Exception as e:
            logger.warning(f"[级联检查] {conversation_id} 级联检查异常（非致命）: {e}")


# ══════════════════════════════════════════════════════════
# 单例 + 任务注册
# ══════════════════════════════════════════════════════════

_engine_instance: ConversationEngine | None = None
_engine_lock = threading.Lock()


def get_conversation_engine() -> ConversationEngine:
    """获取全局对话引擎单例（双重检查锁）"""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ConversationEngine()
    return _engine_instance


def register_task_handlers():
    """向 task_queue 注册对话域的所有任务处理器（v9.10.1: 从 handlers/ 子包导入）"""
    from backend.business.conversation_mgr.handlers import (
        handle_conversation_analysis,
        handle_conversation_finalize,
        handle_finalize_business_tech,
        handle_finalize_knowledge_graph,
        handle_finalize_user_profile,
        handle_knowledge_extraction,
        handle_profile_update,
        handle_step_analysis,
        handle_system_optimization,
    )
    from backend.core.task_queue_kernel.queue_client import get_task_queue

    engine = get_conversation_engine()
    queue = get_task_queue()

    queue.register_handler("step_analysis", lambda p: handle_step_analysis(engine, p))
    queue.register_handler(
        "conversation_finalize", lambda p: handle_conversation_finalize(engine, p)
    )
    queue.register_handler(
        "conversation_analysis", lambda p: handle_conversation_analysis(engine, p)
    )
    queue.register_handler("profile_update", lambda p: handle_profile_update(engine, p))
    queue.register_handler("knowledge_extraction", lambda p: handle_knowledge_extraction(engine, p))
    queue.register_handler("system_optimization", lambda p: handle_system_optimization(engine, p))
    queue.register_handler(
        "finalize_business_tech", lambda p: handle_finalize_business_tech(engine, p)
    )
    queue.register_handler(
        "finalize_user_profile", lambda p: handle_finalize_user_profile(engine, p)
    )
    queue.register_handler(
        "finalize_knowledge_graph", lambda p: handle_finalize_knowledge_graph(engine, p)
    )

    logger.info("📝 对话域任务处理器已注册 (9 个)")
