"""
埋点工具层 (v9.10.1)
====================
统一封装：写入追踪、耗时统计、日志格式、进度回调包装。
消除散落的 _track_write、_llm_stream_progress 等重复模式。
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime

from backend.business.conversation_mgr.constants import TRUNC_RULES

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 写入追踪
# ══════════════════════════════════════════════════════════


def track_write(operation: str, success: bool) -> None:
    """写入操作追踪（v9.10.1: 从 Engine._track_write 提升为独立工具）"""
    try:
        from backend.business.data_cleanup.cleanup_service import get_write_tracker

        tracker = get_write_tracker()
        if success:
            tracker.record_success(operation)
        else:
            tracker.record_failure(operation)
    except Exception:
        logger.warning("track_write: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        pass


# ══════════════════════════════════════════════════════════
# 耗时计算
# ══════════════════════════════════════════════════════════


def calc_duration_ms(start_dt: datetime) -> int:
    """计算从 start_dt 到现在的耗时（毫秒）"""
    return int((datetime.now() - start_dt).total_seconds() * 1000)


def calc_duration_ms_from_time(start_time: float) -> int:
    """计算从 start_time (time.time()) 到现在的耗时（毫秒）"""
    return int((time.time() - start_time) * 1000)


# ══════════════════════════════════════════════════════════
# 日志工具
# ══════════════════════════════════════════════════════════


def log_step(
    conversation_id: str,
    step_id: str = "",
    msg: str = "",
    level: str = "info",
) -> None:
    """统一日志格式，自动携带 conversation_id/step_id"""
    prefix = f"[{conversation_id}]"
    if step_id:
        prefix += f"[{step_id}]"
    full_msg = f"{prefix} {msg}"

    if level == "error":
        logger.error(full_msg)
    elif level == "warning":
        logger.warning(full_msg)
    elif level == "debug":
        logger.debug(full_msg)
    else:
        logger.info(full_msg)


# ══════════════════════════════════════════════════════════
# 进度回调包装
# ══════════════════════════════════════════════════════════


def wrap_llm_stream_progress(
    on_progress: Callable | None,
    step_name: str = "",
) -> Callable[[str, float], None]:
    """包装 LLM 流式进度回调（替代 _llm_stream_progress 内部函数）"""

    def _callback(partial_text: str, progress_pct: float) -> None:
        if on_progress:
            partial = partial_text[: TRUNC_RULES["partial_text"]] if partial_text else ""
            note = f"步骤分析中: {step_name[:30]}"
            on_progress(progress_pct, partial, note)

    return _callback


def wrap_step_progress(
    on_progress: Callable | None,
    step_name: str = "",
    stage: str = "分析",
) -> None:
    """统一的步骤进度回调"""
    if on_progress:
        on_progress(0.05, "", f"正在{stage}: {step_name[:50]}")


def wrap_step_complete(
    on_progress: Callable | None,
    step_name: str = "",
    stage: str = "分析",
) -> None:
    """统一的步骤完成回调"""
    if on_progress:
        on_progress(0.9, "", f"{stage}完成: {step_name[:50]}")


def wrap_finalize_progress(
    on_progress: Callable | None,
    progress: float,
    partial: str = "",
    note: str = "",
) -> None:
    """统一的 finalize 进度回调"""
    if on_progress:
        on_progress(progress, partial, note)


def wrap_finalize_complete(
    on_progress: Callable | None,
    message: str = "",
) -> None:
    """统一的 finalize 完成回调"""
    if on_progress:
        on_progress(1.0, "", message)
