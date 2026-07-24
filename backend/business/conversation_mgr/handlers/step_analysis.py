"""
步骤分析处理器 (v9.10.1)
========================
从 conversation_engine.py 拆出 handle_step_analysis。
"""

import logging
from datetime import datetime

from backend.business.conversation_mgr.tracker import (
    calc_duration_ms,
    log_step,
    wrap_llm_stream_progress,
    wrap_step_complete,
    wrap_step_progress,
)

logger = logging.getLogger(__name__)


def handle_step_analysis(engine, payload: dict) -> dict:
    """步骤分析任务处理器（v9.5.1: 支持进度报告）
    v9.10.1: 从 Engine 移出，通过 engine 参数获取 DAO/LLM/队列依赖
    """
    step_start = datetime.now()
    conversation_id = payload.get("conversation_id", "")
    step_id = payload.get("step_id", "")
    step_name = payload.get("step_name", "")
    content = payload.get("content", "")
    knowledge_points = payload.get("knowledge_points", [])
    step_type = payload.get("step_type", "general")
    symptom = payload.get("symptom", "")
    root_cause = payload.get("root_cause", "")
    solution = payload.get("solution", "")
    user_requirement = payload.get("user_requirement", "")
    commands_executed = payload.get("commands_executed", "")

    on_progress = payload.get("_progress_callback")
    dao = engine.dao

    results = {
        "skill_domains": [],
        "llm_analyzed": False,
    }

    extracted_kp: list[dict] = []
    try:
        llm = engine._get_llm()
        if llm and llm.is_available():
            wrap_step_progress(on_progress, step_name, "分析步骤")

            llm_result = llm.analyze_step_content(
                step_name=step_name,
                step_type=step_type,
                content=content,
                symptom=symptom,
                root_cause=root_cause,
                solution=solution,
                user_requirement=user_requirement,
                commands_executed=commands_executed,
                on_progress=wrap_llm_stream_progress(on_progress, step_name),
            )
            wrap_step_complete(on_progress, step_name, "步骤分析")

            if llm_result:
                results["llm_analyzed"] = True
                results["step_summary"] = llm_result.get("step_summary", "")
                results["skill_domains"] = llm_result.get("skill_domains", [])
                results["difficulty"] = llm_result.get("difficulty", "medium")
                results["problem_solving_pattern"] = llm_result.get("problem_solving_pattern", {})
                results["commands_used"] = llm_result.get("commands_used", [])
                results["key_insights"] = llm_result.get("key_insights", [])
                results["improvement_suggestions"] = llm_result.get("improvement_suggestions", [])
                extracted_kp = llm_result.get("knowledge_points", []) or []
                results["llm_knowledge_points"] = len(extracted_kp)
    except Exception as e:
        logger.warning(f"LLM 步骤分析失败（非致命）: {e}")

    # 收集步骤级通用知识点（来自 LLM 分析与 AI 透传），统一委托 KnowledgeExtractor 落库。
    # 修复旧 source_id=step_id 死链：统一以 source_id=conversation_id 回查（设计 §4.1）。
    step_kps: list[dict] = []
    step_kps.extend([k for k in extracted_kp if isinstance(k, dict)])
    step_kps.extend([k for k in (knowledge_points or []) if isinstance(k, dict)])

    kp_ids: list[str] = []
    if step_kps:
        try:
            from backend.business.knowledge_extractor.extract_service import (
                get_knowledge_extractor,
            )

            extractor = get_knowledge_extractor()
            kp_ids = extractor.extract_step_knowledge(step_kps, conversation_id)
        except Exception as e:
            logger.warning(f"步骤知识点落库失败（非致命）: {e}")

    actual_duration_ms = calc_duration_ms(step_start)
    dao.update_step_status(
        step_id=step_id,
        status="completed",
        output_data=results,
        completed_at=datetime.now().isoformat(),
        duration_ms=actual_duration_ms,
    )

    dao.sync_step_counts(conversation_id)
    log_step(
        conversation_id,
        step_id,
        f"Step analysis done | KP: {len(kp_ids)} | LLM: {results['llm_analyzed']}",
    )

    # 级联检查
    engine._cascade_check_conversation_complete(conversation_id)

    return results
