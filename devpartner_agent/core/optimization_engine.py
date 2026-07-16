"""
优化引擎 (v8.2)
================
优化闭环的统一业务入口。

职责：
  - get_report: 优化报告
  - apply_optimization: 应用优化
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_OPTIMIZATION_STATE_FILE = Path(__file__).parent.parent.parent / "data" / ".optimization_state.json"


class OptimizationEngine:
    """优化域业务逻辑"""

    def get_report(self) -> dict:
        from devpartner_agent.services.optimization_loop import get_optimization_loop
        loop = get_optimization_loop()
        report = loop.generate_optimization_report()
        return {"success": True, **report}

    def apply_optimization(self, feedback_id: int) -> dict:
        from devpartner_agent.services.optimization_loop import get_optimization_loop
        loop = get_optimization_loop()
        return loop.apply_optimization(feedback_id)

    def _get_tool_call_stats(self) -> dict:
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            return db.get_tool_stats()
        except Exception:
            return {"total_tools": 0, "total_calls": 0}


_instance: Optional[OptimizationEngine] = None

def get_optimization_engine() -> OptimizationEngine:
    global _instance
    if _instance is None:
        _instance = OptimizationEngine()
    return _instance


def register_optimization_tools(mcp):
    """注册优化域的所有 MCP 工具"""

    @mcp.tool()
    def get_optimization_report() -> str:
        """获取 MCP 优化报告：汇总所有待处理的反馈，给出优先级排序的优化建议。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_optimization_engine()
            return engine.get_report()
        return _inner()

    @mcp.tool()
    def apply_optimization(feedback_id: int) -> str:
        """应用指定的优化建议（标记为已处理）。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_optimization_engine()
            return engine.apply_optimization(feedback_id)
        return _inner()