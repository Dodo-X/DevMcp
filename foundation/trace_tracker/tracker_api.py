"""埋点统一对外调用门面（业务只需导入此文件）。"""

from foundation.trace_tracker import write_tracker
from foundation.trace_tracker.context_proxy import (
    clear_context,
    get_context,
    get_trace_id,
    set_context,
    set_trace_id,
)
from foundation.trace_tracker.span_tracker import span

__all__ = [
    "set_trace_id",
    "get_trace_id",
    "set_context",
    "get_context",
    "clear_context",
    "span",
    "write_tracker",
]
