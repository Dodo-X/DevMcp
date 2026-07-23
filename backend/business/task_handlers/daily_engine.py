"""
日报任务处理器 (v9.10.0)
=========================
v9.10.0: 删除 DailyEngine 薄包装类，handle_* 直接调用 skills 函数
v9.8.2: 日报生成 — 纯日历日记，不写业务知识/用户画像
v9.5.4: LLM 分析成功自动闭环 — 保存到 DB + 导出 Calendar/{date}.md

职责：
  - handle_daily_summary: 异步 LLM 日报生成 + 自动保存/导出
  - handle_daily_export: 异步日报导出到 Vault
  - register_task_handlers: 注册日报任务到 task_queue
"""

import logging

logger = logging.getLogger(__name__)


def handle_daily_summary(payload: dict) -> dict:
    """
    v9.8.2: 日报生成 — 纯日历日记，不写业务知识/用户画像。

    数据流：LLM 生成日报 → 导出 Calendar/{date}.md（唯一持久化）
    不再写 conversations 表、improvement_log、shared daily_summary 表。
    业务知识/用户画像/知识图谱由 finalize 子任务独立负责。
    """
    from backend.business.task_handlers.daily_summary import generate_daily_summary

    _progress = payload.get("_progress_callback", lambda p, t="", n="": None)
    date_str = payload.get("date", "")
    target_date = payload.get("target_date", date_str)

    # Stage 1: LLM 生成日报
    _progress(0.05, "", "正在加载工作数据...")
    summary = generate_daily_summary(target_date)

    if not summary.get("success"):
        _progress(1.0, "", "日报生成失败")
        return summary

    _progress(0.65, summary.get("summary", {}).get("overview", "")[:200], "LLM 分析完成")

    if summary.get("analysis_method") != "llm":
        logger.info(
            f"日报 [{target_date}] LLM 分析未成功 (method={summary.get('analysis_method')})，跳过导出"
        )
        return summary

    # Step 2: 导出 Calendar/{date}.md（唯一持久化）
    _progress(0.75, "", "正在导出 Markdown 报告...")
    try:
        from backend.business.vault_export.vault_exporter import get_vault_exporter

        exporter = get_vault_exporter()
        report_path = exporter.export_daily_report(target_date, summary)
        if report_path:
            summary["report_path"] = report_path
            logger.info(f"📅 日报已导出: {report_path}")
    except Exception as e:
        logger.warning(f"日报 [{target_date}] MD 导出失败: {e}")

    # Step 3: 结构化指标/心理落库（P1，使分数可聚合/趋势/环比）
    _progress(0.88, "", "正在存储指标数据...")
    if summary.get("analysis_method") == "llm":
        try:
            from backend.business.task_handlers.daily_summary import _store_daily_report_metrics
            from backend.core.database.base_conn import get_db

            _store_daily_report_metrics(get_db(), target_date, summary)
        except Exception as e:
            logger.warning(f"日报 [{target_date}] 指标落库失败: {e}")

    return summary


def handle_daily_export(payload: dict) -> dict:
    """v9.11: 统一到 handle_daily_summary（日报 gen+export 合并为单 handler）"""
    return handle_daily_summary(payload)


def register_task_handlers():
    """注册日报/报告任务处理器到 task_queue"""
    from backend.core.task_queue_kernel.queue_client import get_task_queue

    queue = get_task_queue()
    queue.register_handler("daily_summary", handle_daily_summary)
    queue.register_handler("daily_export", handle_daily_export)

    # 注册大型报告 handler（串行化执行，防止 Ollama 连接争抢）
    def _weekly_wrapper(payload: dict) -> dict:
        from datetime import datetime as _dt

        from backend.business.task_handlers.reports import generate_weekly_report

        ts = payload.get("trigger_time", "")
        trigger_time = _dt.fromisoformat(ts) if ts else None
        return generate_weekly_report(trigger_time)

    def _monthly_wrapper(payload: dict) -> dict:
        from datetime import datetime as _dt

        from backend.business.task_handlers.reports import generate_monthly_report

        ts = payload.get("trigger_time", "")
        trigger_time = _dt.fromisoformat(ts) if ts else None
        return generate_monthly_report(trigger_time=trigger_time)

    def _annual_wrapper(payload: dict) -> dict:
        from datetime import datetime as _dt

        from backend.business.task_handlers.reports import generate_annual_report

        ts = payload.get("trigger_time", "")
        trigger_time = _dt.fromisoformat(ts) if ts else None
        return generate_annual_report(trigger_time=trigger_time)

    queue.register_handler("weekly_report", _weekly_wrapper)
    queue.register_handler("monthly_report", _monthly_wrapper)
    queue.register_handler("annual_report", _annual_wrapper)

    logger.info("📝 日报+报告任务处理器已注册 (5 个 handler)")
