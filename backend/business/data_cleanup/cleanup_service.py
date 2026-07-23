"""
数据生命周期管理服务 (v7.5)
============================
合并来源：
  - services/cleanup_service.py   → CleanupService
  - services/cleanup_scheduler.py → CleanupScheduler
  - services/data_integrity.py    → WriteTracker + check_and_log_integrity

职责：
  - 软删除 / 物理删除 / VACUUM 回收
  - 定时后台清理调度
  - 写入成功率追踪 + 数据完整性检查
"""

import logging
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# WriteTracker — 写入成功率追踪（来自 data_integrity.py）
# ════════════════════════════════════════════════════════════


class WriteTracker:
    """写入成功率追踪器（内存计数）"""

    def __init__(self):
        self._success = Counter()
        self._failure = Counter()

    def record_success(self, operation: str):
        self._success[operation] += 1

    def record_failure(self, operation: str):
        self._failure[operation] += 1

    def get_stats(self) -> dict:
        stats = {}
        all_ops = set(self._success) | set(self._failure)
        for op in sorted(all_ops):
            s = self._success[op]
            f = self._failure[op]
            total = s + f
            rate = round(s / total * 100, 1) if total > 0 else 100
            stats[op] = {"success": s, "failure": f, "total": total, "success_rate": rate}
        return stats

    def get_summary(self) -> str:
        return " | ".join(
            f"{op}: {s['success']}/{s['total']} ({s['success_rate']}%)"
            for op, s in self.get_stats().items()
        )


_write_tracker: WriteTracker | None = None


def get_write_tracker() -> WriteTracker:
    global _write_tracker
    if _write_tracker is None:
        _write_tracker = WriteTracker()
    return _write_tracker


def log_write_result(operation: str, success: bool, detail: str = ""):
    """记录写入操作结果到追踪器并输出日志"""
    tracker = get_write_tracker()
    if success:
        tracker.record_success(operation)
    else:
        tracker.record_failure(operation)
        logger.warning(f"❌ {operation} 写入失败: {detail}")


def check_and_log_integrity(db) -> dict:
    """执行数据完整性检查并记录结果"""
    try:
        integrity = db.validate_conversation_integrity()
        tracker = get_write_tracker()
        write_stats = tracker.get_stats()

        summary = tracker.get_summary()
        if integrity["status"] in ("warning", "error") or any(
            s["success_rate"] < 100 for s in write_stats.values()
        ):
            logger.warning(f"写入成功率: {summary}")
            if integrity["issues"]:
                for issue in integrity["issues"][:5]:
                    logger.warning(f"⚠️ {issue}")

        return {**integrity, "write_stats": write_stats}
    except Exception as e:
        return {"status": "error", "issues": [f"完整性检查异常: {e}"], "write_stats": {}}


# ════════════════════════════════════════════════════════════
# CleanupService — 软删除 / 物理删除 / VACUUM（来自 cleanup_service.py）
# ════════════════════════════════════════════════════════════


