"""
多级报告生成 v9.10.0 — 周报/月报/年报
=======================================
从 daily_summary.py 拆分出来，专注长跨周期报告（周/月/年）。
日报数据获取 + 生成逻辑仍保留在 daily_summary.py。

数据流向：
  Calendar/*.md 日报 → 周报 → 月报 → 年报
  用户画像快照 + 项目画像快照作为上下文注入
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _run_growth_analysis(
    db,
    period_start: str,
    period_end: str,
    weekly_summaries_text: str,
    user_snapshot: str,
    project_snapshot: str,
):
    """
    月报生成后触发系统+用户双维度成长分析，产出 growth_analysis 表数据。

    v8.5.0: 双维度分析 — system_analyses（系统优化）+ user_analyses（用户成长）
    结果写入 growth_analysis 表，状态为 pending，等待 Dashboard 人工审核。
    """
    month_str = period_start[:7]
    try:
        from backend.templates.llm_prompt import TASK_GROWTH_ANALYSIS, run_analysis

        ga_result = run_analysis(
            TASK_GROWTH_ANALYSIS,
            period_start=period_start,
            period_end=period_end,
            weekly_summaries=weekly_summaries_text,
            user_profile_snapshot=user_snapshot,
            project_profile_snapshot=project_snapshot,
        )

        if not ga_result or not isinstance(ga_result, dict):
            logger.warning("成长分析 LLM 返回无效结果，跳过")
            return

        # v8.5.0: 双维度 — system_analyses + user_analyses
        system_items = ga_result.get("system_analyses", [])
        user_items = ga_result.get("user_analyses", [])
        all_items = system_items + user_items

        if not all_items:
            logger.info("本月无成长分析建议")
            return

        count = 0
        for item in all_items:
            try:
                db.insert_growth_analysis(
                    {
                        "analysis_type": item.get("analysis_type", ""),
                        "title": item.get("title", ""),
                        "description": item.get("description", ""),
                        "suggestion": item.get("suggestion", ""),
                        "related_data": {
                            **(item.get("related_data", {}) or {}),
                            "related_skills": item.get("related_skills", []),
                            "trend_keywords": item.get("trend_keywords", []),
                            "expected_effect": item.get("expected_effect", ""),
                        },
                        "priority": item.get("priority", "medium"),
                        "source": "monthly_report",
                        "source_period": month_str,
                    }
                )
                count += 1
            except Exception as e:
                logger.error(f"写入 growth_analysis 失败: {e}")

        # v8.5.0: 保存汇总信息到 improvement_log
        summary = ga_result.get("summary", {})
        if summary:
            try:
                db.query_local(
                    """
                    INSERT INTO improvement_log (
                        timestamp, category, suggestion, priority, status
                    ) VALUES (?, 'growth_summary', ?, 'medium', 'pending')
                """,
                    (datetime.now().isoformat(), json.dumps(summary, ensure_ascii=False)[:500]),
                )
            except Exception:
                logger.warning(
                    "_run_growth_analysis: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

        if count > 0:
            logger.info(
                f"成长分析完成: {count} 条建议已写入 growth_analysis 表（{month_str}）"
                f" | 系统={len(system_items)} 用户={len(user_items)}"
            )

        _cleanup_old_growth_analysis(db, month_str)

    except Exception as e:
        logger.error(f"成长分析执行失败: {e}", exc_info=True)


def _cleanup_old_growth_analysis(db, current_period: str):
    """
    清理上个月已处理的 growth_analysis 数据。

    规则：每月清理 status 为 approved/rejected 且 source_period < 当前月的数据。
    """
    try:
        year, month = int(current_period[:4]), int(current_period[5:7])
        before = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"

        deleted = db.cleanup_growth_analysis(before)
        if deleted > 0:
            logger.info(f"清理已处理 growth_analysis: {deleted} 条（{before} 及之前）")
    except Exception as e:
        logger.error(f"清理 growth_analysis 失败: {e}")


def generate_weekly_report(
    trigger_time: datetime = None, target_date: str = None, force_overwrite: bool = False,
    on_progress=None,
) -> dict:
    """
    生成周报（v8.0 — LLM 驱动 + MD 自包含）
    v8.5.7: 新增 target_date + force_overwrite，支持手动覆盖生成

    数据来源：上周的 Calendar/*.md 日报文件 + 用户/项目画像快照
    输出：Reports/Weekly/{YYYY-WXX}.md

    Args:
        trigger_time: 触发时间，默认当前时间
        target_date: 目标日期（YYYY-MM-DD），定位到该日期所在周，默认上周
        force_overwrite: 是否覆盖已存在的报告

    Returns:
        {"success": bool, "method": "llm"/"pending", "file_path": str}
    """
    if trigger_time is None:
        trigger_time = datetime.now()

    result = {"success": False, "method": "none", "file_path": None}

    try:
        from backend.business.task_handlers.daily_summary import (
            _check_llm_available,
            _get_project_profile_snapshot,
            _get_user_profile_snapshot,
            _read_md_reports,
            _write_pending_analysis,
        )
        from backend.business.vault_export.vault_exporter import get_vault_exporter
        from backend.core.database.base_conn import get_db

        db = get_db()
        exporter = get_vault_exporter()

        if target_date:
            td = datetime.strptime(target_date, "%Y-%m-%d").date()
            week_monday = td - timedelta(days=td.weekday())
            week_sunday = week_monday + timedelta(days=6)
            period_start = week_monday.strftime("%Y-%m-%d")
            period_end = week_sunday.strftime("%Y-%m-%d")
            week_num = week_monday.strftime("%Y-W%W")
        else:
            today = trigger_time.date()
            this_monday = today - timedelta(days=today.weekday())
            last_monday = this_monday - timedelta(days=7)
            last_sunday = this_monday - timedelta(days=1)
            period_start = last_monday.strftime("%Y-%m-%d")
            period_end = last_sunday.strftime("%Y-%m-%d")
            week_num = last_monday.strftime("%Y-W%W")

        target_file = exporter._reports_dir / "Weekly" / f"{week_num}.md"
        if target_file.exists() and not force_overwrite:
            result["success"] = True
            result["method"] = "skipped"
            result["file_path"] = str(target_file)
            result["note"] = f"报告已存在: {week_num}.md（勾选覆盖可重新生成）"
            result["period_start"] = period_start
            result["period_end"] = period_end
            return result

        daily_summaries = _read_md_reports(
            exporter._calendar_dir,
            limit=7,
            date_from=period_start,
            date_to=period_end,
        )
        daily_summaries_text = ""
        for ds in daily_summaries:
            daily_summaries_text += f"### {ds['file']}\n{ds['content']}\n\n"

        if not daily_summaries_text.strip():
            if on_progress: on_progress(1.0, "", "本周无日报数据")
            result["success"] = True
            result["method"] = "none"
            result["note"] = "本周无日报数据"
            return result

        user_snapshot = _get_user_profile_snapshot(db)
        project_snapshot = _get_project_profile_snapshot(db)

        llm_ok, llm_reason = _check_llm_available("enhance_weekly_report")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="weekly_report",
                source_date=period_start,
                raw_data={
                    "daily_summaries": daily_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=[
                    "key_achievements",
                    "skill_progress",
                    "risk_assessment",
                    "next_week_plan",
                ],
                error_message=llm_reason,
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        from backend.templates.llm_prompt import TASK_WEEKLY_REPORT, run_analysis

        if on_progress:
            # 桥接 run_analysis 的 on_progress → 任务进度回调
            def _w_progress(partial_text, pct):
                stage_progress = 0.25 + pct * 0.45
                on_progress(stage_progress, partial_text[:200], "LLM 分析中...")
            _w_progress("", 0.0)
        else:
            _w_progress = None

        llm_result = run_analysis(
            TASK_WEEKLY_REPORT,
            period_start=period_start,
            period_end=period_end,
            daily_summaries=daily_summaries_text[:8000],
            user_profile_snapshot=user_snapshot[:2000],
            project_profile_snapshot=project_snapshot[:2000],
            on_progress=_w_progress,
        )

        if llm_result and isinstance(llm_result, dict) and "summary" in llm_result:
            if on_progress: on_progress(0.80, "", "正在导出周报文件...")
            file_path = exporter.export_weekly_report(period_start, period_end, llm_result)
            result["success"] = True
            result["method"] = "llm"
            result["file_path"] = file_path
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="weekly_report",
                source_date=period_start,
                raw_data={
                    "daily_summaries": daily_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=[
                    "key_achievements",
                    "skill_progress",
                    "risk_assessment",
                    "next_week_plan",
                ],
                error_message="LLM 返回结果无效",
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = "LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"周报生成失败: {e}", exc_info=True)

    return result


def generate_monthly_report(
    trigger_time: datetime = None, target_date: str = None, force_overwrite: bool = False,
    on_progress=None,
) -> dict:
    """
    生成月报（v8.0 — LLM 驱动 + MD 自包含）
    v8.5.7: 新增 target_date + force_overwrite，支持手动覆盖生成

    数据来源：上月的 Reports/Weekly/*.md 周报文件 + 用户/项目画像快照
    输出：Reports/Monthly/{YYYY-MM}.md

    Args:
        trigger_time: 触发时间，默认当前时间
        target_date: 目标日期（YYYY-MM-DD），定位到该日期所在月，默认上月
        force_overwrite: 是否覆盖已存在的报告

    Returns:
        {"success": bool, "method": "llm"/"pending", "file_path": str}
    """
    if trigger_time is None:
        trigger_time = datetime.now()

    result = {"success": False, "method": "none", "file_path": None}

    try:
        from backend.business.task_handlers.daily_summary import (
            _check_llm_available,
            _get_project_profile_snapshot,
            _get_user_profile_snapshot,
            _read_md_reports,
            _write_pending_analysis,
        )
        from backend.business.vault_export.vault_exporter import get_vault_exporter
        from backend.core.database.base_conn import get_db

        db = get_db()
        exporter = get_vault_exporter()

        if target_date:
            td = datetime.strptime(target_date, "%Y-%m-%d").date()
            first_of_month = td.replace(day=1)
            if td.month == 12:
                last_of_month = td.replace(day=31)
            else:
                next_month = td.replace(month=td.month + 1, day=1)
                last_of_month = next_month - timedelta(days=1)
            period_start = first_of_month.strftime("%Y-%m-%d")
            period_end = last_of_month.strftime("%Y-%m-%d")
            month_str = first_of_month.strftime("%Y-%m")
        else:
            today = trigger_time.date()
            first_of_this_month = today.replace(day=1)
            last_of_prev_month = first_of_this_month - timedelta(days=1)
            first_of_prev_month = last_of_prev_month.replace(day=1)
            period_start = first_of_prev_month.strftime("%Y-%m-%d")
            period_end = last_of_prev_month.strftime("%Y-%m-%d")
            month_str = first_of_prev_month.strftime("%Y-%m")

        target_file = exporter._reports_dir / "Monthly" / f"{month_str}.md"
        if target_file.exists() and not force_overwrite:
            result["success"] = True
            result["method"] = "skipped"
            result["file_path"] = str(target_file)
            result["note"] = f"报告已存在: {month_str}.md（勾选覆盖可重新生成）"
            result["period_start"] = period_start
            result["period_end"] = period_end
            return result

        weekly_summaries = _read_md_reports(
            exporter._reports_dir / "Weekly",
            limit=5,
            date_from=period_start,
            date_to=period_end,
        )
        weekly_summaries_text = ""
        for ws in weekly_summaries:
            weekly_summaries_text += f"### {ws['file']}\n{ws['content']}\n\n"

        if not weekly_summaries_text.strip():
            result["success"] = True
            result["method"] = "none"
            result["note"] = "本月无周报数据"
            return result

        user_snapshot = _get_user_profile_snapshot(db)
        project_snapshot = _get_project_profile_snapshot(db)

        llm_ok, llm_reason = _check_llm_available("enhance_monthly_report")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="monthly_report",
                source_date=period_start,
                raw_data={
                    "weekly_summaries": weekly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=[
                    "major_achievements",
                    "skill_evolution",
                    "risk_and_debt",
                    "next_month_plan",
                ],
                error_message=llm_reason,
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        from backend.templates.llm_prompt import TASK_MONTHLY_REPORT, run_analysis

        if on_progress:
            def _m_progress(partial_text, pct):
                stage_progress = 0.25 + pct * 0.45
                on_progress(stage_progress, partial_text[:200], "LLM 分析中...")
            _m_progress("", 0.0)
        else:
            _m_progress = None

        llm_result = run_analysis(
            TASK_MONTHLY_REPORT,
            period_start=period_start,
            period_end=period_end,
            weekly_summaries=weekly_summaries_text[:10000],
            user_profile_snapshot=user_snapshot[:2000],
            project_profile_snapshot=project_snapshot[:2000],
            on_progress=_m_progress,
        )

        if llm_result and isinstance(llm_result, dict) and "summary" in llm_result:
            if on_progress: on_progress(0.80, "", "正在导出月报文件...")
            file_path = exporter.export_monthly_report(period_start, period_end, llm_result)
            result["success"] = True
            result["method"] = "llm"
            result["file_path"] = file_path

            _run_growth_analysis(
                db=db,
                period_start=period_start,
                period_end=period_end,
                weekly_summaries_text=weekly_summaries_text[:10000],
                user_snapshot=user_snapshot[:2000],
                project_snapshot=project_snapshot[:2000],
            )
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="monthly_report",
                source_date=period_start,
                raw_data={
                    "weekly_summaries": weekly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=[
                    "major_achievements",
                    "skill_evolution",
                    "risk_and_debt",
                    "next_month_plan",
                ],
                error_message="LLM 返回结果无效",
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = "LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"月报生成失败: {e}", exc_info=True)

    return result


def generate_annual_report(
    trigger_time: datetime = None, target_date: str = None, force_overwrite: bool = False
) -> dict:
    """
    生成年报（v8.0 — LLM 驱动 + MD 自包含）
    v8.5.7: 新增 target_date + force_overwrite，支持手动覆盖生成

    数据来源：本年的 Reports/Monthly/*.md 月报文件 + 用户/项目画像快照
    输出：Reports/Annual/{YYYY}.md

    Args:
        trigger_time: 触发时间，默认当前时间
        target_date: 目标日期（YYYY-MM-DD），定位到该日期所在年，默认去年
        force_overwrite: 是否覆盖已存在的报告

    Returns:
        {"success": bool, "method": "llm"/"pending", "file_path": str}
    """
    if trigger_time is None:
        trigger_time = datetime.now()

    result = {"success": False, "method": "none", "file_path": None}

    try:
        from backend.business.task_handlers.daily_summary import (
            _check_llm_available,
            _get_project_profile_snapshot,
            _get_user_profile_snapshot,
            _read_md_reports,
            _write_pending_analysis,
        )
        from backend.business.vault_export.vault_exporter import get_vault_exporter
        from backend.core.database.base_conn import get_db

        db = get_db()
        exporter = get_vault_exporter()

        if target_date:
            year_str = str(datetime.strptime(target_date, "%Y-%m-%d").year)
        else:
            year_str = str(trigger_time.year - 1)

        period_start = f"{year_str}-01-01"
        period_end = f"{year_str}-12-31"

        target_file = exporter._reports_dir / "Annual" / f"{year_str}.md"
        if target_file.exists() and not force_overwrite:
            result["success"] = True
            result["method"] = "skipped"
            result["file_path"] = str(target_file)
            result["note"] = f"报告已存在: {year_str}.md（勾选覆盖可重新生成）"
            result["period_start"] = period_start
            result["period_end"] = period_end
            return result

        monthly_summaries = _read_md_reports(
            exporter._reports_dir / "Monthly",
            limit=12,
            date_from=period_start,
            date_to=period_end,
        )
        monthly_summaries_text = ""
        for ms in monthly_summaries:
            monthly_summaries_text += f"### {ms['file']}\n{ms['content']}\n\n"

        if not monthly_summaries_text.strip():
            result["success"] = True
            result["method"] = "none"
            result["note"] = "本年无月报数据"
            return result

        user_snapshot = _get_user_profile_snapshot(db)
        project_snapshot = _get_project_profile_snapshot(db)

        llm_ok, llm_reason = _check_llm_available("enhance_annual_report")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="annual_report",
                source_date=period_start,
                raw_data={
                    "monthly_summaries": monthly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "year": year_str,
                },
                missing_dimensions=[
                    "year_in_review",
                    "skill_journey",
                    "growth_analysis",
                    "next_year_vision",
                ],
                error_message=llm_reason,
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        from backend.templates.llm_prompt import TASK_ANNUAL_REPORT, run_analysis

        llm_result = run_analysis(
            TASK_ANNUAL_REPORT,
            period_start=period_start,
            period_end=period_end,
            monthly_summaries=monthly_summaries_text[:14000],
            user_profile_snapshot=user_snapshot[:2000],
            project_profile_snapshot=project_snapshot[:2000],
        )

        if llm_result and isinstance(llm_result, dict) and "summary" in llm_result:
            file_path = exporter.export_annual_report(year_str, llm_result)
            result["success"] = True
            result["method"] = "llm"
            result["file_path"] = file_path
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="annual_report",
                source_date=period_start,
                raw_data={
                    "monthly_summaries": monthly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "year": year_str,
                },
                missing_dimensions=[
                    "year_in_review",
                    "skill_journey",
                    "growth_analysis",
                    "next_year_vision",
                ],
                error_message="LLM 返回结果无效",
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = "LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"年报生成失败: {e}", exc_info=True)

    return result
