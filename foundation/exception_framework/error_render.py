"""异常 -> StandardResponse 渲染。"""

from foundation.api_response.resp_factory import fail
from foundation.config.error_code import ErrorCode
from foundation.exception_framework.base_exc import BizException
from foundation.trace_tracker.context_proxy import get_trace_id


def render_exception(exc: Exception) -> dict:
    """把任意异常渲染成统一失败返回体。"""
    trace_id = get_trace_id()
    if isinstance(exc, BizException):
        return fail(code=exc.code, message=exc.message, data=exc.data, trace_id=trace_id)
    return fail(code=ErrorCode.INTERNAL_ERROR, message=str(exc), trace_id=trace_id)
