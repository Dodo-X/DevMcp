"""
系统引擎 (v8.2)
================
系统运维 + 诊断 + 清理 + LLM状态 的统一业务入口。

职责：
  - get_system_health: 系统健康状态
  - get_v5_status: v5 升级状态
  - system_diagnose: 系统诊断
  - check_data_integrity: 数据完整性检查
  - cleanup_data: 数据清理
  - llm_status: LLM 状态
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SystemEngine:
    """系统域业务逻辑"""

    def get_system_health(self) -> dict:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        from devpartner_agent.services.task_queue import get_task_queue

        engine = get_conversation_engine()
        queue = get_task_queue()

        conv_health = engine.get_system_health()
        queue_stats = queue.get_queue_stats()

        db = self._get_db()
        kp_total = db.query_local("SELECT COUNT(*) as cnt FROM knowledge_points")[0]["cnt"]
        kp_by_domain = db.query_local(
            "SELECT domain, COUNT(*) as cnt FROM knowledge_points GROUP BY domain ORDER BY cnt DESC LIMIT 10"
        )

        return {
            "conversation_engine": conv_health,
            "task_queue": queue_stats,
            "knowledge_base": {
                "total_points": kp_total,
                "by_domain": {r["domain"]: r["cnt"] for r in kp_by_domain},
            },
            "timestamp": datetime.now().isoformat(),
        }

    def get_v5_status(self) -> dict:
        db = self._get_db()
        cursor = db._local_conn.cursor()

        new_tables = {}
        for table in ["conversation_steps", "knowledge_points", "task_queue"]:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            exists = cursor.fetchone() is not None
            count = 0
            if exists:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
            new_tables[table] = {"exists": exists, "count": count}

        cursor.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]
        v5_columns = {col: (col in columns) for col in
                      ["conversation_id", "status", "priority", "total_steps", "completed_steps"]}

        cursor.execute("SELECT COUNT(*) FROM conversations")
        total_conv = cursor.fetchone()[0]

        return {
            "version": "5.0",
            "new_tables": new_tables,
            "conversations_fields": v5_columns,
            "total_conversations": total_conv,
            "all_new_tables_exist": all(t["exists"] for t in new_tables.values()),
            "all_v5_columns_exist": all(v5_columns.values()),
        }

    def system_diagnose(self) -> dict:
        from devpartner_agent.core.database import get_db

        issues = []
        checks = {}

        try:
            db = get_db()
            checks["database"] = "healthy"
        except Exception as e:
            checks["database"] = f"unhealthy: {e}"
            issues.append(f"数据库异常: {e}")

        try:
            from devpartner_agent.core.config import get_config
            cfg = get_config()
            log_dir = Path(cfg.data.logs_dir)
            if log_dir.exists():
                log_count = len(list(log_dir.glob("*.md")))
                checks["logs"] = f"healthy ({log_count} 个日志文件)"
            else:
                checks["logs"] = "missing"
                issues.append("日志目录不存在")
        except Exception as e:
            checks["logs"] = f"error: {e}"

        try:
            from devpartner_agent.core.rule_engine import get_engine
            engine = get_engine()
            rules = engine.get_all()
            checks["rules"] = f"healthy ({len(rules)} 条规则)"
        except Exception as e:
            checks["rules"] = f"error: {e}"

        return {
            "success": True,
            "health": "healthy" if not issues else "degraded",
            "checks": checks,
            "issues": issues,
            "recommendations": ["重启服务"] if issues else [],
        }

    def check_data_integrity(self, include_write_stats: bool = True) -> dict:
        from devpartner_agent.core.database import get_db
        from devpartner_agent.services.cleanup_service import check_and_log_integrity

        db = get_db()
        result = check_and_log_integrity(db)
        return {"success": True, **result}

    def cleanup_data(self, scope: str = "all", dry_run: bool = False) -> dict:
        from devpartner_agent.services.cleanup_service import get_cleanup_service, get_cleanup_scheduler

        result = {"scope": scope, "dry_run": dry_run, "actions": []}

        if scope in ("all", "conversations"):
            scheduler = get_cleanup_scheduler()
            conv_result = scheduler.cleanup(scope, dry_run)
            result["conversations"] = conv_result

        if scope in ("all", "tasks", "tasks_force", "stats"):
            cs = get_cleanup_service()

            if scope == "stats":
                result["tasks"] = cs.get_cleanup_stats()
            elif scope == "tasks_force":
                if dry_run:
                    stats = cs.get_cleanup_stats()
                    result["tasks"] = {"dry_run": True, "would_delete": stats["soft_deleted_count"]}
                else:
                    force_result = cs.force_cleanup(retention_days=0)
                    result["tasks"] = force_result
            else:
                if dry_run:
                    stats = cs.get_cleanup_stats()
                    result["tasks"] = {"dry_run": True, "soft_deleted_count": stats["soft_deleted_count"]}
                else:
                    cs_result = cs._physical_delete_expired()
                    result["tasks"] = cs_result

        return result

    def llm_status(self, action: str = "status") -> dict:
        from devpartner_agent.core.llm_engine import get_llm_engine
        llm = get_llm_engine()

        if action == "preload":
            loaded = llm.preload()
            status = llm.get_status()
            status["preload_result"] = loaded
            return {"success": loaded, **status}

        return {"success": True, **llm.get_status()}

    def _get_db(self):
        from devpartner_agent.core.database import get_db
        return get_db()


_instance: Optional[SystemEngine] = None

def get_system_engine() -> SystemEngine:
    global _instance
    if _instance is None:
        _instance = SystemEngine()
    return _instance


def register_system_tools(mcp):
    """注册系统域的所有 MCP 工具"""

    @mcp.tool()
    def get_system_health() -> str:
        """获取 DevPartner 系统整体健康状态。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_system_engine()
            return engine.get_system_health()
        return _inner()

    @mcp.tool()
    def get_v5_status() -> str:
        """检查 DevPartner v5.0 升级状态和核心功能可用性。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_system_engine()
            return engine.get_v5_status()
        return _inner()

    @mcp.tool()
    def system_diagnose() -> str:
        """系统诊断。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_system_engine()
            return engine.system_diagnose()
        return _inner()

    @mcp.tool()
    def check_data_integrity(include_write_stats: bool = True) -> str:
        """检查数据库数据完整性：关键字段非空 + FK 关联有效性 + 写入成功率。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_system_engine()
            return engine.check_data_integrity(include_write_stats)
        return _inner()

    @mcp.tool()
    def cleanup_data(scope: str = "all", dry_run: bool = False) -> str:
        """数据清理（支持对话旧记录 + 软删除任务）。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_system_engine()
            return engine.cleanup_data(scope, dry_run)
        return _inner()

    @mcp.tool()
    def llm_status(action: str = "status") -> str:
        """查看或控制本地 LLM 服务（Ollama）。"""
        from devpartner_agent.core.decorators import mcp_tool_handler

        @mcp_tool_handler
        def _inner():
            engine = get_system_engine()
            return engine.llm_status(action)
        return _inner()