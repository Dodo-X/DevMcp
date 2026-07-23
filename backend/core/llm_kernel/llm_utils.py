"""
LLM 工具函数 (v9.10.0)
=======================
v9.10.0: 从 llm_engine.py 提取 cancel/intercept 机制，与 LLMEngine 核心类解耦。

包含：
  - 请求拦截器（调试用，不持久化）
  - 全局取消机制（task_queue 超时后中断 worker 线程）
"""

import threading
from collections import deque

# ── 请求拦截器（调试用，不持久化） ──
_intercept_enabled = False
_intercept_lock = threading.Lock()
_intercept_buffer = deque(maxlen=50)  # 最近 50 条请求记录

# ── 全局取消机制 ──
# task_queue 超时后通过此 Event 通知 worker 线程中断 LLM 推理。
# 每个 worker 线程在开始推理前将自己的 cancel_event 绑定到此，
# 推理完成后解绑。infer() 在每次 HTTP 调用前检查。
_cancel_event_per_thread: dict[int, threading.Event] = {}
_cancel_lock = threading.Lock()


# ── Cancel 内部函数 ──


def _set_thread_cancel_event(event: threading.Event):
    tid = threading.get_ident()
    with _cancel_lock:
        _cancel_event_per_thread[tid] = event


def _clear_thread_cancel_event():
    tid = threading.get_ident()
    with _cancel_lock:
        _cancel_event_per_thread.pop(tid, None)


def _get_thread_cancel_event() -> threading.Event | None:
    tid = threading.get_ident()
    with _cancel_lock:
        return _cancel_event_per_thread.get(tid)


# ── Cancel 公开 API ──


def bind_cancel_event(event: threading.Event):
    """v9.5.3: 将取消事件绑定到当前线程。
    task_queue 在超时后 set() 此事件，infer() 会自动检测并中断推理。"""
    _set_thread_cancel_event(event)


def unbind_cancel_event():
    """v9.5.3: 解绑当前线程的取消事件。"""
    _clear_thread_cancel_event()


# ── Intercept 公开 API ──


def is_intercept_enabled() -> bool:
    return _intercept_enabled


def set_intercept_enabled(enable: bool) -> bool:
    global _intercept_enabled
    with _intercept_lock:
        _intercept_enabled = enable
    return _intercept_enabled


def get_intercept_logs() -> list:
    with _intercept_lock:
        return list(_intercept_buffer)


def clear_intercept_logs():
    with _intercept_lock:
        _intercept_buffer.clear()
