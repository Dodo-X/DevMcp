"""全链路埋点 + 上下文追踪（HTTP/WS/异步任务通用）。

- context_proxy: 全局上下文存储 trace_id / conv_id / system_id
- span_tracker:  代码块耗时埋点装饰器
- write_tracker: DB/队列/文件写入埋点统计
- tracker_api:   埋点统一对外调用门面
"""

from foundation.trace_tracker.context_proxy import (
    clear_context,
    get_context,
    get_trace_id,
    set_context,
    set_trace_id,
)

__all__ = ["set_trace_id", "get_trace_id", "set_context", "get_context", "clear_context"]