class CleanupService:
    """
    数据清理服务 — "用后即焚 + 缓冲兜底" 两阶段清理策略。

    两阶段清理：
      1. 软删除：总结生成后标记 is_deleted=1，逻辑排除
      2. 物理删除：3天后清除软删除记录 + VACUUM 回收空间

    安全校验：清理前校验 conversations.summary_generated = 1
    """

    def __init__(self):
        self._shutdown_flag = False
        self._soft_delete_retention_days = 3
        self._cleanup_interval_seconds = 3600
        self._last_vacuum_time: datetime | None = None
        self._vacuum_interval_hours = 24

        self._thread = threading.Thread(
            target=self._cleanup_loop, name="cleanup_service", daemon=True
        )
        self._thread.start()
        logger.info("🧹 数据清理服务已启动 (v7.5)")

    def _cleanup_loop(self):
        while not self._shutdown_flag:
            try:
                self._physical_delete_expired()
                self._maybe_vacuum()
            except Exception as e:
                logger.error(f"❌ 清理循环异常: {e}", exc_info=True)
            time.sleep(self._cleanup_interval_seconds)

    def soft_delete_conversation_tasks(self, conversation_id: str) -> int:
        """软删除指定会话的所有任务（总结生成后调用）"""
        from backend.core.database.base_conn import get_db

        db = get_db()

        conv = db.query_local(
            "SELECT summary_generated FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if not conv or not conv[0].get("summary_generated"):
            logger.warning(f"⚠️ 软删除被拒绝: {conversation_id} 总结未生成")
            return 0

        affected = db.query_local(
            """
            UPDATE task_queue SET is_deleted = 1, completed_at = ?
            WHERE is_deleted = 0
              AND json_extract(payload, '$.conversation_id') = ?
        """,
            (datetime.now().isoformat(), conversation_id),
        )

        count = affected[0].get("affected_rows", 0) if affected else 0
        if count > 0:
            logger.info(f"🗑️ 软删除: {conversation_id} | {count} 个任务")
        return count

    def _physical_delete_expired(self) -> dict:
        cutoff = (datetime.now() - timedelta(days=self._soft_delete_retention_days)).isoformat()

        from backend.core.database.base_conn import get_db

        db = get_db()

        result = db.query_local(
            """
            DELETE FROM task_queue
            WHERE is_deleted = 1 AND completed_at IS NOT NULL AND completed_at <= ?
        """,
            (cutoff,),
        )

        deleted = result[0].get("affected_rows", 0) if result else 0
        if deleted > 0:
            logger.info(
                f"🧹 物理删除: {deleted} 条过期任务 (>{self._soft_delete_retention_days}天)"
            )

        return {"deleted": deleted, "cutoff": cutoff}

    def _maybe_vacuum(self):
        now = datetime.now()
        if self._last_vacuum_time:
            hours_since = (now - self._last_vacuum_time).total_seconds() / 3600
            if hours_since < self._vacuum_interval_hours:
                return

        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            import os

            db_path = os.path.join("data", "devpartner.db")
            size_before = os.path.getsize(db_path) if os.path.exists(db_path) else 0

            db.query_local("VACUUM")

            size_after = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            freed_mb = (size_before - size_after) / (1024 * 1024)

            self._last_vacuum_time = now
            logger.info(
                f"🗜️ VACUUM 完成: {size_before / 1024 / 1024:.1f}MB → {size_after / 1024 / 1024:.1f}MB (释放 {freed_mb:.1f}MB)"
            )
        except Exception as e:
            logger.warning(f"⚠️ VACUUM 失败: {e}")

    def force_cleanup(self, retention_days: int = None) -> dict:
        days = retention_days or self._soft_delete_retention_days
        self._soft_delete_retention_days = days
        result = self._physical_delete_expired()
        self._soft_delete_retention_days = 3
        return result

    def get_cleanup_stats(self) -> dict:
        from backend.core.database.base_conn import get_db

        db = get_db()

        soft_deleted = db.query_local("SELECT COUNT(*) as cnt FROM task_queue WHERE is_deleted = 1")
        total = db.query_local("SELECT COUNT(*) as cnt FROM task_queue")

        return {
            "soft_deleted_count": soft_deleted[0]["cnt"] if soft_deleted else 0,
            "total_tasks": total[0]["cnt"] if total else 0,
            "retention_days": self._soft_delete_retention_days,
            "last_vacuum": self._last_vacuum_time.isoformat() if self._last_vacuum_time else None,
        }

    def shutdown(self):
        self._shutdown_flag = True
        logger.info("🧹 数据清理服务已关闭")


_cleanup_instance: CleanupService | None = None


def get_cleanup_service() -> CleanupService:
    global _cleanup_instance
    if _cleanup_instance is None:
        _cleanup_instance = CleanupService()
    return _cleanup_instance


# ════════════════════════════════════════════════════════════
# CleanupScheduler — 定时后台清理调度（来自 cleanup_scheduler.py）
# ════════════════════════════════════════════════════════════


class CleanupScheduler:
    """后台自动清理调度器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._interval_seconds = 24 * 3600
        self._last_cleanup: datetime | None = None
        self._cleanup_history: list[dict] = []

    def start(self, interval_hours: int = 24) -> bool:
        with self._lock:
            if self._running:
                return False

            self._interval_seconds = interval_hours * 3600
            self._running = True
            self._thread = threading.Thread(
                target=self._cleanup_loop,
                name="devpartner-cleanup",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self):
        with self._lock:
            self._running = False
            if self._thread:
                self._thread.join(timeout=10)

    def run_now(self) -> dict:
        return self._do_cleanup()

    def get_status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "interval_hours": self._interval_seconds / 3600,
                "last_cleanup": self._last_cleanup.isoformat() if self._last_cleanup else None,
                "history_count": len(self._cleanup_history),
                "recent_history": self._cleanup_history[-3:] if self._cleanup_history else [],
            }

    def _cleanup_loop(self):
        while self._running:
            try:
                self._do_cleanup()
            except Exception:
                pass

            sleep_chunks = self._interval_seconds
            while sleep_chunks > 0 and self._running:
                time.sleep(min(60, sleep_chunks))
                sleep_chunks -= 60

    def _do_cleanup(self) -> dict:
        """执行数据清理（v8.1: 委托给统一的 archive_and_cleanup_data 入口，避免直接删除导致数据丢失）"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "actions": [],
            "errors": [],
            "summary": {},
        }

        try:
            from backend.business.task_handlers.daily_summary import archive_and_cleanup_data

            archive_result = archive_and_cleanup_data()

            result["actions"].append(
                {
                    "action": "archive_and_cleanup",
                    "warm_archived": archive_result.get("warm_archived", 0),
                    "cold_archived": archive_result.get("cold_archived", 0),
                    "deep_cleaned": archive_result.get("deep_cleaned", 0),
                    "pending_failed": archive_result.get("pending_failed", 0),
                    "logs_cleaned": archive_result.get("logs_cleaned", 0),
                }
            )

            if archive_result.get("errors"):
                result["errors"].extend(archive_result["errors"])

            total_actions = (
                archive_result.get("warm_archived", 0)
                + archive_result.get("cold_archived", 0)
                + archive_result.get("deep_cleaned", 0)
                + archive_result.get("pending_failed", 0)
                + archive_result.get("logs_cleaned", 0)
            )

            result["summary"] = {
                "total_cleaned": total_actions,
                "success": len(result["errors"]) == 0,
            }

        except Exception as e:
            result["errors"].append(f"归档清理失败: {e}")
            logger.error(f"CleanupScheduler 归档清理异常: {e}", exc_info=True)

        self._last_cleanup = datetime.now()
        self._cleanup_history.append(result)

        return result


