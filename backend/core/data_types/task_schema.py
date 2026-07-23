"""异步任务接口结构体（前后端契约）。"""

from dataclasses import dataclass
from typing import Any


@dataclass
class TaskInfo:
    task_id: str
    task_type: str
    status: str = "pending"
    payload: dict[str, Any] | None = None
    error: str | None = None
