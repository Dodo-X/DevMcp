"""
数据完整性服务 v4.3
PONYTATIL: WriteTracker 使用 collections.Counter 替代手写计数逻辑。
"""

from collections import Counter
from typing import Optional


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
        """生成写入成功率摘要"""
        return " | ".join(
            f"{op}: {s['success']}/{s['total']} ({s['success_rate']}%)"
            for op, s in self.get_stats().items()
        )


# 全局追踪器实例
_write_tracker: Optional[WriteTracker] = None


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
        print(f"[data_integrity] ❌ {operation} 写入失败: {detail}")


def check_and_log_integrity(db) -> dict:
    """
    执行数据完整性检查并记录结果。

    Returns:
        {"status": "ok|warning|error", "issues": [...], "write_stats": {...}}
    """
    try:
        integrity = db.validate_conversation_integrity()
        tracker = get_write_tracker()
        write_stats = tracker.get_stats()

        # 输出写入成功率
        summary = tracker.get_summary()
        if integrity["status"] in ("warning", "error") or any(
            s["success_rate"] < 100 for s in write_stats.values()
        ):
            print(f"[data_integrity] 写入成功率: {summary}")
            if integrity["issues"]:
                for issue in integrity["issues"][:5]:
                    print(f"[data_integrity] ⚠️ {issue}")

        return {
            **integrity,
            "write_stats": write_stats,
        }
    except Exception as e:
        return {"status": "error", "issues": [f"完整性检查异常: {e}"], "write_stats": {}}
