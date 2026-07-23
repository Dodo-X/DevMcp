"""轻量 schema 校验工具（无第三方依赖）。"""

from collections.abc import Iterable
from typing import Any


def require_keys(data: dict[str, Any], keys: Iterable[str]) -> tuple[bool, list]:
    """校验 dict 是否包含全部必需 key。返回 (是否通过, 缺失列表)。"""
    missing = [k for k in keys if k not in data or data.get(k) in (None, "")]
    return (len(missing) == 0, missing)
