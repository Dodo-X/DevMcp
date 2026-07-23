"""
MCP 工具统一装饰器
==================
消除 74 个裸函数中重复的 try/except + json.dumps 样板代码。
"""

import logging

logger = logging.getLogger(__name__)


import functools
import json
from collections.abc import Callable


def mcp_tool_handler(func: Callable) -> Callable:
    """
    MCP 工具统一装饰器：初始化 + 异常捕获 + JSON 序列化

    用法：
        @mcp_tool_handler
        def my_tool(param: str) -> dict:
            engine = get_xxx_engine()
            return engine.do_something(param)

    等价于：
        def my_tool(param: str) -> str:
            _ensure_core()
            try:
                engine = get_xxx_engine()
                result = engine.do_something(param)
                return json.dumps(result, ensure_ascii=False, default=str)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from backend.core.bootstrap import ensure_ready

        ensure_ready()

        try:
            result = func(*args, **kwargs)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, indent=2, default=str)
            return result
        except Exception as e:
            logger.warning("mcp_tool_handler: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    return wrapper
