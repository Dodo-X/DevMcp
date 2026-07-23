"""时间通用工具。"""

from datetime import datetime


def now_iso() -> str:
    return datetime.now().isoformat()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
