"""
杂项任务处理器 (v9.10.1)
========================
从 conversation_engine.py 拆出，包含：
  - handle_conversation_analysis: 批量执行对话步骤
  - handle_profile_update: 用户画像更新
  - handle_knowledge_extraction: 知识提取
  - handle_system_optimization: 系统优化建议
"""

import logging

from backend.business.conversation_mgr.constants import TRUNC_RULES

logger = logging.getLogger(__name__)


def handle_conversation_analysis(engine, payload: dict) -> dict:
    """批量执行对话的所有待分析步骤"""
    conversation_id = payload.get("conversation_id")
    if not conversation_id:
        raise ValueError("Missing conversation_id")

    dao = engine.dao
    status_info = engine.get_conversation_status(conversation_id)
    if not status_info:
        raise ValueError(f"Conversation not found: {conversation_id}")

    steps = status_info["steps"]
    total_steps = len(steps)
    results = []

    try:
        from backend.core.task_queue_kernel.callback_registry import get_callback_registry

        registry = get_callback_registry()

        for i, step in enumerate(steps):
            if step["status"] in ["pending", "failed"]:
                registry.trigger_step_start(
                    conversation_id=conversation_id,
                    step_id=step["step_id"],
                    step_name=step.get("step_name", "Unknown"),
                )

                step_result = engine.execute_single_step(step["step_id"])
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
                    dao.fail_conversation(conversation_id, f"Step failed: {step['step_id']}")
                    registry.trigger_error(
                        conversation_id=conversation_id,
                        error_message=f"Step failed: {step['step_id']}",
                    )
                    break
    except ImportError:
        for step in steps:
            if step["status"] in ["pending", "failed"]:
                step_result = engine.execute_single_step(step["step_id"])
                results.append(step_result)
                if step_result["status"] == "failed":
                    dao.fail_conversation(conversation_id, f"Step failed: {step['step_id']}")
                    break

    return {
        "conversation_id": conversation_id,
        "steps_executed": len(results),
        "final_status": engine.get_conversation_status(conversation_id)["conversation"]["status"],
    }


def handle_profile_update(engine, payload: dict) -> dict:
    """用户画像更新任务处理器"""
    user_traits = payload.get("user_traits", {})
    from backend.core.llm_kernel.base_client import get_llm_engine

    llm = get_llm_engine()
    result = llm.apply_user_traits(user_traits, source="profile_update")
    return {"output": {"traits_extracted": result.get("skills", 0)}}


def handle_knowledge_extraction(engine, payload: dict) -> dict:
    """知识提取任务处理器"""
    content = payload.get("content", "")
    domain = payload.get("domain", "General")

    if not content.strip():
        return {"knowledge_extracted": 0, "error": "Empty content"}

    dao = engine.dao
    kp_id = dao.insert_knowledge_point(
        title=f"[{domain}] 自动提取知识点",
        content=content[: TRUNC_RULES["knowledge_content"]],
        category="concept",
        domain=domain,
        tags=[domain, "auto-extracted"],
    )
    return {"knowledge_extracted": 1 if kp_id else 0, "knowledge_id": kp_id}


def handle_system_optimization(engine, payload: dict) -> dict:
    """系统优化建议生成任务处理器"""
    system_data = payload.get("system_data", {})
    improvement_history = payload.get("improvement_history", [])

    llm = engine._get_llm()
    suggestions = llm.generate_self_improvement_suggestions(system_data, improvement_history)

    return {
        "suggestions_generated": len(suggestions) if suggestions else 0,
        "suggestions": suggestions or [],
    }
