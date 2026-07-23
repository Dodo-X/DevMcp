"""
Finalize 子任务: 知识图谱 MD 生成 (v9.10.1)
==========================================
从 finalize_handlers.py 拆出，非 LLM，统一走 MdExporter。
"""

import logging

from backend.business.conversation_mgr.constants import TRUNC_RULES
from backend.business.conversation_mgr.handlers.finalize_aggregator import (
    check_finalize_sub_tasks,
)
from backend.business.conversation_mgr.tracker import (
    wrap_finalize_complete,
    wrap_finalize_progress,
)

logger = logging.getLogger(__name__)


def handle_finalize_knowledge_graph(engine, payload: dict) -> dict:
    """v9.9.3: 对话知识摘要 MD 生成（非 LLM，统一走 MdExporter）
    v9.10.1: 重构 — 从 finalize_handlers.py 拆出
    """
    conversation_id = payload.get("conversation_id", "")
    on_progress = payload.get("_progress_callback")

    results = {
        "conversation_id": conversation_id,
        "dimension": "knowledge_graph",
        "success": False,
        "md_path": None,
        "kp_count": 0,
    }

    try:
        wrap_finalize_progress(on_progress, 0.1, "", "汇总: 对话知识摘要...")

        from backend.business.vault_export.md_exporter import get_md_exporter

        md_exporter = get_md_exporter()

        topic = payload.get("topic", "未命名对话")
        system_id = payload.get("system_id", "default")

        export_result = md_exporter.export_knowledge_summary(
            conversation_id=conversation_id,
            topic=topic,
            system_id=system_id,
            on_progress=on_progress,
        )
        results["success"] = export_result["success"]
        results["md_path"] = export_result.get("md_path")
        results["kp_count"] = export_result["kp_count"]

        if not export_result["success"] and export_result.get("error"):
            results["error"] = export_result["error"]

        wrap_finalize_complete(on_progress, "知识摘要 MD 生成完成")

    except Exception as e:
        logger.error(f"handle_finalize_knowledge_graph 失败: {e}", exc_info=True)
        results["error"] = str(e)[: TRUNC_RULES["error_msg"]]

    finally:
        check_finalize_sub_tasks(engine, conversation_id)

    return results
