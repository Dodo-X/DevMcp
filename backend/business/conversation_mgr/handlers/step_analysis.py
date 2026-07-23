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
    ai_reasoning = payload.get("ai_reasoning", "")
    user_requirement = payload.get("user_requirement", "")
    commands_executed = payload.get("commands_executed", "")

    on_progress = payload.get("_progress_callback")
    dao = engine.dao

    results = {
        "skill_domains": [],
        "llm_analyzed": False,
    }

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
                ai_reasoning=ai_reasoning,
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
                results["thinking_patterns"] = llm_result.get("thinking_patterns", [])
                results["commands_used"] = llm_result.get("commands_used", [])
                results["complexity_level"] = llm_result.get("complexity_level", "simple")
                results["key_insights"] = llm_result.get("key_insights", [])
                results["improvement_suggestions"] = llm_result.get("improvement_suggestions", [])
                results["related_tools"] = llm_result.get("related_tools", [])

                extracted_kp = llm_result.get("knowledge_points", [])
                if extracted_kp:
                    for kp in extracted_kp:
                        dao.insert_knowledge_point(
                            title=kp.get("title", "LLM提取知识点"),
                            content=kp.get("desc", ""),
                            category="llm_extracted",
                            domain=kp.get("domain", "General"),
                            tags=kp.get("tags", [step_type]),
                            source_id=step_id,
                        )
                    results["llm_knowledge_points"] = len(extracted_kp)
                else:
                    results["llm_knowledge_points"] = 0
    except Exception as e:
        logger.warning(f"LLM 步骤分析失败（非致命）: {e}")

    # 写入 AI 传的 knowledge_points
    kp_ids = []
    if knowledge_points:
        for kp in knowledge_points:
            kp_id = dao.insert_knowledge_point(
                title=kp.get("title", "未命名知识点"),
                content=kp.get("desc", ""),
                category="step_extracted",
                domain=kp.get("domain", "General"),
                tags=kp.get("tags", [step_type]),
                source_id=step_id,
            )
            if kp_id:
                kp_ids.append(kp_id)

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
