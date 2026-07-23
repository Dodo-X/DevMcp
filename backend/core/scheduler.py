#!/usr/bin/env python
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

import json
import logging
import threading
from datetime import datetime, timedelta

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
        self._thread: threading.Thread | None = None
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
        self._thread = threading.Thread(
            target=self._run, name="task_timeout_scheduler", daemon=True
        )
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
                # v9.6.0: _scan_pending_retry_steps 已由统一恢复流水线接管
                self._stats["scan_count"] += 1
            except Exception as e:
                logger.error(f"❌ TaskTimeoutScheduler 扫描异常: {e}", exc_info=True)
            self._stop_event.wait(self.interval)

    def _scan_orphaned_steps(self):
        """扫描 pending > 24h 的步骤 → 标记 orphaned"""
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
            cursor = db.query_local(
                """
                UPDATE conversation_steps
                SET status = 'orphaned',
                    error_message = 'Marked orphaned by scheduler (pending > 24h)'
                WHERE status = 'pending'
                  AND created_at < ?
                  AND started_at IS NULL
            """,
                (cutoff,),
            )
            affected = cursor if isinstance(cursor, int) else 0
            if affected and affected > 0:
                self._stats["orphaned_marked"] += affected
                logger.info(f"📋 TaskTimeoutScheduler: {affected} 个步骤标记为 orphaned")
        except Exception as e:
            logger.error(f"❌ orphaned 扫描失败: {e}")

    def _scan_stuck_steps(self):
        """扫描 running > 3h 的步骤 → 超时回退为 pending（可重试），对齐 task_queue 超时"""
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            cutoff = (datetime.now() - timedelta(hours=3)).isoformat()
            db.query_local(
                """
                UPDATE conversation_steps
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    started_at = NULL,
                    error_message = 'Timeout reset by scheduler (running > 3h)'
                WHERE status = 'running'
                  AND started_at < ?
            """,
                (cutoff,),
            )
        except Exception as e:
            logger.error(f"❌ stuck 扫描失败: {e}")

    def _scan_exceeded_retries(self):
        """扫描 retry_count >= max_retries 的 pending 步骤 → 标记 failed"""
        try:
            from backend.core.database.base_conn import get_db

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
    - 每30分钟扫描 pending_analyses，LLM 可用时自动清算
    - 使用 threading.Event 精确等待，无需轮询
    - 支持手动调用 trigger_manual_analysis(scope)
    """

    DAILY_HOUR = 17
    DAILY_MINUTE = 30
    WEEKLY_DAY = 0
    WEEKLY_HOUR = 9
    WEEKLY_MINUTE = 0
    ARCHIVE_DAY = 6  # 周日执行归档
    ARCHIVE_HOUR = 3  # 凌晨3点
    ARCHIVE_MINUTE = 0
    MONTHLY_DAY = 1  # 每月1号
    MONTHLY_HOUR = 10  # 上午10点
    MONTHLY_MINUTE = 0
    ANNUAL_MONTH = 12  # 12月
    ANNUAL_DAY = 31  # 12月31日
    ANNUAL_HOUR = 20  # 晚上8点
    ANNUAL_MINUTE = 0
    PENDING_SCAN_INTERVAL_MINUTES = 30  # pending 扫描间隔

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_daily_run: str | None = None
        self._last_weekly_run: str | None = None
        self._last_archive_run: str | None = None
        self._last_monthly_run: str | None = None
        self._last_annual_run: str | None = None
        self._last_pending_scan: datetime | None = None

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

    def _compensate_startup(self):
        """启动时补偿检查：如果错过了本月/本年的报告触发窗口，立即触发"""
        now = datetime.now()
        month_str = now.strftime("%Y-%m")
        year_str = str(now.year)

        # 检查月报：如果已是当月 2 号以后且未记录本月已运行
        if self._last_monthly_run is None:
            monthly_target = now.replace(day=self.MONTHLY_DAY, hour=self.MONTHLY_HOUR,
                                         minute=self.MONTHLY_MINUTE, second=0, microsecond=0)
            if now >= monthly_target:
                logger.info(f"📅 启动补偿: 触发 {month_str} 月报")
                try:
                    self._execute_monthly_report(now)
                except Exception as e:
                    logger.error(f"启动补偿月报失败: {e}")
                self._last_monthly_run = month_str

        # 检查年报：如果已在 12 月 31 日后且未记录本年已运行
        if self._last_annual_run is None:
            annual_target = now.replace(month=self.ANNUAL_MONTH, day=self.ANNUAL_DAY,
                                        hour=self.ANNUAL_HOUR, minute=self.ANNUAL_MINUTE,
                                        second=0, microsecond=0)
            if now >= annual_target:
                logger.info(f"📅 启动补偿: 触发 {year_str} 年报")
                try:
                    self._execute_annual_report(now)
                except Exception as e:
                    logger.error(f"启动补偿年报失败: {e}")
                self._last_annual_run = year_str

    def _run_loop(self):
        """主循环：精确等待触发时间，无需轮询"""
        logger.debug("🔄 定时调度器主循环启动（精确触发模式）")

        # 启动补偿：检查是否错过了本周期的月报/年报
        self._compensate_startup()

        # ponytail: 每 60s 检查一次，简单可靠，上限: 60s 精度足够
        while self._running:
            wait_seconds = 60
            try:
                now = datetime.now()

                # 每日触发：使用日期去重，不依赖精确分钟匹配
                today_str = now.strftime("%Y-%m-%d")
                if self._last_daily_run != today_str:
                    daily_target = now.replace(
                        hour=self.DAILY_HOUR, minute=self.DAILY_MINUTE, second=0, microsecond=0
                    )
                    if now >= daily_target:
                        self._execute_daily_summary(now)
                        # v9.8.2: _execute_daily_profile_merge / _execute_daily_system_merge 已删除
                        # 用户画像/业务知识由 finalize 子任务实时处理，不需要每日二次合并
                        self._last_daily_run = today_str

                # 每周触发：使用周号去重
                if now.weekday() == self.WEEKLY_DAY:
                    week_str = now.strftime("%Y-W%W")
                    if self._last_weekly_run != week_str:
                        weekly_target = now.replace(
                            hour=self.WEEKLY_HOUR,
                            minute=self.WEEKLY_MINUTE,
                            second=0,
                            microsecond=0,
                        )
                        if now >= weekly_target:
                            self._execute_weekly_roadmap(now)
                            self._last_weekly_run = week_str

                # 每周归档：使用周号去重
                if now.weekday() == self.ARCHIVE_DAY:
                    archive_str = now.strftime("%Y-W%W")
                    if self._last_archive_run != archive_str:
                        archive_target = now.replace(
                            hour=self.ARCHIVE_HOUR,
                            minute=self.ARCHIVE_MINUTE,
                            second=0,
                            microsecond=0,
                        )
                        if now >= archive_target:
                            self._execute_weekly_archive(now)
                            self._last_archive_run = archive_str

                # 月报：使用月份去重
                month_str = now.strftime("%Y-%m")
                if self._last_monthly_run != month_str:
                    monthly_target = now.replace(
                        day=self.MONTHLY_DAY,
                        hour=self.MONTHLY_HOUR,
                        minute=self.MONTHLY_MINUTE,
                        second=0,
                        microsecond=0,
                    )
                    if now >= monthly_target:
                        self._execute_monthly_report(now)
                        self._last_monthly_run = month_str

                # 年报：使用年份去重
                year_str = str(now.year)
                if self._last_annual_run != year_str:
                    annual_target = now.replace(
                        month=self.ANNUAL_MONTH,
                        day=self.ANNUAL_DAY,
                        hour=self.ANNUAL_HOUR,
                        minute=self.ANNUAL_MINUTE,
                        second=0,
                        microsecond=0,
                    )
                    if now >= annual_target:
                        self._execute_annual_report(now)
                        self._last_annual_run = year_str

                # v8.1: 定期扫描 pending_analyses，LLM 可用时自动清算
                if (
                    self._last_pending_scan is None
                    or (now - self._last_pending_scan).total_seconds()
                    >= self.PENDING_SCAN_INTERVAL_MINUTES * 60
                ):
                    self._execute_pending_scan(now)
                    self._last_pending_scan = now

            except Exception as e:
                logger.error(f"❌ 定时调度器循环异常: {e}", exc_info=True)

            self._stop_event.wait(timeout=wait_seconds)

    def _execute_daily_summary(self, trigger_time: datetime):
        """
        执行每日工作总结生成（v9.5.1: 异步提交到 task_queue，不再同步等待 LLM）

        通过 task_queue 异步提交 daily_summary 任务，立即返回。
        进度通过 /api/tasks/progress 可查询。

        v9.6.3: 增加日报兜底扫描 — 检查是否有遗漏的日报（当日所有 conversation
        都已完成 finalize 但 task_queue 中没有 daily_summary），自动补交。
        """
        target_date = trigger_time.strftime("%Y-%m-%d")
        logger.info(f"📊 提交每日工作总结任务 [{target_date}]")

        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            queue = get_task_queue()

            # v9.6.3: 先做日报兜底扫描 — 检查是否有历史遗漏的日报
            cascade_count = self._cascade_scan_daily_summary()
            if cascade_count > 0:
                logger.info(f"📋 日报兜底扫描: 补交 {cascade_count} 个遗漏的 daily_summary")

            # 提交当日日报
            task_id = queue.submit_task(
                task_type="daily_summary",
                payload={
                    "target_date": target_date,
                    "trigger_time": trigger_time.isoformat(),
                },
                priority=5,
                estimated_memory_mb=200,
            )
            logger.info(f"📥 日报任务已入队: {task_id}")

        except Exception as e:
            logger.error(f"❌ 每日总结任务提交失败: {e}", exc_info=True)

    def _cascade_scan_daily_summary(self) -> int:
        """
        v9.6.3: 日报兜底扫描 — 从 task_recovery 移至 ProfileScheduler。

        每日 17:30 触发时调用一次，检查是否有"当日所有 conversation 都已完成
        finalize 但 task_queue 中没有对应 daily_summary 任务"的情况，自动补交。

        去重：提交前检查 task_queue 中是否已有同 target_date 的 daily_summary 任务，
        包括 pending/queued/running/completed 状态的（只要不是 cancelled/duplicate_discarded）。

        Returns:
            补交的 daily_summary 任务数量
        """
        cascade_count = 0
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            if not db.is_local_initialized():
                return 0

            # 1. 找到所有有 conversation 的日期，且当日所有 conversation 都已 analyzed
            rows = db.query_local("""
                SELECT
                    DATE(created_at) as target_date,
                    COUNT(*) as total,
                    SUM(CASE WHEN analyzed = 1 THEN 1 ELSE 0 END) as analyzed
                FROM conversations
                WHERE is_deleted = 0
                GROUP BY DATE(created_at)
                HAVING analyzed = total AND total > 0
            """)

            if not rows:
                return 0

            from backend.core.task_queue_kernel.queue_client import get_task_queue

            for row in rows:
                target_date = row["target_date"]
                if not target_date:
                    continue

                # 2. 去重：检查 task_queue 中是否已有该日期的 daily_summary
                #    包括 pending/queued/running/completed 状态的（只要不是已取消/废弃的）
                existing = db.query_local(
                    """
                    SELECT task_id, status FROM task_queue
                    WHERE task_type = 'daily_summary'
                      AND is_deleted = 0
                      AND json_extract(payload, '$.target_date') = ?
                      AND status NOT IN ('cancelled', 'duplicate_discarded')
                """,
                    (target_date,),
                )

                if existing:
                    logger.debug(
                        f"[日报兜底] {target_date}: 已有 daily_summary "
                        f"({existing[0]['task_id']}, status={existing[0]['status']})，跳过"
                    )
                    continue

                # 3. 补交 daily_summary
                tq = get_task_queue()
                task_id = tq.submit(
                    task_type="daily_summary",
                    payload={
                        "target_date": target_date,
                        "_trigger_source": "daily_cascade",  # v9.6.3
                    },
                    priority="medium",
                )
                logger.info(
                    f"[日报兜底] {target_date}: 所有 conversation finalize 完成"
                    f"({row['analyzed']}/{row['total']})，补交 daily_summary → {task_id}"
                )
                cascade_count += 1

        except Exception as e:
            logger.warning(f"[日报兜底] 异常（非致命）: {e}")

        return cascade_count

    # v9.8.2: _execute_daily_profile_merge / _execute_daily_system_merge 已删除
    # 用户画像/业务知识由 finalize 子任务实时处理，不再需要每日二次 LLM 合并

    def _execute_weekly_roadmap(self, trigger_time: datetime):
        """
        执行每周成长路线图生成（v8.5.4: 使用 LLM 驱动的 generate_weekly_report）
        """
        logger.info(f"🗺️ 开始执行每周成长路线图 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")

        try:
            from backend.business.task_handlers.daily_summary import generate_weekly_report

            result = generate_weekly_report(trigger_time)
            if result.get("success") and result.get("method") != "none":
                logger.info(f"✅ 每周成长路线图完成: 方法={result.get('method', 'unknown')}")
            elif result.get("method") == "pending":
                logger.warning("⏸️ 周报数据已暂存 pending_analyses，等待 LLM 可用时清算")
            else:
                logger.info("ℹ️ 本周无数据，跳过周报生成")

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
                from backend.business.task_handlers.daily_summary import generate_daily_summary

                result_data = generate_daily_summary(use_llm=True)
            elif scope == "weekly":
                from backend.business.task_handlers.daily_summary import get_weekly_work_data

                result_data = get_weekly_work_data()
            else:
                from backend.business.task_handlers.daily_summary import generate_daily_summary

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
        执行每周数据归档与清理（v9.2: 不再使用 archived_conversations 表）

        每周日凌晨3点执行，按数据生命周期策略分层归档：
        1. 清理 pending_analyses 超时记录
        2. 温数据归档（30-180天，压缩 steps 详情）
        3. 冷数据归档（>180天，标记 archive_tier='archived'）
        4. 深度清理（>365天，直接删除）
        5. 清理过期日志
        """
        logger.info(f"🗄️ 开始执行每周数据归档与清理 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")

        try:
            from backend.business.task_handlers.daily_summary import archive_and_cleanup_data

            result = archive_and_cleanup_data()

            total_actions = (
                result.get("warm_archived", 0)
                + result.get("cold_archived", 0)
                + result.get("deep_cleaned", 0)
                + result.get("pending_failed", 0)
                + result.get("logs_cleaned", 0)
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
            from backend.business.task_handlers.daily_summary import generate_monthly_report

            result = generate_monthly_report(trigger_time=trigger_time)

            if result.get("success"):
                method = result.get("method", "unknown")
                if method == "llm":
                    logger.info(f"✅ 月报生成完成: {result.get('file_path', '')}")
                elif method == "pending":
                    logger.warning("⚠️ 月报数据已暂存: LLM 不可用，等待下次清算")
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
            from backend.business.task_handlers.daily_summary import generate_annual_report

            result = generate_annual_report(trigger_time=trigger_time)

            if result.get("success"):
                method = result.get("method", "unknown")
                if method == "llm":
                    logger.info(f"✅ 年报生成完成: {result.get('file_path', '')}")
                elif method == "pending":
                    logger.warning("⚠️ 年报数据已暂存: LLM 不可用，等待下次清算")
                else:
                    logger.info(f"ℹ️ 年报: {result.get('note', '无数据')}")
            else:
                logger.warning(f"⚠️ 年报生成失败: {result.get('error', 'unknown')}")

        except Exception as e:
            logger.error(f"❌ 年报生成执行失败: {e}", exc_info=True)

    def _execute_pending_scan(self, trigger_time: datetime):
        """
        定期扫描 pending_analyses（v8.1 新增）

        每 PENDING_SCAN_INTERVAL_MINUTES 分钟执行一次。
        LLM 可用时，自动清算 pending_analyses 中暂存的日报/画像/系统认知数据。
        同时处理 daily_summary 类型的暂存数据（LLM 不可用时暂存的日报）。
        """
        try:
            from backend.business.task_handlers.daily_summary import process_pending_analyses

            result = process_pending_analyses()

            if result.get("processed", 0) > 0:
                logger.info(
                    f"📋 pending 扫描完成: {result['processed']} 条已处理, "
                    f"{result.get('still_pending', 0)} 条仍待处理"
                )
            elif result.get("still_pending", 0) > 0:
                logger.debug(f"⏸️ pending 扫描: LLM 仍不可用, {result['still_pending']} 条待处理")
        except Exception as e:
            logger.error(f"❌ pending 扫描执行失败: {e}", exc_info=True)


# NOTE: 模块级单例，当需要多实例时改为依赖注入
_scheduler_instance: ProfileScheduler | None = None
_timeout_scheduler_instance: TaskTimeoutScheduler | None = None


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
