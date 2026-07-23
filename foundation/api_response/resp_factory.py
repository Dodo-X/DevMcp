"""快捷生成成功/失败/分页返回。"""

from typing import Any

from foundation.api_response.base_resp import StandardResponse
from foundation.api_response.page_resp import PageResponse
from foundation.config.error_code import ErrorCode


def ok(data: Any = None, message: str = "ok", trace_id: str | None = None) -> dict:
    return StandardResponse(
        code=ErrorCode.SUCCESS, message=message, data=data, trace_id=trace_id
    ).to_dict()


def fail(
    code: int = ErrorCode.INTERNAL_ERROR,
    message: str = "error",
    data: Any = None,
    trace_id: str | None = None,
) -> dict:
    return StandardResponse(code=int(code), message=message, data=data, trace_id=trace_id).to_dict()


def page(
    items: list[Any], total: int, page_no: int = 1, page_size: int = 20, trace_id: str | None = None
) -> dict:
    payload = PageResponse(items=items, total=total, page=page_no, page_size=page_size).to_dict()
    return ok(data=payload, trace_id=trace_id)
