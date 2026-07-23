"""
Finalize 子任务: 业务技术评估 (v9.10.1)
=======================================
从 finalize_handlers.py 拆出，消除内联 SQL 和重复模式。
"""

import logging
from datetime import datetime

from backend.business.conversation_mgr.constants import (
    DEFAULT_CONFIDENCE,
    DEFAULT_SYSTEM_ID,
    TRUNC_RULES,
)
from backend.business.conversation_mgr.handlers.finalize_aggregator import (
    check_finalize_sub_tasks,
)
from backend.business.conversation_mgr.tracker import (
    log_step,
    wrap_finalize_complete,
    wrap_finalize_progress,
)

logger = logging.getLogger(__name__)


def handle_finalize_business_tech(engine, payload: dict) -> dict:
    """v9.8.2: 业务知识 + 技术决策 + 整体评估 子任务处理器
    v9.10.1: 重构 — 使用 DAO 层消除内联 SQL
    """
    conversation_id = payload.get("conversation_id", "")
    on_progress = payload.get("_progress_callback")
    dao = engine.dao
    now = datetime.now().isoformat()

    results = {"conversation_id": conversation_id, "dimension": "business_tech", "success": False}

    try:
        llm = engine._get_llm()
        if not llm or not llm.is_available():
            results["error"] = "LLM unavailable"
            return results

        wrap_finalize_progress(on_progress, 0.1, "", "深度分析: 业务知识 + 技术决策 + 整体评估...")

        bt_result = llm.analyze_business_tech(
            topic=payload.get("topic", ""),
            system_id=payload.get("system_id", DEFAULT_SYSTEM_ID),
            project_context=payload.get("project_context", ""),
            user_raw_input=payload.get("user_raw_input", ""),
            summary=payload.get("summary", ""),
            key_decisions=payload.get("key_decisions", []),
            ai_analysis=payload.get("ai_analysis", ""),
            on_progress=on_progress,
        )

        if not bt_result:
            results["error"] = "LLM returned empty"
            return results

        business_knowledge = bt_result.get("business_knowledge", {})
        technical_decisions = bt_result.get("technical_decisions", [])
        overall_assessment = bt_result.get("overall_assessment", {})

        # ── 写入 connected_systems ──
        system_id = payload.get("system_id", DEFAULT_SYSTEM_ID)
        if system_id != DEFAULT_SYSTEM_ID and business_knowledge.get("connected_systems"):
            try:
                for cs in business_knowledge["connected_systems"]:
                    if isinstance(cs, dict):
                        arch = cs.get("architecture", "") or ""
                        ts = cs.get("tech_stack", [])
                        bd = cs.get("business_rules", [])
                        if arch or ts or bd:
                            dao.update_connected_system(
                                system_id=system_id,
                                architecture=arch,
                                tech_stack=ts,
                                business_domains=bd,
                                now=now,
                            )
            except Exception:
                logger.warning(
                    "handle_finalize_business_tech: 未预期的异常被静默捕获（P-17 收口）",
                    exc_info=True,
                )
                pass

        # ── 构造信号 ──
        tech_signals = []
        architecture_signals = []
        business_signals = []
        new_discoveries = business_knowledge.get("new_discoveries", [])
        if isinstance(new_discoveries, list):
            business_signals = [str(d)[: TRUNC_RULES["business_signal"]] for d in new_discoveries]
        if isinstance(technical_decisions, list):
            for td in technical_decisions:
                if isinstance(td, dict):
                    decision_type = td.get("decision_type", "")
                    decision_str = (
                        f"{td.get('decision', '')[: TRUNC_RULES['decision_str']]} "
                        f"({td.get('reason', '')[: TRUNC_RULES['decision_str']]})"
                    )
                    if decision_type in ("架构设计", "技术选型"):
                        architecture_signals.append(decision_str)
                    else:
                        tech_signals.append(decision_str)

        tech_signals.append(
            f"对话质量: {overall_assessment.get('conversation_quality', '一般')}, "
            f"完成度: {overall_assessment.get('completeness', 0)}, "
            f"复杂度: {overall_assessment.get('complexity', 'moderate')}"
        )

        # ── 写入 system_context_fragments ──
        try:
            dao.insert_system_context_fragment(
                conversation_id=conversation_id,
                system_id=system_id,
                tech_signals=tech_signals,
                architecture_signals=architecture_signals,
                business_signals=business_signals,
                new_discoveries=business_knowledge.get("new_discoveries", []),
                confidence=DEFAULT_CONFIDENCE,
                now=now,
            )
        except Exception:
            logger.warning(
                "handle_finalize_business_tech: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            pass

        results["success"] = True
        results["decisions_count"] = (
            len(technical_decisions) if isinstance(technical_decisions, list) else 0
        )
        results["discoveries_count"] = (
            len(new_discoveries) if isinstance(new_discoveries, list) else 0
        )

        # ── 导出项目画像 MD ──
        if system_id != DEFAULT_SYSTEM_ID:
            try:
                from backend.business.vault_export.md_exporter import get_md_exporter

                md_exporter = get_md_exporter()
                results["md_exported"] = md_exporter.export_project_profile(system_id)
            except Exception as e:
                logger.warning(f"项目画像 MD 导出失败（非致命）: {e}")

        wrap_finalize_complete(on_progress, "业务技术评估完成")
        log_step(
            conversation_id,
            "",
            f"business_tech 分析完成 | 决策: {results['decisions_count']} | "
            f"发现: {results['discoveries_count']}",
        )

    except Exception as e:
        logger.error(f"handle_finalize_business_tech 失败: {e}", exc_info=True)
        results["error"] = str(e)[: TRUNC_RULES["error_msg"]]

    finally:
        check_finalize_sub_tasks(engine, conversation_id)

    return results
