"""全局上下文存储（基于 contextvars，HTTP/WS/异步任务通用）。"""

import contextvars
import uuid
from typing import Any

_ctx: "contextvars.ContextVar[dict[str, Any]]" = contextvars.ContextVar("dp_ctx", default={})


def set_context(**kwargs: Any) -> None:
    data = dict(_ctx.get())
    data.update({k: v for k, v in kwargs.items() if v is not None})
    _ctx.set(data)


def get_context() -> dict[str, Any]:
    return dict(_ctx.get())


def clear_context() -> None:
    _ctx.set({})


def set_trace_id(trace_id: str | None = None) -> str:
    tid = trace_id or uuid.uuid4().hex[:16]
    set_context(trace_id=tid)
    return tid


def get_trace_id() -> str | None:
    return _ctx.get().get("trace_id")