_cleanup_scheduler_instance: CleanupScheduler | None = None


def get_cleanup_scheduler() -> CleanupScheduler:
    global _cleanup_scheduler_instance
    if _cleanup_scheduler_instance is None:
        _cleanup_scheduler_instance = CleanupScheduler()
    return _cleanup_scheduler_instance


# ══════════════════════════════════════════════════════════
# Task Handler 注册（v8.1 — 支持异步并行清理）
# ══════════════════════════════════════════════════════════


def handle_cleanup_force(payload: dict) -> dict:
    """异步强制清理过期数据"""
    service = get_cleanup_service()
    return service.force_cleanup(retention_days=payload.get("retention_days"))


def handle_cleanup_vacuum(payload: dict) -> dict:
    """异步 VACUUM 回收空间"""
    service = get_cleanup_service()
    service._maybe_vacuum()
    return {
        "success": True,
        "last_vacuum": service._last_vacuum_time.isoformat() if service._last_vacuum_time else None,
    }


def handle_cleanup_full(payload: dict) -> dict:
    """异步执行完整清理流程（物理删除 + VACUUM）"""
    scheduler = get_cleanup_scheduler()
    return scheduler.run_now()


def register_task_handlers():
    """注册清理任务处理器到 task_queue"""
    from backend.core.task_queue_kernel.queue_client import get_task_queue

    queue = get_task_queue()
    queue.register_handler("cleanup_force", handle_cleanup_force)
    queue.register_handler("cleanup_vacuum", handle_cleanup_vacuum)
    queue.register_handler("cleanup_full", handle_cleanup_full)
    logger.info("📝 清理任务处理器已注册 (3 个 handler)")
