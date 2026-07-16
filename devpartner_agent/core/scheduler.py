#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用户画像定时汇总调度器 v6.0
============================
功能：
1. 每日自动触发画像摘要生成
2. 每周自动生成成长路线图
3. 支持手动触发全量分析

设计原则：
- 使用 threading + time.sleep 实现轻量级定时（避免额外依赖 schedule 库）
- 守护线程模式，不阻塞主进程
- 异常隔离：单次失败不影响后续执行
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class TaskTimeoutScheduler:
    """
    后台巡检任务超时和孤儿步骤

    职责：
    1. 扫描 pending > 24h 的 conversation_steps → 标记 orphaned
    2. 扫描 running > 10min 的 conversation_steps → 超时回退为 pending（可重试）
    3. 超过 max_retries 的步骤 → 标记 failed

    设计原则：
    - 守护线程，不阻塞主进程
    - 异常隔离：单次扫描失败不影响后续执行
    - 轻量级：使用原生 SQL，不依赖 ORM
    """

    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stats = {
            "orphaned_marked": 0,
            "timeout_reset": 0,
            "failed_exceeded": 0,
            "scan_count": 0,
        }

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("TaskTimeoutScheduler 已在运行中")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="task_timeout_scheduler", daemon=True)
        self._thread.start()
        logger.info(f"✅ TaskTimeoutScheduler 已启动 (间隔 {self.interval}s)")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("⏹️ TaskTimeoutScheduler 已停止")

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._scan_orphaned_steps()
                self._scan_stuck_steps()
                self._scan_exceeded_retries()
                self._stats["scan_count"] += 1
            except Exception as e:
                logger.error(f"❌ TaskTimeoutScheduler 扫描异常: {e}", exc_info=True)
            self._stop_event.wait(self.interval)

    def _scan_orphaned_steps(self):
        """扫描 pending > 24h 的步骤 → 标记 orphaned"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
            cursor = db.query_local("""
                UPDATE conversation_steps
                SET status = 'orphaned',
                    error_message = 'Marked orphaned by scheduler (pending > 24h)'
                WHERE status = 'pending'
                  AND created_at < ?
                  AND started_at IS NULL
            """, (cutoff,))
            affected = cursor if isinstance(cursor, int) else 0
            if affected and affected > 0:
                self._stats["orphaned_marked"] += affected
                logger.info(f"📋 TaskTimeoutScheduler: {affected} 个步骤标记为 orphaned")
        except Exception as e:
            logger.error(f"❌ orphaned 扫描失败: {e}")

    def _scan_stuck_steps(self):
        """扫描 running > 10min 的步骤 → 超时回退为 pending（可重试）"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            cutoff = (datetime.now() - timedelta(minutes=10)).isoformat()
            db.query_local("""
                UPDATE conversation_steps
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    started_at = NULL,
                    error_message = 'Timeout reset by scheduler (running > 10min)'
                WHERE status = 'running'
                  AND started_at < ?
            """, (cutoff,))
        except Exception as e:
            logger.error(f"❌ stuck 扫描失败: {e}")

    def _scan_exceeded_retries(self):
        """扫描 retry_count >= max_retries 的 pending 步骤 → 标记 failed"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local("""
                UPDATE conversation_steps
                SET status = 'failed',
                    error_message = 'Max retries exceeded after timeout'
                WHERE status = 'pending'
                  AND retry_count >= max_retries
                  AND max_retries > 0
            """)
        except Exception as e:
            logger.error(f"❌ exceeded retries 扫描失败: {e}")

    @property
    def status(self) -> dict:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "interval_seconds": self.interval,
            "stats": dict(self._stats),
        }


class ProfileScheduler:
    """
    用户画像定时汇总调度器（精确触发版）

    调度策略：
    - 每天 17:30 触发每日画像摘要（daily_summary）
    - 每周一 09:00 触发每周成长路线图（weekly_roadmap）
    - 使用 threading.Event 精确等待，无需轮询
    - 支持手动调用 trigger_manual_analysis(scope)
    """

    DAILY_HOUR = 17
    DAILY_MINUTE = 30
    WEEKLY_DAY = 0
    WEEKLY_HOUR = 9
    WEEKLY_MINUTE = 0
    ARCHIVE_DAY = 6          # 周日执行归档
    ARCHIVE_HOUR = 3         # 凌晨3点
    ARCHIVE_MINUTE = 0
    MONTHLY_DAY = 1          # 每月1号
    MONTHLY_HOUR = 10        # 上午10点
    MONTHLY_MINUTE = 0
    ANNUAL_MONTH = 12        # 12月
    ANNUAL_DAY = 31          # 12月31日
    ANNUAL_HOUR = 20         # 晚上8点
    ANNUAL_MINUTE = 0

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_daily_run: Optional[str] = None
        self._last_weekly_run: Optional[str] = None
        self._last_archive_run: Optional[str] = None
        self._last_monthly_run: Optional[str] = None
        self._last_annual_run: Optional[str] = None

    def start(self):
        """启动定时调度器（守护线程模式）"""
        if self._running:
            logger.warning("⚠️ 定时调度器已在运行中")
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ProfileScheduler")
        self._thread.start()
        logger.info("✅ 每日总结调度器已启动 (每日 17:30, 精确触发)")

    def stop(self):
        """停止调度器"""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("⏹️ 定时调度器已停止")

    def _seconds_until_next_daily(self) -> float:
        """计算距离下次每日触发（17:30）的秒数"""
        now = datetime.now()
        target = now.replace(hour=self.DAILY_HOUR, minute=self.DAILY_MINUTE, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    def _seconds_until_next_weekly(self) -> float:
        """计算距离下次每周触发（周一 09:00）的秒数"""
        now = datetime.now()
        target = now + timedelta(days=(self.WEEKLY_DAY - now.weekday()) % 7)
        target = target.replace(hour=self.WEEKLY_HOUR, minute=self.WEEKLY_MINUTE, second=0, microsecond=0)
        if target <= datetime.now():
            target += timedelta(days=7)
        return (target - now).total_seconds()

    def _run_loop(self):
        """主循环：精确等待触发时间，无需轮询"""
        logger.debug("🔄 定时调度器主循环启动（精确触发模式）")

        while self._running:
            try:
                now = datetime.now()

                if now.hour == self.DAILY_HOUR and now.minute == self.DAILY_MINUTE:
                    today_str = now.strftime("%Y-%m-%d")
                    if self._last_daily_run != today_str:
                        self._execute_daily_summary(now)
                        self._execute_daily_profile_merge(now)
                        self._execute_daily_system_merge(now)
                        self._last_daily_run = today_str

                if now.weekday() == self.WEEKLY_DAY and now.hour == self.WEEKLY_HOUR and now.minute == self.WEEKLY_MINUTE:
                    week_str = now.strftime("%Y-W%W")
                    if self._last_weekly_run != week_str:
                        self._execute_weekly_roadmap(now)
                        self._last_weekly_run = week_str

                if now.weekday() == self.ARCHIVE_DAY and now.hour == self.ARCHIVE_HOUR and now.minute == self.ARCHIVE_MINUTE:
                    archive_str = now.strftime("%Y-W%W")
                    if self._last_archive_run != archive_str:
                        self._execute_weekly_archive(now)
                        self._last_archive_run = archive_str

                if now.day == self.MONTHLY_DAY and now.hour == self.MONTHLY_HOUR and now.minute == self.MONTHLY_MINUTE:
                    month_str = now.strftime("%Y-%m")
                    if self._last_monthly_run != month_str:
                        self._execute_monthly_report(now)
                        self._last_monthly_run = month_str

                if now.month == self.ANNUAL_MONTH and now.day == self.ANNUAL_DAY and now.hour == self.ANNUAL_HOUR and now.minute == self.ANNUAL_MINUTE:
                    year_str = str(now.year)
                    if self._last_annual_run != year_str:
                        self._execute_annual_report(now)
                        self._last_annual_run = year_str

                next_daily = self._seconds_until_next_daily()
                next_weekly = self._seconds_until_next_weekly()
                wait_seconds = min(next_daily, next_weekly, 3600)

            except Exception as e:
                logger.error(f"❌ 定时调度器循环异常: {e}", exc_info=True)
                wait_seconds = 60

            self._stop_event.wait(timeout=wait_seconds)
    def _execute_daily_summary(self, trigger_time: datetime):
        """
        执行每日工作总结生成

        收集今日所有对话，通过 skills/daily_summary 生成摘要，存入 improvement_log 表
        """
        logger.info(f"📊 开始执行每日工作总结 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")

        try:
            from devpartner_agent.skills.daily_summary import generate_daily_summary

            target_date = trigger_time.strftime("%Y-%m-%d")
            result = generate_daily_summary(date_str=target_date, use_llm=True)

            if not result.get("success"):
                logger.warning(f"⚠️ 每日总结生成失败: {result.get('error', 'unknown')}")
                return

            if result.get("analysis_method") == "none":
                logger.info("ℹ️ 今日无对话数据，跳过每日总结")
                return

            from devpartner_agent.core.database import get_db
            db = get_db()

            summary_data = result.get("summary", {})
            db.insert_improvement_with_dimensions(
                category="daily_profile_summary",
                dimensions={
                    "summary_type": "daily",
                    "date": target_date,
                    "total_conversations": summary_data.get("total_conversations", 0),
                    "analysis_method": result.get("analysis_method", "unknown"),
                    "llm_available": result.get("llm_available", False),
                    "generated_by": "scheduler_daily",
                },
                priority="low",
            )

            conv_count = summary_data.get("total_conversations", 0)
            method = result.get("analysis_method", "unknown")
            logger.info(f"✅ 每日工作总结完成: {conv_count} 条对话, 方式={method}")

            if method == "llm" and result.get("llm_available"):
                try:
                    from devpartner_agent.services.vault_exporter import get_vault_exporter
                    exporter = get_vault_exporter()
                    report_path = exporter.export_daily_report(target_date, result)
                    if report_path:
                        logger.info(f"📅 日报已导出到 Calendar: {report_path}")
                except Exception as export_err:
                    logger.warning(f"⚠️ 日报 MD 导出失败: {export_err}")

        except Exception as e:
            logger.error(f"❌ 每日工作总结执行失败: {e}", exc_info=True)

    def _execute_daily_profile_merge(self, trigger_time: datetime):
        """
        执行每日用户画像合并（v8.0 — 纯 LLM 驱动）

        执行顺序：
        1. 先清算 pending_analyses 中的历史欠账
        2. 再处理当日数据

        LLM 不可用时，当日数据写入 pending_analyses 等待下次清算。
        """
        target_date = trigger_time.strftime("%Y-%m-%d")
        logger.info(f"👤 开始执行每日用户画像合并 [{target_date}]")

        try:
            from devpartner_agent.skills.daily_summary import process_pending_analyses, merge_daily_profile

            pending_result = process_pending_analyses()
            if pending_result.get("processed", 0) > 0:
                logger.info(f"📋 历史欠账清算完成: {pending_result['processed']} 条已处理, {pending_result.get('still_pending', 0)} 条仍待处理")
            elif pending_result.get("still_pending", 0) > 0:
                logger.warning(f"⏸️ 历史欠账清算跳过: LLM 仍不可用, {pending_result['still_pending']} 条待处理")

            result = merge_daily_profile(date_str=target_date)

            if result.get("success"):
                method = result.get("method", "unknown")
                if method == "llm":
                    dims = result.get("dimensions_updated", 0)
                    logger.info(f"✅ 每日用户画像合并完成: {dims} 个维度更新, 方式=LLM")
                elif method == "pending":
                    logger.warning(f"⚠️ 每日用户画像数据已暂存: LLM 不可用，等待下次清算")
                else:
                    logger.info(f"ℹ️ 每日用户画像合并: {result.get('note', '无数据')}")
            else:
                logger.warning(f"⚠️ 每日用户画像合并失败: {result.get('error', 'unknown')}")

        except Exception as e:
            logger.error(f"❌ 每日用户画像合并执行失败: {e}", exc_info=True)

    def _execute_daily_system_merge(self, trigger_time: datetime):
        """
        执行每日系统认知合并（v8.0 — 纯 LLM 驱动）

        执行顺序：
        1. 先清算 pending_analyses 中的历史欠账（由 profile_merge 已触发，此处不重复）
        2. 再处理当日数据

        LLM 不可用时，当日数据写入 pending_analyses 等待下次清算。
        """
        target_date = trigger_time.strftime("%Y-%m-%d")
        logger.info(f"🏗️ 开始执行每日系统认知合并 [{target_date}]")

        try:
            from devpartner_agent.skills.daily_summary import merge_daily_system_context

            result = merge_daily_system_context(date_str=target_date)

            if result.get("success"):
                method = result.get("method", "unknown")
                if method == "llm":
                    systems = result.get("systems_updated", 0)
                    logger.info(f"✅ 每日系统认知合并完成: {systems} 个系统更新, 方式=LLM")
                elif method == "pending":
                    logger.warning(f"⚠️ 每日系统认知数据已暂存: LLM 不可用，等待下次清算")
                else:
                    logger.info(f"ℹ️ 每日系统认知合并: {result.get('note', '无数据')}")
            else:
                logger.warning(f"⚠️ 每日系统认知合并失败: {result.get('error', 'unknown')}")

        except Exception as e:
            logger.error(f"❌ 每日系统认知合并执行失败: {e}", exc_info=True)

    def _execute_weekly_roadmap(self, trigger_time: datetime):
        """
        执行每周成长路线图生成

        汇总一周内所有对话，使用 skills/daily_summary 获取数据
        """
        logger.info(f"🗺️ 开始执行每周成长路线图 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")

        try:
            from devpartner_agent.skills.daily_summary import get_weekly_work_data
            from devpartner_agent.core.database import get_db

            week_data = get_weekly_work_data()

            if not week_data or not week_data.get("daily_summaries"):
                logger.info("ℹ️ 本周无工作数据，跳过周报生成")
                return

            db = get_db()
            db.insert_improvement_with_dimensions(
                category="weekly_growth_roadmap",
                dimensions={
                    "summary_type": "weekly",
                    "period_start": week_data.get("period_start", ""),
                    "period_end": week_data.get("period_end", ""),
                    "total_days": week_data.get("total_days", 0),
                    "total_conversations": week_data.get("total_conversations", 0),
                    "daily_summaries": week_data.get("daily_summaries", []),
                    "generated_by": "scheduler_weekly",
                },
                priority="medium",
            )

            conv_count = week_data.get("total_conversations", 0)
            logger.info(f"✅ 每周成长路线图已存储: {conv_count} 条对话")

        except Exception as e:
            logger.error(f"❌ 每周成长路线图执行失败: {e}", exc_info=True)
    def trigger_manual_analysis(self, scope: str = "full") -> dict:
        """
        手动触发全量分析（供外部调用）

        Args:
            scope: 分析范围 ("full" / "recent" / "daily" / "weekly")

        Returns:
            分析结果字典
        """
        logger.info(f"🎯 手动触发分析 [scope={scope}]")

        try:
            if scope in ("daily", "full", "recent"):
                from devpartner_agent.skills.daily_summary import generate_daily_summary
                result_data = generate_daily_summary(use_llm=True)
            elif scope == "weekly":
                from devpartner_agent.skills.daily_summary import get_weekly_work_data
                result_data = get_weekly_work_data()
            else:
                from devpartner_agent.skills.daily_summary import generate_daily_summary
                result_data = generate_daily_summary(use_llm=True)

            return {
                "status": "success",
                "scope": scope,
                "triggered_at": datetime.now().isoformat(),
                "request_id": f"manual_{datetime.now().strftime('%a%m%d%H%M%S')}",
                "result": result_data,
            }

        except Exception as e:
            logger.error(f"❌ 手动分析触发失败: {e}", exc_info=True)
            return {
                "status": "error",
                "scope": scope,
                "error": str(e),
                "triggered_at": datetime.now().isoformat(),
            }
    @property
    def is_running(self) -> bool:
        """检查调度器是否在运行"""
        return self._running and self._thread and self._thread.is_alive()

    @property
    def status(self) -> dict:
        """获取调度器状态信息"""
        return {
            "running": self.is_running,
            "last_daily_run": self._last_daily_run,
            "last_weekly_run": self._last_weekly_run,
            "last_archive_run": self._last_archive_run,
            "thread_alive": self._thread.is_alive() if self._thread else False,
            "current_time": datetime.now().isoformat(),
        }

    def _execute_weekly_archive(self, trigger_time: datetime):
        """
        执行每周数据归档与清理（v8.0）

        每周日凌晨3点执行，按数据生命周期策略分层归档：
        1. 清理 pending_analyses 超时记录
        2. 温数据归档（30-180天，压缩 steps 详情）
        3. 冷数据归档（>180天，移入 archived_conversations）
        4. 深度清理（>365天，删除 archived_conversations）
        5. 清理过期日志
        """
        logger.info(f"🗄️ 开始执行每周数据归档与清理 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")

        try:
            from devpartner_agent.skills.daily_summary import archive_and_cleanup_data
            result = archive_and_cleanup_data()

            total_actions = (
                result.get("warm_archived", 0) +
                result.get("cold_archived", 0) +
                result.get("deep_cleaned", 0) +
                result.get("pending_failed", 0) +
                result.get("logs_cleaned", 0)
            )

            if total_actions > 0:
                logger.info(
                    f"✅ 每周归档完成: "
                    f"温数据压缩={result.get('warm_archived', 0)}, "
                    f"冷数据归档={result.get('cold_archived', 0)}, "
                    f"深度清理={result.get('deep_cleaned', 0)}, "
                    f"pending标记failed={result.get('pending_failed', 0)}, "
                    f"日志清理={result.get('logs_cleaned', 0)}"
                )
            else:
                logger.info("ℹ️ 每周归档: 无需处理的数据")

            if result.get("errors"):
                for err in result["errors"]:
                    logger.warning(f"⚠️ 归档子任务异常: {err}")

        except Exception as e:
            logger.error(f"❌ 每周数据归档执行失败: {e}", exc_info=True)

    def _execute_monthly_report(self, trigger_time: datetime):
        """
        执行每月报告生成（v8.0）

        每月1号上午10点执行，基于上月周报生成月报。
        数据来源：Reports/Weekly/*.md（不依赖 SQLite）
        输出：Reports/Monthly/{YYYY-MM}.md
        """
        logger.info(f"🗓️ 开始执行月报生成 [{trigger_time.strftime('%Y-%m')}]")

        try:
            from devpartner_agent.skills.daily_summary import generate_monthly_report
            result = generate_monthly_report(trigger_time=trigger_time)

            if result.get("success"):
                method = result.get("method", "unknown")
                if method == "llm":
                    logger.info(f"✅ 月报生成完成: {result.get('file_path', '')}")
                elif method == "pending":
                    logger.warning(f"⚠️ 月报数据已暂存: LLM 不可用，等待下次清算")
                else:
                    logger.info(f"ℹ️ 月报: {result.get('note', '无数据')}")
            else:
                logger.warning(f"⚠️ 月报生成失败: {result.get('error', 'unknown')}")

        except Exception as e:
            logger.error(f"❌ 月报生成执行失败: {e}", exc_info=True)

    def _execute_annual_report(self, trigger_time: datetime):
        """
        执行年度报告生成（v8.0）

        每年12月31日晚8点执行，基于本年月报生成年报。
        数据来源：Reports/Monthly/*.md（不依赖 SQLite）
        输出：Reports/Annual/{YYYY}.md
        """
        logger.info(f"📖 开始执行年报生成 [{trigger_time.year}]")

        try:
            from devpartner_agent.skills.daily_summary import generate_annual_report
            result = generate_annual_report(trigger_time=trigger_time)

            if result.get("success"):
                method = result.get("method", "unknown")
                if method == "llm":
                    logger.info(f"✅ 年报生成完成: {result.get('file_path', '')}")
                elif method == "pending":
                    logger.warning(f"⚠️ 年报数据已暂存: LLM 不可用，等待下次清算")
                else:
                    logger.info(f"ℹ️ 年报: {result.get('note', '无数据')}")
            else:
                logger.warning(f"⚠️ 年报生成失败: {result.get('error', 'unknown')}")

        except Exception as e:
            logger.error(f"❌ 年报生成执行失败: {e}", exc_info=True)


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_scheduler_instance: Optional[ProfileScheduler] = None
_timeout_scheduler_instance: Optional[TaskTimeoutScheduler] = None

def get_scheduler() -> ProfileScheduler:
    """获取全局调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ProfileScheduler()
    return _scheduler_instance

def get_timeout_scheduler() -> TaskTimeoutScheduler:
    """获取全局超时巡检调度器单例"""
    global _timeout_scheduler_instance
    if _timeout_scheduler_instance is None:
        _timeout_scheduler_instance = TaskTimeoutScheduler()
    return _timeout_scheduler_instance


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 测试 ProfileScheduler")
    print("=" * 60)
    
    scheduler = get_scheduler()
    
    print("\n📋 调度器状态:")
    print(f"运行状态: {scheduler.is_running}")
    print(f"状态详情: {scheduler.status}")
    
    print("\n🎯 测试手动触发:")
    result = scheduler.trigger_manual_analysis(scope="recent")
    print(json.dumps(result, indent=2, ensure_ascii=False))