"""
自动数据清理调度器

在后台定期运行数据生命周期管理：
- 清理过期日志文件
- 清理数据库中的旧对话记录
- 生成清理报告
"""
import threading
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class CleanupScheduler:
    """后台自动清理调度器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval_seconds = 24 * 3600  # 默认24小时
        self._last_cleanup: Optional[datetime] = None
        self._cleanup_history: list[dict] = []

    def start(self, interval_hours: int = 24) -> bool:
        """
        启动后台清理线程

        Args:
            interval_hours: 清理间隔（小时）

        Returns:
            True 如果成功启动
        """
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
        """停止后台清理线程"""
        with self._lock:
            self._running = False
            if self._thread:
                self._thread.join(timeout=10)

    def run_now(self) -> dict:
        """立即执行一次清理"""
        return self._do_cleanup()

    def get_status(self) -> dict:
        """获取清理状态"""
        with self._lock:
            return {
                "running": self._running,
                "interval_hours": self._interval_seconds / 3600,
                "last_cleanup": self._last_cleanup.isoformat() if self._last_cleanup else None,
                "history_count": len(self._cleanup_history),
                "recent_history": self._cleanup_history[-3:] if self._cleanup_history else [],
            }

    def _cleanup_loop(self):
        """后台清理循环"""
        while self._running:
            try:
                self._do_cleanup()
            except Exception:
                pass  # 静默处理清理错误，不影响主流程

            # 等待下一次清理
            sleep_chunks = self._interval_seconds
            while sleep_chunks > 0 and self._running:
                time.sleep(min(60, sleep_chunks))
                sleep_chunks -= 60

    def _do_cleanup(self) -> dict:
        """执行实际清理操作"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "actions": [],
            "errors": [],
            "summary": {},
        }

        try:
            from devpartner_agent.core.config import get_config
            cfg = get_config()
            retention_days = cfg.data_lifecycle.log_retention_days
            backup_before = cfg.data_lifecycle.backup_before_cleanup
        except Exception:
            retention_days = 90
            backup_before = True

        cutoff_date = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")

        # ── 清理数据库旧记录 ──
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            # 获取清理前记录数
            count_result = db.query_local(
                "SELECT COUNT(*) as cnt FROM conversations WHERE date(timestamp) < ?",
                (cutoff_date,)
            )
            before_count = count_result[0]["cnt"] if count_result else 0

            if before_count > 0:
                # 备份（如果配置启用）
                if backup_before:
                    db.query_local(
                        """INSERT INTO conversations_archive
                           SELECT * FROM conversations WHERE date(timestamp) < ?""",
                        (cutoff_date,)
                    )

                # 删除
                db.query_local(
                    "DELETE FROM conversations WHERE date(timestamp) < ?",
                    (cutoff_date,)
                )
                result["actions"].append({
                    "action": "db_cleanup",
                    "table": "conversations",
                    "deleted_count": before_count,
                    "cutoff_date": cutoff_date,
                })

                # VACUUM 回收空间
                try:
                    db.execute_raw("PRAGMA wal_checkpoint(TRUNCATE)")
                    db.execute_raw("VACUUM")
                    result["actions"].append({"action": "vacuum", "status": "completed"})
                except Exception:
                    pass
        except Exception as e:
            result["errors"].append(f"数据库清理失败: {e}")

        # ── 清理旧日志文件（v5.2: Markdown 文件日志已废弃，仅清理数据库旧记录）──
        # 注：日志文件清理功能已在 v5.2 中移除，数据统一由 SQLite 管理

        # ── 记录清理历史 ──
        self._last_cleanup = datetime.now()
        total_cleaned = sum(
            a.get("deleted_count", a.get("archived_count", 0))
            for a in result["actions"]
        )
        result["summary"] = {
            "total_cleaned": total_cleaned,
            "retention_days": retention_days,
            "cutoff_date": cutoff_date,
            "success": len(result["errors"]) == 0,
        }
        self._cleanup_history.append(result)

        return result


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_cleanup_scheduler_instance: Optional[CleanupScheduler] = None

def get_cleanup_scheduler() -> CleanupScheduler:
    """获取清理调度器单例"""
    global _cleanup_scheduler_instance
    if _cleanup_scheduler_instance is None:
        _cleanup_scheduler_instance = CleanupScheduler()
    return _cleanup_scheduler_instance
