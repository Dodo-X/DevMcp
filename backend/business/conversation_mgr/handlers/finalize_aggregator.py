"""
Finalize 聚合器 + 辅助方法 (v9.10.1)
====================================
从 finalize_handlers.py 拆出，包含：
  - check_finalize_sub_tasks: 聚合检查
  - merge_skills_from_profile: 技能合并
  - cascade_check_daily_summary: 级联触发 daily_summary
"""

import logging
from datetime import datetime

from backend.business.conversation_mgr.constants import (
    FINALIZE_SUB_TASK_TYPES,
)
from backend.business.conversation_mgr.tracker import log_step

logger = logging.getLogger(__name__)


def check_finalize_sub_tasks(engine, conversation_id: str) -> None:
    """v9.8.0: 聚合器 — 检查三个 finalize 子任务是否全部完成。
    v9.10.1: 使用 DAO 层查询任务状态
    """
    try:
        dao = engine.dao

        all_done = True
        has_failure = False
        for task_type in FINALIZE_SUB_TASK_TYPES:
            status = dao.check_finalize_sub_task_status(task_type, conversation_id)
            if status is None:
                all_done = False
                break
            if status not in ("completed", "failed", "cancelled"):
                all_done = False
                break
            if status == "failed":
                has_failure = True

        if not all_done:
            logger.debug(f"[finalize聚合] {conversation_id}: 子任务尚未全部完成，等待中")
            return

        # ── 全部完成，标记 conversation 为 completed ──
        now = datetime.now().isoformat()
        dao.mark_conversation_completed(conversation_id, now)

        log_step(
            conversation_id,
            "",
            f"finalize 子任务全部完成 | status → completed (has_failure={has_failure})",
        )

        # ── 级联检查 daily_summary ──
        cascade_check_daily_summary(engine, conversation_id)

    except Exception as e:
        logger.warning(f"[finalize聚合] {conversation_id} 聚合检查异常（非致命）: {e}")


def merge_skills_from_profile(
    dao, conversation_id: str, skills_observed: list, profile: dict
) -> None:
    """v9.8.0: 将 LLM 识别的技能合并到 user_skills 表
    v9.10.1: 使用 DAO 层，提取 normalize_domain 到顶层
    """
    from backend.core.skill_domain_standard import normalize_domain

    now = datetime.now().isoformat()

    for skill in skills_observed:
        if isinstance(skill, str):
            skill_name = skill
            skill_domain = normalize_domain(skill)
        elif isinstance(skill, dict):
            skill_name = skill.get("skill_name", "")
            skill_domain = normalize_domain(skill.get("skill_domain", "") or skill_name)
        else:
            continue

        if not skill_name:
            continue

        try:
            dao.merge_user_skill(
                skill_name=skill_name,
                skill_domain=skill_domain,
                conversation_id=conversation_id,
                profile=profile,
                now=now,
            )
        except Exception as e:
            logger.debug(f"技能合并失败 [{skill_name}]: {e}")


def cascade_check_daily_summary(engine, conversation_id: str) -> None:
    """v9.6.0: 级联检查 — finalize 完成后检查当日所有 conversation 是否都已完成
    v9.10.1: 使用 DAO 层查询
    """
    try:
        dao = engine.dao

        conv = dao.get_conversation(conversation_id)
        if not conv:
            return
        created_at = conv.get("created_at", "")
        if not created_at:
            return
        target_date = created_at[:10] if len(created_at) >= 10 else created_at

        total, analyzed = dao.count_daily_conversations(target_date)

        if total == 0 or analyzed < total:
            logger.debug(
                f"[级联检查-daily] {target_date}: finalize {analyzed}/{total}，尚未全部完成"
            )
            return

        if dao.check_daily_summary_exists(target_date):
            logger.debug(f"[级联检查-daily] {target_date}: 已有 daily_summary 任务，跳过")
            return

        from backend.core.task_queue_kernel.queue_client import get_task_queue

        tq = get_task_queue()
        task_id = tq.submit(
            task_type="daily_summary",
            payload={
                "target_date": target_date,
                "_trigger_source": "cascade",
            },
            priority="medium",
        )
        logger.info(
            f"[级联检查-daily] {target_date}: 当日所有 conversation finalize 完成"
            f"({analyzed}/{total})，自动提交 daily_summary → {task_id}"
        )

    except Exception as e:
        logger.warning(f"[级联检查-daily] 异常（非致命）: {e}")
