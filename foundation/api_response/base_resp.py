"""StandardResponse —— 前后端统一返回结构。"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StandardResponse:
    """标准返回体：所有 HTTP 接口统一返回此结构。

    code:     业务错误码（0 = 成功，见 foundation.config.error_code）
    message:  可读提示
    data:     业务数据载荷
    trace_id: 全链路追踪 ID（由 trace_tracker 注入）
    """

    code: int = 0
    message: str = "ok"
    data: Any = None
    trace_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
