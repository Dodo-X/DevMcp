"""
HTTP REST API 路由
==================
从 server.py 提取的 Web/API 路由（@mcp.custom_route）。
包括：
  - 根路径 / 健康检查
  - Dashboard
  - Growth Analytics API
  - System Status / Tasks / Memory / Callbacks / Health Check / Trends
  - Projects List/Query
"""
import json
import os as _os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse


def register_rest_routes(mcp):
    """注册所有 HTTP 路由到 MCP 实例"""

    from devpartner_agent.core.config import get_project_version
    VERSION = get_project_version()

    _DASHBOARD_PATH = _os.path.join(_os.path.dirname(__file__),
                                    "..", "dashboard.html")

    # ── 根路径 ──
    @mcp.custom_route("/", methods=["GET", "HEAD"])
    async def root_endpoint(request: Request):
        return JSONResponse({
            "service": "DevPartner v7.5",
            "version": VERSION,
            "protocol": "MCP Streamable HTTP",
            "mcp_endpoint": "/mcp",
            "health": "/health",
            "dashboard": "/dashboard",
            "status": "running",
        })

    # ── 健康检查 ──
    @mcp.custom_route("/health", methods=["GET", "HEAD"])
    async def health_endpoint(request: Request):
        return JSONResponse({"status": "healthy", "version": VERSION})

    # ── MCP 端点健康检查 ──
    @mcp.custom_route("/mcp", methods=["GET"])
    async def mcp_health_check(request: Request) -> JSONResponse:
        try:
            from devpartner_agent.core.llm_engine import get_llm_engine
            llm = get_llm_engine()
            llm_available = llm.is_available() if llm else False
        except Exception:
            llm_available = False
        return JSONResponse({
            "status": "ok",
            "server": "devpartner",
            "version": VERSION,
            "protocol": "MCP Streamable HTTP (POST /mcp)",
            "dashboard": "/dashboard",
            "health": "/health",
            "llm_available": llm_available,
        })

    # ── Dashboard ──
    @mcp.custom_route("/dashboard", methods=["GET"])
    async def serve_dashboard(request: Request) -> HTMLResponse:
        try:
            with open(_DASHBOARD_PATH, "r", encoding="utf-8") as f:
                html = f.read()
            html = html.replace("{{VERSION}}", VERSION)
            return HTMLResponse(html)
        except FileNotFoundError:
            return HTMLResponse(
                "<h1>Dashboard not found</h1>",
                status_code=404
            )

    # ════════════════════════════════════════════════
    # Growth Analytics API
    # ════════════════════════════════════════════════
    from devpartner_tools.tools.growth_analytics import (
        get_user_growth_overview,
        get_user_skill_radar,
        get_learning_timeline,
        get_user_activity_heatmap,
    )

    @mcp.custom_route("/api/growth/user-overview", methods=["GET"])
    async def api_user_growth_overview(request: Request) -> JSONResponse:
        data = json.loads(get_user_growth_overview())
        return JSONResponse(content=data)

    @mcp.custom_route("/api/growth/skill-radar", methods=["GET"])
    async def api_skill_radar(request: Request) -> JSONResponse:
        data = json.loads(get_user_skill_radar())
        return JSONResponse(content=data)

    @mcp.custom_route("/api/growth/timeline", methods=["GET"])
    async def api_learning_timeline(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", 20))
        data = json.loads(get_learning_timeline(limit=limit))
        return JSONResponse(content=data)

    @mcp.custom_route("/api/growth/activity-heatmap", methods=["GET"])
    async def api_activity_heatmap(request: Request) -> JSONResponse:
        data = json.loads(get_user_activity_heatmap())
        return JSONResponse(content=data)

    # ════════════════════════════════════════════════
    # System Status API
    # ════════════════════════════════════════════════
    from datetime import date as _dt_date

    @mcp.custom_route("/api/system/status", methods=["GET"])
    async def api_system_status(request: Request) -> JSONResponse:
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            today = _dt_date.today().isoformat()

            active = db.query_local(
                "SELECT COUNT(DISTINCT conversation_id) as cnt FROM conversations "
                "WHERE timestamp >= datetime('now', '-1 day')"
            )
            active_sessions = active[0]["cnt"] if active else 0

            today_new = db.query_local(
                "SELECT COUNT(DISTINCT conversation_id) as cnt FROM conversations "
                "WHERE date(timestamp) = ?", (today,)
            )
            today_sessions = today_new[0]["cnt"] if today_new else 0

            pending_tasks = running_tasks = completed_tasks = 0
            try:
                from devpartner_agent.services.task_queue import get_task_queue
                tq = get_task_queue()
                ts = tq.get_queue_stats()
                pending_tasks = ts.get("pending_tasks", 0)
                running_tasks = ts.get("running_tasks", 0)
                completed_tasks = ts.get("total_completed", 0)
            except Exception:
                pass

            kb_size = 0
            try:
                kb = db.query_local("SELECT COUNT(*) as cnt FROM knowledge_points")
                kb_size = kb[0]["cnt"] if kb else 0
            except Exception:
                pass

            today_knowledge = 0
            try:
                kt = db.query_local(
                    "SELECT COUNT(*) as cnt FROM knowledge_points WHERE date(created_at) = ?",
                    (today,)
                )
                today_knowledge = kt[0]["cnt"] if kt else 0
            except Exception:
                pass

            callback_registrations = callback_triggers = 0
            try:
                from devpartner_agent.services.callback_registry import get_callback_registry
                cr = get_callback_registry()
                cs = cr.get_stats()
                callback_registrations = cs.get("total_registrations", 0)
                callback_triggers = cs.get("total_triggered", 0)
            except Exception:
                pass

            pending_analyses_count = 0
            pending_analyses_details = []
            try:
                pa_rows = db.query_local(
                    "SELECT analysis_type, source_date, missing_dimensions, status, created_at "
                    "FROM pending_analyses WHERE status = 'pending' ORDER BY created_at ASC"
                )
                pending_analyses_count = len(pa_rows or [])
                for pa in (pa_rows or [])[:20]:
                    pending_analyses_details.append({
                        "type": pa.get("analysis_type", ""),
                        "date": pa.get("source_date", ""),
                        "missing_dimensions": pa.get("missing_dimensions", "[]"),
                        "created_at": pa.get("created_at", ""),
                    })
            except Exception:
                pass

            return JSONResponse(content={
                "active_sessions": active_sessions,
                "today_new_sessions": today_sessions,
                "pending_tasks": pending_tasks,
                "running_tasks": running_tasks,
                "completed_tasks": completed_tasks,
                "knowledge_base_size": kb_size,
                "today_knowledge_added": today_knowledge,
                "callback_registrations": callback_registrations,
                "callback_triggers": callback_triggers,
                "pending_analyses_count": pending_analyses_count,
                "pending_analyses_details": pending_analyses_details,
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/pending-analyses/process", methods=["POST"])
    async def api_process_pending_analyses(request: Request) -> JSONResponse:
        """手动触发待分析数据清算（v8.0）"""
        try:
            from devpartner_agent.skills.daily_summary import process_pending_analyses
            result = process_pending_analyses()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/archive/cleanup", methods=["POST"])
    async def api_archive_cleanup(request: Request) -> JSONResponse:
        """手动触发数据归档与清理（v8.0）"""
        try:
            from devpartner_agent.skills.daily_summary import archive_and_cleanup_data
            result = archive_and_cleanup_data()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/report/weekly", methods=["POST"])
    async def api_weekly_report(request: Request) -> JSONResponse:
        """手动触发周报生成（v8.0）"""
        try:
            from devpartner_agent.skills.daily_summary import generate_weekly_report
            result = generate_weekly_report()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/report/monthly", methods=["POST"])
    async def api_monthly_report(request: Request) -> JSONResponse:
        """手动触发月报生成（v8.0）"""
        try:
            from devpartner_agent.skills.daily_summary import generate_monthly_report
            result = generate_monthly_report()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/report/annual", methods=["POST"])
    async def api_annual_report(request: Request) -> JSONResponse:
        """手动触发年报生成（v8.0）"""
        try:
            from devpartner_agent.skills.daily_summary import generate_annual_report
            result = generate_annual_report()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/report/next", methods=["GET"])
    async def api_report_next(request: Request) -> JSONResponse:
        """获取下次各类报告的预计生成时间（v8.0 — 文件名即计算节点）"""
        try:
            from devpartner_agent.services.vault_exporter import get_vault_exporter
            from datetime import datetime, timedelta

            exporter = get_vault_exporter()
            now = datetime.now()
            result = {}

            latest_weekly = exporter.get_latest_report_date("weekly")
            if latest_weekly:
                try:
                    year_part, week_part = latest_weekly.split("-W")
                    last_week_end = datetime.strptime(
                        f"{year_part} {int(week_part)} 0", "%Y %W %w"
                    ) + timedelta(days=6)
                    next_weekly = last_week_end + timedelta(days=1)
                    days_until = (next_weekly - now).days
                    result["weekly"] = {
                        "latest": latest_weekly,
                        "next_date": next_weekly.strftime("%Y-%m-%d"),
                        "days_until": max(0, days_until),
                    }
                except Exception:
                    result["weekly"] = {"latest": latest_weekly, "error": "parse_failed"}
            else:
                result["weekly"] = {"latest": None, "note": "尚未生成周报"}

            latest_monthly = exporter.get_latest_report_date("monthly")
            if latest_monthly:
                try:
                    year_m, month_m = latest_monthly.split("-")
                    next_monthly = datetime(int(year_m), int(month_m), 1) + timedelta(days=32)
                    next_monthly = next_monthly.replace(day=1)
                    days_until = (next_monthly - now).days
                    result["monthly"] = {
                        "latest": latest_monthly,
                        "next_date": next_monthly.strftime("%Y-%m-%d"),
                        "days_until": max(0, days_until),
                    }
                except Exception:
                    result["monthly"] = {"latest": latest_monthly, "error": "parse_failed"}
            else:
                result["monthly"] = {"latest": None, "note": "尚未生成月报"}

            latest_annual = exporter.get_latest_report_date("annual")
            if latest_annual:
                try:
                    next_annual = datetime(int(latest_annual) + 1, 12, 31)
                    days_until = (next_annual - now).days
                    result["annual"] = {
                        "latest": latest_annual,
                        "next_date": next_annual.strftime("%Y-%m-%d"),
                        "days_until": max(0, days_until),
                    }
                except Exception:
                    result["annual"] = {"latest": latest_annual, "error": "parse_failed"}
            else:
                result["annual"] = {"latest": None, "note": "尚未生成年报"}

            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/list", methods=["GET"])
    async def api_tasks_list(request: Request) -> JSONResponse:
        try:
            limit = int(request.query_params.get("limit", 20))
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            tasks = []
            for task_id, task_data in tq._task_map.items():
                payload = task_data.get("payload", {})
                task_name = (
                    payload.get("step_name") or 
                    payload.get("step_type") or 
                    task_data.get("task_type", "general")
                )
                tasks.append({
                    "id": task_id[:8] if len(task_id) > 8 else task_id,
                    "name": task_name if isinstance(task_name, str) else str(task_name),
                    "type": task_data.get("task_type", "general"),
                    "status": task_data.get("status", "pending"),
                    "created_at": task_data.get("queued_at") or "",
                    "priority": task_data.get("priority", 0),
                })
            tasks.sort(key=lambda t: t["created_at"] or "z")
            return JSONResponse(content=tasks[:limit])
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Task Ops API (v8.1 — 运维监管)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/tasks/diagnostics", methods=["GET"])
    async def api_tasks_diagnostics(request: Request) -> JSONResponse:
        """任务队列深度诊断（阶段锁、并发槽位、运行中任务详情）"""
        try:
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            diag = tq.get_diagnostics()
            return JSONResponse(content=diag)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/handlers", methods=["GET"])
    async def api_tasks_handlers(request: Request) -> JSONResponse:
        """已注册的任务处理器清单"""
        try:
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            stats = tq.get_queue_stats()
            handlers = stats.get("registered_handlers", [])
            parallel_types = list(tq.PHASE_PARALLEL)
            sequential_types = list(tq.PHASE_SEQUENTIAL)
            handler_info = []
            for h in handlers:
                phase = "PARALLEL" if h in tq.PHASE_PARALLEL else (
                    "SEQUENTIAL" if h in tq.PHASE_SEQUENTIAL else "UNKNOWN"
                )
                handler_info.append({"name": h, "phase": phase})
            return JSONResponse(content={
                "total": len(handlers),
                "handlers": handler_info,
                "phase_parallel_count": len(parallel_types),
                "phase_sequential_count": len(sequential_types),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/cancel", methods=["POST"])
    async def api_tasks_cancel(request: Request) -> JSONResponse:
        """取消待执行的任务（仅 pending/queued 状态可取消）"""
        try:
            body = await request.json()
            task_id = body.get("task_id", "")
            if not task_id:
                return JSONResponse(content={"error": "缺少 task_id"}, status_code=400)
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            ok = tq.cancel_task(task_id)
            return JSONResponse(content={"success": ok, "task_id": task_id})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/stats", methods=["GET"])
    async def api_tasks_stats(request: Request) -> JSONResponse:
        """任务队列统计指标（成功率、平均耗时、并发槽位）"""
        try:
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            stats = tq.get_queue_stats()
            total = stats.get("total_completed", 0) + stats.get("total_failed", 0)
            success_rate = round(stats.get("total_completed", 0) / max(1, total) * 100, 1)
            return JSONResponse(content={
                "pending": stats.get("pending_tasks", 0),
                "running": stats.get("running_tasks", 0),
                "completed": stats.get("total_completed", 0),
                "failed": stats.get("total_failed", 0),
                "cancelled": stats.get("total_cancelled", 0),
                "timeout": stats.get("total_timeout", 0),
                "success_rate": success_rate,
                "avg_execution_time": round(stats.get("avg_execution_time", 0), 2),
                "available_slots": stats.get("available_slots", 0),
                "active_workers": stats.get("active_workers", 0),
                "memory_usage_mb": stats.get("memory_usage_mb", 0),
                "memory_limit_mb": stats.get("memory_limit_mb", 0),
                "utilization_percent": stats.get("utilization_percent", 0),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/memory", methods=["GET"])
    async def api_system_memory(request: Request) -> JSONResponse:
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            used_mb = round(mem_info.rss / 1024 / 1024, 1)
            total_mb = round(psutil.virtual_memory().total / 1024 / 1024)
            percent = round((used_mb / max(1, total_mb)) * 100, 1)
            details = [
                {"name": "RSS 物理内存", "size_mb": used_mb, "percent": percent},
                {"name": "VMS 虚拟内存", "size_mb": round(mem_info.vms / 1024 / 1024, 1), "percent": percent},
            ]
            vm = psutil.virtual_memory()
            sys_used = round(vm.used / 1024 / 1024)
            details.append({"name": "系统总使用", "size_mb": sys_used, "percent": vm.percent})
            return JSONResponse(content={
                "used_mb": used_mb, "total_mb": total_mb, "percent": percent, "details": details,
            })
        except ImportError:
            try:
                from devpartner_agent.services.task_queue import get_task_queue
                tq = get_task_queue()
                stats = tq.get_queue_stats()
                return JSONResponse(content={
                    "used_mb": stats.get("memory_usage_mb", 0),
                    "total_mb": stats.get("memory_limit_mb", 500),
                    "percent": stats.get("utilization_percent", 0), "details": [],
                })
            except Exception:
                return JSONResponse(content={"used_mb": 0, "total_mb": 1, "percent": 0, "details": []})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/callbacks/stats", methods=["GET"])
    async def api_callback_stats(request: Request) -> JSONResponse:
        try:
            from devpartner_agent.services.callback_registry import get_callback_registry
            cr = get_callback_registry()
            stats = cr.get_stats()
            recent = []
            with cr._lock:
                for reg_id, reg in list(cr._registrations.items())[:5]:
                    recent.append({
                        "id": reg_id[:12] if len(reg_id) > 12 else reg_id,
                        "name": f"cb:{reg.conversation_id[:8]}" if reg.conversation_id else f"cb:{reg_id[:8]}",
                        "status": "active" if reg.is_active else "inactive",
                        "timestamp": reg.last_triggered_at or reg.created_at or "",
                    })
            return JSONResponse(content={
                "success_count": stats.get("total_triggered", 0),
                "error_count": stats.get("total_errors", 0),
                "recent_calls": recent,
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/health/check", methods=["GET"])
    async def api_health_check(request: Request) -> JSONResponse:
        result = {"services": {}}
        result["services"]["mcp_server"] = {"healthy": True, "detail": "运行中"}
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local("SELECT 1")
            result["services"]["database"] = {"healthy": True, "detail": "连接正常"}
        except Exception as e:
            result["services"]["database"] = {"healthy": False, "detail": str(e)}
        try:
            from devpartner_agent.core.llm_engine import get_llm_engine
            llm = get_llm_engine()
            available = llm.is_available() if llm else False
            result["services"]["llm_service"] = {
                "healthy": available,
                "detail": "Ollama 已连接" if available else "Ollama 不可达",
            }
        except Exception as e:
            result["services"]["llm_service"] = {"healthy": False, "detail": str(e)}
        try:
            test_path = Path(_os.path.dirname(__file__)) / ".." / ".." / "data"
            writable = _os.access(str(test_path), _os.W_OK) if test_path.exists() else False
            result["services"]["filesystem"] = {
                "healthy": test_path.exists() and writable,
                "detail": "可读写" if writable else ("目录不存在" if not test_path.exists() else "无写入权限"),
            }
        except Exception as e:
            result["services"]["filesystem"] = {"healthy": False, "detail": str(e)}
        return JSONResponse(content=result)

    @mcp.custom_route("/api/trends/system", methods=["GET"])
    async def api_system_trends(request: Request) -> JSONResponse:
        try:
            hours = int(request.query_params.get("hours", 24))
            from devpartner_agent.core.database import get_db
            db = get_db()
            rows = db.query_local(
                "SELECT strftime('%H:00', timestamp) as hour, "
                "COUNT(DISTINCT conversation_id) as cnt "
                "FROM conversations "
                "WHERE timestamp >= datetime('now', '-{} hours') "
                "GROUP BY strftime('%Y-%m-%d %H', timestamp) "
                "ORDER BY strftime('%Y-%m-%d %H', timestamp)".format(hours)
            )
            timestamps = []
            sessions = []
            if rows:
                for r in rows:
                    timestamps.append(r["hour"])
                    sessions.append(r["cnt"])
            else:
                timestamps = ["00:00"]
                sessions = [0]
            completed = 0
            triggered = 0
            try:
                from devpartner_agent.services.task_queue import get_task_queue
                completed = get_task_queue().get_queue_stats().get("total_completed", 0)
            except Exception:
                pass
            try:
                from devpartner_agent.services.callback_registry import get_callback_registry
                triggered = get_callback_registry().get_stats().get("total_triggered", 0)
            except Exception:
                pass
            n = max(1, len(timestamps))
            return JSONResponse(content={
                "timestamps": timestamps,
                "sessions": sessions,
                "tasks_completed": [max(0, completed // n)] * n,
                "callbacks_triggered": [max(0, triggered // n)] * n,
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Projects Knowledge API
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/projects/list", methods=["GET"])
    async def api_projects_list(request: Request) -> JSONResponse:
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            rows = db.query_local(
                "SELECT DISTINCT domain FROM knowledge_points WHERE type = 'business' ORDER BY domain"
            )
            projects = [r["domain"] for r in (rows or [])]
            return JSONResponse(content={"success": True, "projects": projects})
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/projects/query", methods=["POST"])
    async def api_projects_query(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            question = body.get("question", "")
            project_name = body.get("project_name", "")
            category = body.get("category", "")
            limit = body.get("limit", 5)

            from devpartner_agent.core.database import get_db
            db = get_db()

            conditions = []
            params = []

            if category and category in ("skill", "business"):
                conditions.append("kp.type = ?")
                params.append(category)

            if project_name:
                conditions.append("kp.type = 'business' AND kp.domain = ?")
                params.append(project_name)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            if question:
                search_term = f"%{question}%"
                sql = f"""
                    SELECT kp.knowledge_id, kp.title, kp.content, kp.type, kp.domain,
                           kp.tags, kp.category, kp.difficulty, kp.usage_count, kp.created_at
                    FROM knowledge_points kp
                    WHERE {where_clause}
                      AND (kp.title LIKE ? OR kp.content LIKE ?)
                    ORDER BY kp.usage_count DESC, kp.created_at DESC
                    LIMIT ?
                """
                params.extend([search_term, search_term, limit])
            else:
                sql = f"""
                    SELECT kp.knowledge_id, kp.title, kp.content, kp.type, kp.domain,
                           kp.tags, kp.category, kp.difficulty, kp.usage_count, kp.created_at
                    FROM knowledge_points kp
                    WHERE {where_clause}
                    ORDER BY kp.usage_count DESC, kp.created_at DESC
                    LIMIT ?
                """
                params.append(limit)

            rows = db.query_local(sql, tuple(params))

            results = []
            for row in (rows or []):
                tags = row.get("tags", "[]")
                if isinstance(tags, str):
                    try:
                        tags = json.loads(tags)
                    except Exception:
                        tags = [tags]
                content = row.get("content", "")
                results.append({
                    "knowledge_id": row["knowledge_id"],
                    "title": row["title"],
                    "summary": content[:300] + "..." if len(content) > 300 else content,
                    "content": content,
                    "type": row.get("type", "skill"),
                    "domain": row.get("domain", ""),
                    "tags": tags,
                    "category": row.get("category", ""),
                    "difficulty": row.get("difficulty", "medium"),
                    "usage_count": row.get("usage_count", 0),
                })

            return JSONResponse(content={
                "success": True,
                "question": question,
                "project_name": project_name,
                "category_filter": category,
                "total": len(results),
                "results": results,
            })
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)