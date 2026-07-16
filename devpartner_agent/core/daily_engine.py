"""
日报引擎 (v7.5)
================
日报/日志的统一业务入口。

职责：
  - get_daily_summary: 获取每日工作总结
  - read_daily_log: 读取指定日期的对话日志
  - list_logs: 列出所有有对话记录的日期
  - check_log_gaps: 检查对话时间间隙
  - get_daily_work_data: 获取工作原始数据
  - save_daily_analysis: 保存每日分析结果
  - get_weekly_work_data: 获取周数据
  - get_work_schema_guide: 数据结构说明
  - get_auto_log_stats: 自动日志统计
"""
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class DailyEngine:
    """日报域业务逻辑"""

    def get_daily_summary(self, date: str = "") -> dict:
        from devpartner_agent.skills.daily_summary import generate_daily_summary
        return generate_daily_summary(date)

    def read_daily_log(self, date: str = "") -> dict:
        db = self._get_db()
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        conversations = db.query_local(
            """SELECT * FROM conversations
               WHERE date(timestamp) = ?
               ORDER BY timestamp ASC""",
            (date,)
        )

        return {
            "success": True,
            "date": date,
            "conversations": conversations or [],
            "conversation_count": len(conversations) if conversations else 0,
        }

    def list_logs(self) -> dict:
        db = self._get_db()
        daily = db.query_local(
            """SELECT date(timestamp) as date, COUNT(*) as count
               FROM conversations
               GROUP BY date(timestamp)
               ORDER BY date DESC"""
        )
        return {
            "success": True,
            "daily_summary": daily or [],
            "total_dates": len(daily) if daily else 0,
        }

    def check_log_gaps(self, date: str = "") -> dict:
        db = self._get_db()
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        rows = db.query_local(
            """SELECT timestamp FROM conversations
               WHERE date(timestamp) = ?
               ORDER BY timestamp ASC""",
            (date,)
        )
        if not rows:
            return {"has_gaps": False, "message": f"日期 {date} 暂无对话记录", "total_entries": 0}

        gaps = []
        for i in range(1, len(rows)):
            t1 = datetime.fromisoformat(rows[i-1]["timestamp"])
            t2 = datetime.fromisoformat(rows[i]["timestamp"])
            diff_minutes = (t2 - t1).total_seconds() / 60
            if diff_minutes > 30:
                gaps.append({
                    "from": rows[i-1]["timestamp"][:19],
                    "to": rows[i]["timestamp"][:19],
                    "gap_minutes": int(diff_minutes),
                })

        return {
            "has_gaps": len(gaps) > 0,
            "gap_count": len(gaps),
            "gaps": gaps,
            "total_entries": len(rows),
        }

    def get_daily_work_data(self, date: str = "", fallback_to_log: bool = True) -> dict:
        from devpartner_agent.skills.daily_summary import get_daily_work_data as get_data
        return get_data(date if date else None, fallback_to_log)

    def save_daily_analysis(self, analysis_json: str) -> dict:
        from devpartner_agent.skills.daily_summary import save_daily_analysis as save_analysis
        return save_analysis(analysis_json)

    def get_weekly_work_data(self) -> dict:
        from devpartner_agent.skills.daily_summary import get_weekly_work_data as get_weekly
        return get_weekly()

    def get_work_schema_guide(self) -> dict:
        return {
            "description": "每日工作总结数据结构（用于 save_daily_analysis）",
            "fields": {
                "date": "日期 YYYY-MM-DD（必填）",
                "summary": "一句话总结今日工作（必填）",
                "experience": {"deep_dive": "深度复盘", "lesson": "教训"},
                "skills": {"new_skills": [], "patterns": [], "tools": []},
                "knowledge": {"must_remember": [], "insights": []},
                "danger_signals": {"repeated_mistakes": [], "tech_debt": [], "hot_files": []},
                "tomorrow_plan": "明天最优先做的事",
                "self_analysis": {"strengths": [], "weaknesses": [], "growth_suggestions": []},
            }
        }

    def get_auto_log_stats(self) -> dict:
        from devpartner_agent.core.bootstrap import is_initialized
        if not is_initialized():
            return {"success": False, "error": "核心未初始化"}
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            stats = db.get_tool_stats()
            return {"success": True, "stats": stats}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_db(self):
        from devpartner_agent.core.database import get_db
        return get_db()


_instance: Optional[DailyEngine] = None

def get_daily_engine() -> DailyEngine:
    global _instance
    if _instance is None:
        _instance = DailyEngine()
    return _instance


# ══════════════════════════════════════════════════════════
# Task Handler 注册（v8.1 — 支持异步并行日报生成）
# ══════════════════════════════════════════════════════════

def handle_daily_summary(payload: dict) -> dict:
    """异步生成每日工作总结（含 LLM 分析）"""
    engine = get_daily_engine()
    return engine.get_daily_summary(date=payload.get("date", ""))


def handle_daily_export(payload: dict) -> dict:
    """异步生成日报并导出到 Vault"""
    engine = get_daily_engine()
    date_str = payload.get("date", "")
    summary = engine.get_daily_summary(date=date_str)

    if summary.get("success"):
        from devpartner_agent.services.vault_exporter import get_vault_exporter
        exporter = get_vault_exporter()
        path = exporter.export_daily_report(
            date_str=date_str or datetime.now().strftime("%Y-%m-%d"),
            report_data=summary,
        )
        summary["vault_path"] = path

    return summary


def register_task_handlers():
    """注册日报任务处理器到 task_queue"""
    from devpartner_agent.services.task_queue import get_task_queue
    queue = get_task_queue()
    queue.register_handler("daily_summary", handle_daily_summary)
    queue.register_handler("daily_export", handle_daily_export)
    logger.info("📝 日报任务处理器已注册 (2 个 handler)")


def register_daily_tools(mcp):
    """注册日报域的所有 MCP 工具"""

    @mcp.tool()
    def get_daily_summary(date: str = "") -> str:
        """获取每日工作总结。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.get_daily_summary(date)
        return _inner()

    @mcp.tool()
    def read_daily_log(date: str = "") -> str:
        """读取指定日期的对话日志。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.read_daily_log(date)
        return _inner()

    @mcp.tool()
    def list_logs() -> str:
        """列出所有有对话记录的日期。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.list_logs()
        return _inner()

    @mcp.tool()
    def check_log_gaps(date: str = "") -> str:
        """检查指定日期对话的时间间隙。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.check_log_gaps(date)
        return _inner()

    @mcp.tool()
    def get_daily_work_data(date: str = "", fallback_to_log: bool = True) -> str:
        """获取指定日期的工作原始数据（供 AI 客户端分析用）。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.get_daily_work_data(date, fallback_to_log)
        return _inner()

    @mcp.tool()
    def save_daily_analysis(analysis_json: str) -> str:
        """保存 AI 客户端的每日分析结果。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.save_daily_analysis(analysis_json)
        return _inner()

    @mcp.tool()
    def get_weekly_work_data() -> str:
        """获取最近7天的工作数据概览。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.get_weekly_work_data()
        return _inner()

    @mcp.tool()
    def get_work_schema_guide() -> str:
        """获取 save_daily_analysis 所需的数据结构说明。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.get_work_schema_guide()
        return _inner()

    @mcp.tool()
    def get_auto_log_stats() -> str:
        """获取系统工具调用统计与优化状态。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_daily_engine()
            return engine.get_auto_log_stats()
        return _inner()