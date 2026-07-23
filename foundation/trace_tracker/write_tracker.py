"""DB/队列/文件写入埋点统计（进程内计数）。"""

import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)


def incr(channel: str, n: int = 1) -> None:
    """记录一次写入。channel 如 'db' / 'queue' / 'file'。"""
    with _lock:
        _counters[channel] += n


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)
