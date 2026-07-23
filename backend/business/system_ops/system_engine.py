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

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class SystemEngine:
    """系统域业务逻辑"""

    def get_system_health(self) -> dict:
        result = {"timestamp": datetime.now().isoformat()}

        # 会话引擎健康
        try:
            from backend.business.conversation_mgr import get_conversation_engine

            engine = get_conversation_engine()
            result["conversation_engine"] = engine.get_system_health()
        except Exception as e:
            logger.warning(
                "SystemEngine.get_system_health: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["conversation_engine"] = {"status": "error", "error": str(e)}

        # 任务队列健康
        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            queue = get_task_queue()
            result["task_queue"] = queue.get_queue_stats()
        except Exception as e:
            logger.warning(
                "SystemEngine.get_system_health: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["task_queue"] = {"status": "error", "error": str(e)}

        # 知识库统计
        try:
            db = self._get_db()
            kp_total = db.query_local("SELECT COUNT(*) as cnt FROM knowledge_points")[0]["cnt"]
            kp_by_domain = db.query_local(
                "SELECT domain, COUNT(*) as cnt FROM knowledge_points GROUP BY domain ORDER BY cnt DESC LIMIT 10"
            )
            result["knowledge_base"] = {
                "total_points": kp_total,
                "by_domain": {r["domain"]: r["cnt"] for r in kp_by_domain},
            }
        except Exception as e:
            logger.warning(
                "SystemEngine.get_system_health: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["knowledge_base"] = {"error": str(e)}

        return result

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
        v5_columns = {
            col: (col in columns)
            for col in ["conversation_id", "status", "priority", "total_steps", "completed_steps"]
        }

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
        from backend.core.database.base_conn import get_db

        issues = []
        checks = {}

        # 数据库连接检查
        try:
            db = get_db()
            checks["database"] = "healthy"
        except Exception as e:
            logger.warning(
                "SystemEngine.system_diagnose: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            checks["database"] = f"unhealthy: {e}"
            issues.append(f"数据库异常: {e}")

        # 日志目录检查
        try:
            from foundation.config.app_settings import get_config

            cfg = get_config()
            log_dir = (
                Path(cfg.data.logs_dir)
                if hasattr(cfg, "data") and hasattr(cfg.data, "logs_dir")
                else Path("data/logs")
            )
            if log_dir.exists():
                log_count = len(list(log_dir.glob("*.md")))
                checks["logs"] = f"healthy ({log_count} 个日志文件)"
            else:
                checks["logs"] = "missing"
                issues.append("日志目录不存在")
        except Exception as e:
            logger.warning(
                "SystemEngine.system_diagnose: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            checks["logs"] = f"error: {e}"

        # 数据库表统计
        try:
            tables = [
                "conversations",
                "conversation_steps",
                "knowledge_points",
                "user_skills",
                "task_queue",
                "growth_analysis",
            ]
            table_counts = {}
            for t in tables:
                try:
                    row = db.query_local(f"SELECT COUNT(*) as cnt FROM {t}")
                    table_counts[t] = row[0]["cnt"] if row else 0
                except Exception:
                    logger.warning(
                        "SystemEngine.system_diagnose: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    table_counts[t] = "N/A"
            checks["tables"] = table_counts
        except Exception as e:
            logger.warning(
                "SystemEngine.system_diagnose: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            checks["tables"] = f"error: {e}"

        return {
            "success": True,
            "health": "healthy" if not issues else "degraded",
            "checks": checks,
            "issues": issues,
            "recommendations": ["重启服务"] if issues else [],
        }

    def check_data_integrity(self, include_write_stats: bool = True) -> dict:
        from backend.business.data_cleanup.cleanup_service import (
            check_and_log_integrity,
        )
        from backend.core.database.base_conn import get_db

        db = get_db()
        result = check_and_log_integrity(db)

        # 补充数据库统计（即使 WriteTracker 为空也有意义的数据）
        try:
            tables = [
                "conversations",
                "conversation_steps",
                "knowledge_points",
                "user_skills",
                "task_queue",
                "improvement_log",
                "user_profile",
                "connected_systems",
            ]
            db_stats = {}
            for t in tables:
                try:
                    row = db.query_local(f"SELECT COUNT(*) as cnt FROM {t}")
                    db_stats[t] = row[0]["cnt"] if row else 0
                except Exception:
                    logger.warning(
                        "SystemEngine.check_data_integrity: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    db_stats[t] = -1
            result["db_stats"] = db_stats
        except Exception:
            logger.warning(
                "SystemEngine.check_data_integrity: 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            pass

        return {"success": True, **result}

    def cleanup_data(self, scope: str = "all", dry_run: bool = False) -> dict:
        from backend.business.data_cleanup.cleanup_service import (
            get_cleanup_scheduler,
            get_cleanup_service,
        )
        from backend.core.database.base_conn import get_db

        result = {"scope": scope, "dry_run": dry_run, "actions": []}

        if scope in ("all", "conversations"):
            db = get_db()
            scheduler = get_cleanup_scheduler()
            if dry_run:
                # 预览模式：统计各阶段可清理的对话数量
                try:
                    warm_cutoff = (
                        datetime.now() - __import__("datetime").timedelta(days=7)
                    ).isoformat()
                    cold_cutoff = (
                        datetime.now() - __import__("datetime").timedelta(days=30)
                    ).isoformat()
                    warm_count = db.query_local(
                        "SELECT COUNT(*) as cnt FROM conversations WHERE status='completed' AND analyzed=1 AND completed_at IS NOT NULL AND completed_at <= ?",
                        (warm_cutoff,),
                    )
                    cold_count = db.query_local(
                        "SELECT COUNT(*) as cnt FROM conversations WHERE status='completed' AND analyzed=1 AND completed_at IS NOT NULL AND completed_at <= ?",
                        (cold_cutoff,),
                    )
                    conv_result = {
                        "dry_run": True,
                        "warm_archivable": warm_count[0]["cnt"] if warm_count else 0,
                        "cold_archivable": cold_count[0]["cnt"] if cold_count else 0,
                        "note": "预览模式：展示可归档/清理的会话数量",
                    }
                except Exception as e:
                    logger.warning(
                        "SystemEngine.cleanup_data: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    conv_result = {"dry_run": True, "error": str(e)}
            else:
                conv_result = scheduler.run_now()
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
                    result["tasks"] = {
                        "dry_run": True,
                        "soft_deleted_count": stats["soft_deleted_count"],
                    }
                else:
                    cs_result = cs._physical_delete_expired()
                    result["tasks"] = cs_result

        return result

    def llm_status(self, action: str = "status") -> dict:
        from backend.core.llm_kernel.base_client import get_llm_engine

        llm = get_llm_engine()

        if action == "preload":
            loaded = llm.preload()
            status = llm.get_status()
            status["preload_result"] = loaded
            return {"success": loaded, **status}

        return {"success": True, **llm.get_status()}

    def _get_db(self):
        from backend.core.database.base_conn import get_db

        return get_db()


_instance: SystemEngine | None = None


def get_system_engine() -> SystemEngine:
    global _instance
    if _instance is None:
        _instance = SystemEngine()
    return _instance
