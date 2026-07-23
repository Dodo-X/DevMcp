"""
对话 Finalize 处理器 (v9.10.1)
==============================
从 conversation_engine.py 拆出 handle_conversation_finalize。
编排器模式：从 DB 读数据 → 提交三个独立子任务 → 立即返回。
"""

import json
import logging
from datetime import datetime

from backend.business.conversation_mgr.builder import (
    safe_json_parse,
)
from backend.business.conversation_mgr.constants import (
    DEFAULT_SYSTEM_ID,
    TASK_MEM_MB,
    TASK_PRIORITY,
)
from backend.business.conversation_mgr.tracker import (
    log_step,
    wrap_finalize_progress,
)

logger = logging.getLogger(__name__)


def handle_conversation_finalize(engine, payload: dict) -> dict:
    """v9.8.0 重构: 编排器模式 — 从 DB 读数据 → 提交三个独立子任务 → 立即返回。
    v9.10.1: 从 Engine 移出，通过 engine 参数获取依赖。
    """
    from backend.business.knowledge_extractor.extract_service import get_knowledge_extractor

    conversation_id = payload.get("conversation_id", "")
    ai_summary = payload.get("ai_summary", "")
    on_progress = payload.get("_progress_callback")
    dao = engine.dao
    queue = engine._get_task_queue()
    now = datetime.now().isoformat()

    results = {
        "conversation_id": conversation_id,
        "sub_tasks_queued": 0,
        "sub_task_ids": [],
    }

    # ── 从 DB 读取 conversation 元数据 ──
    conv_meta = dao.get_conversation_meta(conversation_id)
    topic = conv_meta.get("topic", "") or ""
    system_id = conv_meta.get("system_id", DEFAULT_SYSTEM_ID) or DEFAULT_SYSTEM_ID
    client = conv_meta.get("client", "unknown") or "unknown"
    user_raw_input = conv_meta.get("user_raw_input", "") or ""
    self_reflection = ai_summary or conv_meta.get("self_reflection", "") or ""
    ai_analysis_from_db = conv_meta.get("ai_analysis", "") or ""
    project_context = dao.get_system_context(system_id)

    # ── 聚合步骤数据 ──
    all_steps = dao.get_steps_with_input_data(conversation_id)
    summary_parts = []
    steps_summary = []
    for s in all_steps or []:
        input_raw = s.get("input_data", "")
        if input_raw:
            input_dict = safe_json_parse(input_raw, {})
            content = input_dict.get("content", "")
            if content:
                summary_parts.append(f"[{s.get('step_name', '')}]: {content[:500]}")
        step_info = {
            "name": s.get("step_name", ""),
            "type": s.get("step_type", ""),
            "status": s.get("status", ""),
            "created_at": s.get("created_at", ""),
        }
        output = s.get("output_data", "")
        if output:
            output_dict = safe_json_parse(output, {})
            step_info["thinking_patterns"] = output_dict.get("thinking_patterns", [])
            step_info["complexity"] = output_dict.get("complexity_level", "")
        steps_summary.append(step_info)
    summary = "\n".join(summary_parts)

    # ── 聚合 user_traits ──
    user_traits = {}
    trait_rows = dao.get_steps_with_user_traits(conversation_id)
    for tr in trait_rows or []:
        input_raw = tr.get("input_data", "")
        if input_raw:
            input_dict = safe_json_parse(input_raw, {})
            ut = input_dict.get("user_traits", {})
            if ut and isinstance(ut, dict):
                for k, v in ut.items():
                    if k not in user_traits:
                        user_traits[k] = v

    # ── 构造子任务共享上下文 ──
    shared_ctx = {
        "conversation_id": conversation_id,
        "topic": topic,
        "system_id": system_id,
        "client": client,
        "user_raw_input": user_raw_input,
        "project_context": project_context,
        "summary": summary,
        "self_reflection": self_reflection,
        "user_traits": user_traits,
        "key_decisions": [],
        "steps_summary": steps_summary,
        "ai_analysis": ai_analysis_from_db,
        "ai_summary": ai_summary,
    }

    # ── 提交三个独立子任务到 task_queue ──
    sub_tasks = [
        (
            "finalize_business_tech",
            TASK_PRIORITY["finalize_business_tech"],
            TASK_MEM_MB["finalize_business_tech"],
        ),
        (
            "finalize_user_profile",
            TASK_PRIORITY["finalize_user_profile"],
            TASK_MEM_MB["finalize_user_profile"],
        ),
        (
            "finalize_knowledge_graph",
            TASK_PRIORITY["finalize_knowledge_graph"],
            TASK_MEM_MB["finalize_knowledge_graph"],
        ),
    ]

    sub_task_ids = []
    for task_type, priority, mem_mb in sub_tasks:
        try:
            task_id = queue.submit_task(
                task_type=task_type,
                payload=dict(shared_ctx),
                priority=priority,
                estimated_memory_mb=mem_mb,
            )
            if task_id:
                sub_task_ids.append(task_id)
        except Exception as e:
            logger.warning(f"子任务提交失败 ({task_type}): {e}")

    results["sub_tasks_queued"] = len(sub_task_ids)
    results["sub_task_ids"] = sub_task_ids

    wrap_finalize_progress(on_progress, 0.3, "", f"已提交 {len(sub_task_ids)}/3 个深度分析子任务")

    # ── 非 LLM 部分：知识提取（同步执行）──
    results["skill_extracted"] = 0
    results["business_extracted"] = 0
    try:
        extract_text = summary
        if not extract_text:
            fallback_parts = []
            if ai_summary:
                fallback_parts.append(f"AI 总结:\n{ai_summary}")
            if self_reflection:
                fallback_parts.append(f"自我反思:\n{self_reflection}")
            extract_text = "\n\n".join(fallback_parts)
            if extract_text:
                logger.info("📝 summary 为空，使用 ai_summary/self_reflection 作为知识提取输入")

        extractor = get_knowledge_extractor()
        extract_result = extractor.extract_all(
            conversation_id=conversation_id,
            conversation_text=extract_text,
            key_decisions=[],
        )
        results["skill_extracted"] = extract_result.get("skill_extracted", 0)
        results["business_extracted"] = extract_result.get("business_extracted", 0)
        knowledge_ids = extract_result.get("knowledge_ids", [])
        results["knowledge_ids"] = knowledge_ids

        if knowledge_ids:
            try:
                queue.submit(
                    task_type="vault_export_batch",
                    payload={
                        "conversation_id": conversation_id,
                        "project": system_id or "",
                        "knowledge_ids": knowledge_ids,
                    },
                    priority=TASK_PRIORITY["vault_export_batch"],
                )
            except Exception as e:
                logger.warning(f"知识卡片导出任务提交失败（非致命）: {e}")
    except Exception as e:
        logger.warning(f"知识提取失败（非致命）: {e}")

    # ── project_description 评审（轻量独立 LLM 调用）──
    if system_id != DEFAULT_SYSTEM_ID:
        try:
            llm = engine._get_llm()
            if llm and llm.is_available():
                current_desc = dao.get_project_description(system_id)
                review_result = llm.review_project_description(
                    current_description=current_desc,
                    topic=topic,
                    summary=summary,
                    ai_summary=ai_summary,
                )
                if review_result and review_result.get("need_update"):
                    new_desc = (review_result.get("new_description") or "").strip()
                    if new_desc and new_desc != current_desc:
                        dao.update_project_description(system_id, new_desc)
                        logger.info(f"project_description 已更新: {system_id}")
                        try:
                            from backend.business.vault_export.vault_exporter import (
                                get_vault_exporter,
                            )

                            proj_row = dao.get_system_row(system_id)
                            if proj_row:
                                exporter = get_vault_exporter()
                                exporter.export_project_to_vault(system_id, proj_row)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"project_description 评审失败（非致命）: {e}")

    # ── 系统认知片段提取 ──
    try:
        tech_signals = []
        steps_files = dao.get_steps_input_data_only(conversation_id)
        seen_files = set()
        for s in steps_files or []:
            sd = safe_json_parse(s.get("input_data", "{}"), {})
            fc = sd.get("files_changed", "")
            if fc:
                fc_list = (
                    json.loads(fc)
                    if isinstance(fc, str)
                    else (fc if isinstance(fc, list) else [fc])
                )
                for f in fc_list:
                    if f and f not in seen_files:
                        seen_files.add(f)
                        tech_signals.append({"file": f, "type": "file_touched"})
        if tech_signals:
            dao.insert_system_context_fragment(
                conversation_id=conversation_id,
                system_id=system_id,
                tech_signals=tech_signals,
                architecture_signals=[],
                business_signals=[],
                new_discoveries=[],
                confidence=0.7,
                now=now,
            )
    except Exception as e:
        logger.warning(f"系统认知片段提取失败（非致命）: {e}")

    log_step(
        conversation_id,
        "",
        f"conversation_finalize 编排完成 | 子任务: {len(sub_task_ids)}/3 | "
        f"知识提取: {results['skill_extracted'] + results['business_extracted']}",
    )

    return results
