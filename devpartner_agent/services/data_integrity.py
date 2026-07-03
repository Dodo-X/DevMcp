"""
数据完整性服务 v4.3
==================
负责：
1. 定期校验：每次 record_dialogue 后自动检查数据完整性
2. 空值告警：关键字段非空检查 + 日志记录
3. FK 关联校验：检查外键引用有效性
4. 写入成功率监控：三大链路（record_dialogue / record_conversation / save_self_iterate）写入统计

设计原则：
- 校验失败不阻塞正常业务流
- 告警通过日志输出（stderr）
- 统计写入 success/count 记录到 improvement_log（系统级）
"""

import json
from datetime import datetime
from typing import Optional


class WriteTracker:
    """
    写入成功率追踪器（内存计数，服务重启后重新统计）

    追踪三大关键写入链路：
    - record_dialogue: 对话落盘
    - record_conversation: 对话存档
    - save_self_iterate: 优化结果入库
    """

    def __init__(self):
        self._counts = {
            "record_dialogue": {"success": 0, "failure": 0},
            "record_conversation": {"success": 0, "failure": 0},
            "save_self_iterate": {"success": 0, "failure": 0},
        }

    def record_success(self, operation: str):
        if operation in self._counts:
            self._counts[operation]["success"] += 1

    def record_failure(self, operation: str):
        if operation in self._counts:
            self._counts[operation]["failure"] += 1

    def get_stats(self) -> dict:
        stats = {}
        for op, counts in self._counts.items():
            total = counts["success"] + counts["failure"]
            rate = (counts["success"] / total * 100) if total > 0 else 100
            stats[op] = {
                "success": counts["success"],
                "failure": counts["failure"],
                "total": total,
                "success_rate": round(rate, 1),
            }
        return stats

    def get_summary(self) -> str:
        """生成写入成功率摘要"""
        parts = []
        for op, s in self.get_stats().items():
            parts.append(
                f"{op}: {s['success']}/{s['total']} ({s['success_rate']}%)"
            )
        return " | ".join(parts)


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
