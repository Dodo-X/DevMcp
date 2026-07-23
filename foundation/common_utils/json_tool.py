"""JSON 通用工具（安全解析 / 序列化）。"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def safe_loads(text: Any, default: Any = None) -> Any:
    if isinstance(text, (dict, list)):
        return text
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        logger.warning("safe_loads: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return default


def safe_dumps(obj: Any, ensure_ascii: bool = False) -> str:
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii, default=str)
    except Exception:
        logger.warning("safe_dumps: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return "{}"
