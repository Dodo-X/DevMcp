"""全局上下文存储（基于 contextvars，HTTP/WS/异步任务通用）。"""

import contextvars
import uuid
from typing import Any

# NOTE: 标准库 ContextVar 不支持 default_factory 参数（那是 dataclass.Field 的）。
# 用 default=None 避免可变默认值在多个上下文间共享（B039 规则），
# 所有访问处统一用 `or {}` 保证每个上下文拿到独立 dict。
_ctx: "contextvars.ContextVar[dict[str, Any] | None]" = contextvars.ContextVar(
    "dp_ctx", default=None
)


def set_context(**kwargs: Any) -> None:
    data = dict(_ctx.get() or {})
    data.update({k: v for k, v in kwargs.items() if v is not None})
    _ctx.set(data)


def get_context() -> dict[str, Any]:
    return _ctx.get() or {}


def clear_context() -> None:
    _ctx.set({})


def set_trace_id(trace_id: str | None = None) -> str:
    tid = trace_id or uuid.uuid4().hex[:16]
    set_context(trace_id=tid)
    return tid


def get_trace_id() -> str | None:
    return (_ctx.get() or {}).get("trace_id")
