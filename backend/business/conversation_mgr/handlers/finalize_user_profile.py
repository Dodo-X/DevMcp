"""
Finalize 子任务: 用户画像分析 (v9.10.1)
=======================================
从 finalize_handlers.py 拆出，使用 DAO 层消除内联 SQL。
"""

import json
import logging
from datetime import datetime

from backend.business.conversation_mgr.constants import (
    DEFAULT_PROFILE_CONFIDENCE,
    TRUNC_RULES,
    USER_PROFILE_DIMENSION_MAP,
    USER_PROFILE_JSON_DIMENSIONS,
)
from backend.business.conversation_mgr.handlers.finalize_aggregator import (
    check_finalize_sub_tasks,
    merge_skills_from_profile,
)
from backend.business.conversation_mgr.tracker import (
    log_step,
    wrap_finalize_complete,
    wrap_finalize_progress,
)

logger = logging.getLogger(__name__)


def handle_finalize_user_profile(engine, payload: dict) -> dict:
    """v9.8.1: 用户画像深度分析 子任务处理器
    v9.10.1: 重构 — 使用 DAO 层消除内联 SQL
    """
    conversation_id = payload.get("conversation_id", "")
    on_progress = payload.get("_progress_callback")
    dao = engine.dao

    results = {"conversation_id": conversation_id, "dimension": "user_profile", "success": False}

    try:
        llm = engine._get_llm()
        if not llm or not llm.is_available():
            results["error"] = "LLM unavailable"
            return results

        wrap_finalize_progress(on_progress, 0.1, "", "深度分析: 用户画像...")

        up_result = llm.analyze_user_profile(
            user_raw_input=payload.get("user_raw_input", ""),
            ai_analysis=payload.get("ai_analysis", ""),
            on_progress=on_progress,
        )

        if not up_result:
            results["error"] = "LLM returned empty"
            return results

        profile = up_result.get("user_profile", {})
        if not profile:
            results["error"] = "No user_profile in result"
            return results

        # ── 写入 user_profile 维度表 ──
        now = datetime.now().isoformat()
        evidence = f"llm_user_profile_v9.8.1: conv={conversation_id}"
        profile_confidence = profile.get("profile_confidence", DEFAULT_PROFILE_CONFIDENCE)

        for dim_name, dim_key in USER_PROFILE_DIMENSION_MAP.items():
            dim_value = profile.get(dim_name, "")
            if not dim_value or dim_value in ("[]", ""):
                continue
            # 列表类型维度需要 JSON 序列化
            if dim_name in USER_PROFILE_JSON_DIMENSIONS:
                dim_value = json.dumps(dim_value, ensure_ascii=False)
            try:
                dao.upsert_user_profile_dimension(
                    dim_key=dim_key,
                    dim_value=str(dim_value)[: TRUNC_RULES["profile_value"]],
                    confidence=profile_confidence,
                    evidence=evidence,
                    now=now,
                )
            except Exception as e:
                logger.debug(f"user_profile 维度写入失败 [{dim_key}]: {e}")

        # ── 技能写入 ──
        skills_observed = profile.get("skills_observed", [])
        if skills_observed:
            try:
                merge_skills_from_profile(dao, conversation_id, skills_observed, profile)
            except Exception as e:
                logger.warning(f"技能写入失败（非致命）: {e}")

        # ── 学习规划 ──
        areas_for_growth = profile.get("areas_for_growth", [])
        if isinstance(areas_for_growth, str):
            areas_for_growth = [areas_for_growth]
        for area in areas_for_growth:
            try:
                dao.set_skill_plan(domain=str(area), goal=f"提升 {area}")
            except Exception:
                logger.warning(
                    "handle_finalize_user_profile: 未预期的异常被静默捕获（P-17 收口）",
                    exc_info=True,
                )
                pass

        results["success"] = True
        results["skills_count"] = len(skills_observed) if isinstance(skills_observed, list) else 0

        # ── 导出用户画像 MD ──
        try:
            from backend.business.vault_export.md_exporter import get_md_exporter

            md_exporter = get_md_exporter()
            results["md_exported"] = md_exporter.export_user_profile(now[:10])
        except Exception as e:
            logger.warning(f"用户画像 MD 导出失败（非致命）: {e}")

        wrap_finalize_complete(on_progress, "用户画像分析完成")
        log_step(conversation_id, "", f"user_profile 分析完成 | 技能: {results['skills_count']}")

    except Exception as e:
        logger.error(f"handle_finalize_user_profile 失败: {e}", exc_info=True)
        results["error"] = str(e)[: TRUNC_RULES["error_msg"]]

    finally:
        check_finalize_sub_tasks(engine, conversation_id)

    return results
