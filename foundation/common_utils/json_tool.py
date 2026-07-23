"""JSON 通用工具（安全解析 / 序列化）。"""

import json
from typing import Any


def safe_loads(text: Any, default: Any = None) -> Any:
    if isinstance(text, (dict, list)):
        return text
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def safe_dumps(obj: Any, ensure_ascii: bool = False) -> str:
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii, default=str)
    except Exception:
        return "{}"
