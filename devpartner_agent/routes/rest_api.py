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
from datetime import datetime
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse


def register_rest_routes(mcp):
    """注册所有 HTTP 路由到 MCP 实例"""

    from devpartner_agent.core.config import get_project_version
    VERSION = get_project_version()

    # ── 根路径 ──
    @mcp.custom_route("/", methods=["GET", "HEAD"])
    async def root_endpoint(request: Request):
        return JSONResponse({
            "service": "DevPartner v7.5",
            "version": VERSION,
            "protocol": "MCP Streamable HTTP",
            "mcp_endpoint": "/mcp",
            "health": "/health",
            "status": "running",
        })

    # ── Dashboard ──
    @mcp.custom_route("/dashboard", methods=["GET"])
    async def dashboard_endpoint(request: Request):
        """返回运维面板 HTML 页面"""
        dashboard_path = Path(__file__).resolve().parent.parent / "dashboard.html"
        if dashboard_path.exists():
            content = dashboard_path.read_text(encoding="utf-8")
            content = content.replace("{{VERSION}}", VERSION)
            return HTMLResponse(content=content)
        # 降级：返回 JSON 导航
        return JSONResponse({
            "service": "DevPartner",
            "version": VERSION,
            "status": "running",
            "error": "dashboard.html not found",
            "api": {
                "growth_list": "/api/growth/list",
                "growth_review": "/api/growth/review",
                "system_status": "/api/system/status",
                "tasks": "/api/tasks/stats",
                "memory": "/api/system/memory",
                "projects": "/api/projects/list",
            }
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
            "health": "/health",
            "llm_available": llm_available,
        })

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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
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
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/progress", methods=["GET"])
    async def api_tasks_progress(request: Request) -> JSONResponse:
        """v9.5.1: 运行中任务进度列表（含心跳、部分结果、进度百分比）。

        Dashboard 前端轮询此端点，实时展示长任务（日报/深度分析）的执行进度。
        配合 task_queue 的心跳机制，即使 LLM 推理需要 30+ 分钟也不会被误判为僵尸。
        """
        try:
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            running = tq.get_running_tasks_with_progress()

            return JSONResponse(content={
                "running_count": len(running),
                "tasks": running,
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/job-status", methods=["GET"])
    async def api_tasks_job_status(request: Request) -> JSONResponse:
        """v9.5.1: 查询指定任务的状态和结果（用于异步提交→轮询模式）。

        Query params:
            task_id: 任务ID（必填）
        """
        try:
            task_id = request.query_params.get("task_id", "")
            if not task_id:
                return JSONResponse(content={"error": "缺少 task_id"}, status_code=400)

            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            task = tq.get_task_status(task_id)
            if not task:
                return JSONResponse(content={"error": "任务不存在", "task_id": task_id}, status_code=404)

            return JSONResponse(content={
                "task_id": task.get("task_id", task_id),
                "status": task.get("status", ""),
                "task_type": task.get("task_type", ""),
                "progress": task.get("progress", 0.0),
                "partial_result": task.get("partial_result", ""),
                "status_note": task.get("status_note", ""),
                "last_heartbeat": task.get("last_heartbeat", ""),
                "started_at": task.get("started_at", ""),
                "completed_at": task.get("completed_at", ""),
                "error_message": task.get("error_message", ""),
                "result": task.get("result"),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
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

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
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
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Ollama 管理 API (v8.3)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/ollama/status", methods=["GET"])
    async def api_ollama_status(request: Request) -> JSONResponse:
        """获取 Ollama 服务详细状态和启动日志"""
        try:
            from devpartner_agent.core import bootstrap
            from devpartner_agent.core.llm_engine import get_llm_engine

            llm = get_llm_engine()
            llm_status = llm.get_status() if llm else {}
            logs = bootstrap.get_ollama_logs()

            ollama_url = _os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

            model_name = ""
            try:
                from devpartner_agent.core.config import get_config
                cfg = get_config()
                model_name = getattr(cfg.llm, "ollama_model", "qwen3") if hasattr(cfg, "llm") else "qwen3"
            except Exception:
                model_name = "qwen3"

            return JSONResponse(content={
                "available": llm_status.get("available", False),
                "enabled": llm_status.get("enabled", False),
                "ollama_url": ollama_url,
                "model_name": model_name,
                "inference_count": llm_status.get("inference_count", 0),
                "avg_tokens_per_second": llm_status.get("avg_tokens_per_second", 0),
                "load_error": llm_status.get("load_error"),
                "logs": logs,
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/ollama/start", methods=["POST"])
    async def api_ollama_start(request: Request) -> JSONResponse:
        """手动启动/重连 Ollama 服务"""
        try:
            from devpartner_agent.core import bootstrap
            body = await request.json() if request.headers.get("content-length") else {}
            timeout = int(body.get("timeout", 30)) if body else 30
            result = bootstrap.start_ollama_service(timeout=timeout)

            if result["success"]:
                try:
                    from devpartner_agent.core.llm_engine import get_llm_engine
                    llm = get_llm_engine()
                    if llm:
                        llm.preload()
                except Exception as e:
                    result["logs"].append({"time": "", "level": "WARN",
                                           "msg": f"LLM 预加载失败: {e}"})

            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/ollama/stop", methods=["POST"])
    async def api_ollama_stop(request: Request) -> JSONResponse:
        """停止 Ollama 服务"""
        try:
            import subprocess, sys
            result = subprocess.run(
                ["ollama", "stop"],
                capture_output=True, text=True, timeout=10
            )
            from devpartner_agent.core import bootstrap
            bootstrap.reset_ollama_state()
            bootstrap._ollama_log("Ollama 服务已手动停止", "INFO")
            return JSONResponse(content={
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            })
        except FileNotFoundError:
            return JSONResponse(content={"success": False, "error": "ollama 命令未找到"})
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Growth Analysis API (v8.3 — Dashboard 审核)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/growth/list", methods=["GET"])
    async def api_growth_list(request: Request) -> JSONResponse:
        """获取系统成长分析列表"""
        try:
            status_filter = request.query_params.get("status", "pending")
            limit = int(request.query_params.get("limit", 50))
            source_period = request.query_params.get("source_period", "")

            from devpartner_agent.core.database import get_db
            db = get_db()

            if source_period:
                rows = db.get_growth_analysis_by_period(source_period)
            elif status_filter == "pending":
                rows = db.get_pending_growth_analysis(limit=limit)
            else:
                rows = db.query_local(
                    "SELECT * FROM growth_analysis WHERE status = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (status_filter, limit)
                )

            result = []
            for r in (rows or []):
                result.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "analysis_type": r["analysis_type"],
                    "title": r["title"] or "",
                    "description": r["description"] or "",
                    "suggestion": r["suggestion"] or "",
                    "related_data": r.get("related_data", "{}"),
                    "priority": r["priority"] or "medium",
                    "status": r["status"] or "pending",
                    "reviewer": r.get("reviewer") or "",
                    "review_comment": r.get("review_comment") or "",
                    "reviewed_at": r.get("reviewed_at") or "",
                    "applied_at": r.get("applied_at") or "",
                    "source": r.get("source", "monthly_report"),
                    "source_period": r.get("source_period", ""),
                })

            return JSONResponse(content={"total": len(result), "items": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/growth/review", methods=["POST"])
    async def api_growth_review(request: Request) -> JSONResponse:
        """审核系统成长分析（通过/拒绝）"""
        try:
            body = await request.json()
            analysis_id = body.get("id")
            action = body.get("action")  # "approved" 或 "rejected"
            reviewer = body.get("reviewer", "admin")
            comment = body.get("comment", "")

            if not analysis_id or action not in ("approved", "rejected"):
                return JSONResponse(
                    content={"error": "缺少 id 或 action 参数 (approved/rejected)"},
                    status_code=400
                )

            from devpartner_agent.core.database import get_db
            db = get_db()
            db.review_growth_analysis(analysis_id, action, reviewer, comment)

            return JSONResponse(content={
                "success": True,
                "id": analysis_id,
                "action": action,
            })
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/growth/apply", methods=["POST"])
    async def api_growth_apply(request: Request) -> JSONResponse:
        """标记成长分析为已应用"""
        try:
            body = await request.json()
            analysis_id = body.get("id")

            if not analysis_id:
                return JSONResponse(content={"error": "缺少 id 参数"}, status_code=400)

            from devpartner_agent.core.database import get_db
            db = get_db()
            db.apply_growth_analysis(analysis_id)

            return JSONResponse(content={"success": True, "id": analysis_id})
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Projects Knowledge API
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/projects/list", methods=["GET"])
    async def api_projects_list(request: Request) -> JSONResponse:
        """
        v8.5.8: 项目列表 = 通过 MCP 对接的 CodeBuddy/Trae 等客户端的项目名
        数据源: connected_systems 表（project_path → 取目录名作为项目名）
        回退: 如无数据，取当前工作目录名
        """
        try:
            from devpartner_agent.core.database import get_db
            import os as _os
            db = get_db()
            projects = []

            # 主数据源: connected_systems 表 — 对接的真实项目
            try:
                rows = db.query_local(
                    """SELECT system_id, project_path, display_name, system_type
                       FROM connected_systems ORDER BY last_seen_at DESC"""
                )
                for r in (rows or []):
                    proj_path = r.get("project_path", "")
                    proj_name = r.get("display_name", "") or (
                        _os.path.basename(proj_path.rstrip("/\\")) if proj_path else ""
                    )
                    if proj_name and proj_name not in [p["name"] for p in projects]:
                        projects.append({
                            "name": proj_name,
                            "path": proj_path,
                            "system_id": r.get("system_id", ""),
                            "system_type": r.get("system_type", ""),
                        })
            except Exception:
                pass

            # 回退: 如果 connected_systems 为空，用当前工作目录名
            if not projects:
                fallback_name = _os.path.basename(_os.getcwd())
                projects = [{"name": fallback_name, "path": _os.getcwd(), "system_id": "default", "system_type": ""}]

            # 按项目名排序
            projects.sort(key=lambda p: p["name"].lower())

            return JSONResponse(content={"success": True, "projects": projects})
        except Exception as e:
            logger.error(f"/api/projects/list 异常: {e}")
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/projects/query", methods=["POST"])
    async def api_projects_query(request: Request) -> JSONResponse:
        try:
            import json as _json
            raw_body = await request.body()
            if not raw_body:
                return JSONResponse(content={"success": False, "error": "请求体为空", "results": []})
            body = _json.loads(raw_body)
            question = (body.get("question") or "").strip()
            project_name = (body.get("project_name") or "").strip()
            category = (body.get("category") or "").strip()
            limit = min(body.get("limit", 10) or 10, 50)

            from devpartner_agent.core.database import get_db
            db = get_db()

            # 简化查询：直接按 project_name 过滤 domain 字段
            params = []
            conditions = []

            if project_name:
                conditions.append("kp.domain = ?")
                params.append(project_name)

            if category and category in ("skill", "business"):
                conditions.append("kp.type = ?")
                params.append(category)

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

            rows = db.query_local(sql, tuple(params)) if params else db.query_local(sql.replace("WHERE 1=1", "").replace("WHERE 1=1", ""))

            results = []
            for row in (rows or []):
                tags = row.get("tags", "[]")
                if isinstance(tags, str):
                    try:
                        tags = _json.loads(tags)
                    except Exception:
                        tags = [tags]
                content = row.get("content") or ""
                results.append({
                    "knowledge_id": row["knowledge_id"],
                    "title": row.get("title") or "",
                    "summary": (content[:300] + "...") if len(content) > 300 else content,
                    "content": content,
                    "type": row.get("type", "skill"),
                    "domain": row.get("domain") or "",
                    "tags": tags if isinstance(tags, list) else [],
                    "category": row.get("category") or "",
                    "difficulty": row.get("difficulty", "medium"),
                    "usage_count": row.get("usage_count") or 0,
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
            logger.error(f"/api/projects/query 异常: {e}")
            return JSONResponse(content={"success": False, "error": str(e), "results": []})

    # ════════════════════════════════════════════════
    # Internal Operation API（内部运维工具，不暴露给 MCP 客户端）
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/system/check-integrity", methods=["GET"])
    async def api_check_integrity(request: Request) -> JSONResponse:
        """数据库数据完整性检查（内部运维）"""
        try:
            from devpartner_agent.core.system_engine import get_system_engine
            engine = get_system_engine()
            result = engine.check_data_integrity()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/cleanup", methods=["POST"])
    async def api_cleanup_data(request: Request) -> JSONResponse:
        """数据清理（内部运维）"""
        try:
            body = await request.json()
            scope = body.get("scope", "all")
            dry_run = body.get("dry_run", False)
            from devpartner_agent.core.system_engine import get_system_engine
            engine = get_system_engine()
            result = engine.cleanup_data(scope, dry_run)
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/health", methods=["GET"])
    async def api_system_health(request: Request) -> JSONResponse:
        """系统整体健康状态"""
        try:
            from devpartner_agent.core.system_engine import get_system_engine
            engine = get_system_engine()
            result = engine.get_system_health()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/diagnose", methods=["GET"])
    async def api_system_diagnose(request: Request) -> JSONResponse:
        """系统诊断"""
        try:
            from devpartner_agent.core.system_engine import get_system_engine
            engine = get_system_engine()
            result = engine.system_diagnose()
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/llm-status", methods=["GET", "POST"])
    async def api_llm_status(request: Request) -> JSONResponse:
        """LLM 服务状态查看或控制"""
        try:
            action = request.query_params.get("action", "status")
            from devpartner_agent.core.system_engine import get_system_engine
            engine = get_system_engine()
            result = engine.llm_status(action)
            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Reports API（v8.5.7 — Dashboard 报告管理）
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/reports/generate", methods=["POST"])
    async def api_reports_generate(request: Request) -> JSONResponse:
        """手动触发生成周报/月报/年报（支持覆盖模式 + 指定日期范围）"""
        try:
            body = await request.json()
            report_type = body.get("type", "weekly")  # weekly | monthly | annual
            target_date = body.get("target_date", "")  # YYYY-MM-DD，定位到目标周期
            force_overwrite = body.get("force_overwrite", False)

            if report_type not in ("weekly", "monthly", "annual"):
                return JSONResponse(
                    content={"success": False, "error": "type 必须是 weekly/monthly/annual"},
                    status_code=400,
                )

            from devpartner_agent.skills.daily_summary import (
                generate_weekly_report,
                generate_monthly_report,
                generate_annual_report,
            )

            kwargs = {"force_overwrite": force_overwrite}
            if target_date:
                kwargs["target_date"] = target_date

            if report_type == "weekly":
                result = generate_weekly_report(**kwargs)
            elif report_type == "monthly":
                result = generate_monthly_report(**kwargs)
            else:
                result = generate_annual_report(**kwargs)

            return JSONResponse(content=result)
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/reports/generate-daily", methods=["POST"])
    async def api_reports_generate_daily(request: Request) -> JSONResponse:
        """手动触发指定日期的日报生成（支持覆盖）"""
        try:
            body = await request.json()
            date_str = body.get("date", "")  # YYYY-MM-DD，必填
            force_overwrite = body.get("force_overwrite", False)

            if not date_str:
                return JSONResponse(
                    content={"success": False, "error": "缺少 date 参数"},
                    status_code=400,
                )

            from devpartner_agent.skills.daily_summary import generate_daily_summary
            from devpartner_agent.services.vault_exporter import get_vault_exporter

            exporter = get_vault_exporter()
            target_file = exporter._calendar_dir / f"{date_str}.md"

            if target_file.exists() and not force_overwrite:
                return JSONResponse(content={
                    "success": True,
                    "method": "skipped",
                    "file_path": str(target_file),
                    "note": f"日报已存在: {date_str}.md（勾选覆盖可重新生成）",
                })

            result = generate_daily_summary(date_str)

            # v9.3.3: 字段映射 + MD 导出，对齐前端 method 字段和周/月/年报行为
            method = result.get("analysis_method", "unknown")
            file_path = None

            if method == "llm":
                # LLM 分析成功 → 导出 MD 日报
                try:
                    from devpartner_agent.services.vault_exporter import get_vault_exporter
                    exporter = get_vault_exporter()
                    file_path = str(exporter.export_daily_report(date_str, result))
                    if file_path:
                        logger.info(f"📅 日报已导出到 Calendar: {file_path}")
                except Exception as export_err:
                    logger.warning(f"⚠️ 日报 MD 导出失败: {export_err}")

            # v9.4: 日报生成后一并执行用户画像合并 + 系统认知合并（对齐定时任务流程）
            profile_result = None
            system_result = None
            try:
                from devpartner_agent.skills.daily_summary import merge_daily_profile, merge_daily_system_context
                profile_result = merge_daily_profile(date_str=date_str)
                system_result = merge_daily_system_context(date_str=date_str)
                if profile_result.get("success") or system_result.get("success"):
                    logger.info(
                        f"📊 画像/系统合并完成: "
                        f"profile={profile_result.get('method', '?')}({profile_result.get('dimensions_updated', 0)}), "
                        f"system={system_result.get('method', '?')}({system_result.get('systems_updated', 0)})"
                    )
            except Exception as merge_err:
                logger.warning(f"⚠️ 画像/系统合并失败（不影响日报结果）: {merge_err}")

            return JSONResponse(content={
                "success": result.get("success", True),
                "method": method,
                "file_path": file_path,
                "date": result.get("date", date_str),
                "summary": result.get("summary", {}),
                "raw_data": result.get("raw_data"),
                "note": result.get("note", ""),
                "profile_merge": profile_result,
                "system_merge": system_result,
            })
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/reports/list", methods=["GET"])
    async def api_reports_list(request: Request) -> JSONResponse:
        """列出已有报告（日报/周报/月报/年报）"""
        try:
            from devpartner_agent.services.vault_exporter import get_vault_exporter
            exporter = get_vault_exporter()

            def scan_dir(directory, report_type):
                items = []
                if directory.exists():
                    for f in sorted(directory.glob("*.md"), reverse=True):
                        stat = f.stat()
                        # 读取第一行作为标题
                        title = f.stem
                        try:
                            first_line = f.read_text(encoding="utf-8").split("\n")[0]
                            if first_line.startswith("# "):
                                title = first_line[2:].strip()
                        except Exception:
                            pass
                        items.append({
                            "name": f.stem,
                            "title": title,
                            "file": f.name,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "path": str(f),
                        })
                return items

            daily = scan_dir(exporter._calendar_dir, "daily")
            weekly = scan_dir(exporter._reports_dir / "Weekly", "weekly")
            monthly = scan_dir(exporter._reports_dir / "Monthly", "monthly")
            annual = scan_dir(exporter._reports_dir / "Annual", "annual")

            return JSONResponse(content={
                "success": True,
                "daily": daily,
                "weekly": weekly,
                "monthly": monthly,
                "annual": annual,
                "totals": {
                    "daily": len(daily),
                    "weekly": len(weekly),
                    "monthly": len(monthly),
                    "annual": len(annual),
                },
            })
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/reports/read", methods=["GET"])
    async def api_reports_read(request: Request) -> JSONResponse:
        """读取指定报告文件内容"""
        try:
            report_type = request.query_params.get("type", "daily")  # daily|weekly|monthly|annual
            name = request.query_params.get("name", "")  # 文件名（不含 .md）

            if not name:
                return JSONResponse(
                    content={"success": False, "error": "缺少 name 参数"},
                    status_code=400,
                )

            from devpartner_agent.services.vault_exporter import get_vault_exporter
            exporter = get_vault_exporter()

            type_dir_map = {
                "daily": exporter._calendar_dir,
                "weekly": exporter._reports_dir / "Weekly",
                "monthly": exporter._reports_dir / "Monthly",
                "annual": exporter._reports_dir / "Annual",
            }
            target_dir = type_dir_map.get(report_type)
            if not target_dir:
                return JSONResponse(
                    content={"success": False, "error": f"未知报告类型: {report_type}"},
                    status_code=400,
                )

            file_path = target_dir / f"{name}.md"
            if not file_path.exists():
                return JSONResponse(
                    content={"success": False, "error": f"报告不存在: {name}.md"},
                    status_code=404,
                )

            content = file_path.read_text(encoding="utf-8")
            return JSONResponse(content={
                "success": True,
                "name": name,
                "type": report_type,
                "content": content,
                "size": file_path.stat().st_size,
            })
        except Exception as e:
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Daily Engine API（日报引擎内部服务）
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/daily/summary", methods=["GET"])
    async def api_daily_summary(request: Request) -> JSONResponse:
        """每日工作总结"""
        try:
            date = request.query_params.get("date", "")
            from devpartner_agent.core.daily_engine import get_daily_engine
            engine = get_daily_engine()
            result = engine.get_daily_summary(date)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/daily/work-data", methods=["GET"])
    async def api_daily_work_data(request: Request) -> JSONResponse:
        """工作原始数据"""
        try:
            date = request.query_params.get("date", "")
            fallback = request.query_params.get("fallback_to_log", "true") == "true"
            from devpartner_agent.core.daily_engine import get_daily_engine
            engine = get_daily_engine()
            result = engine.get_daily_work_data(date, fallback)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/daily/analysis", methods=["POST"])
    async def api_save_analysis(request: Request) -> JSONResponse:
        """保存每日分析结果"""
        try:
            body = await request.json()
            analysis_json = json.dumps(body, ensure_ascii=False)
            from devpartner_agent.core.daily_engine import get_daily_engine
            engine = get_daily_engine()
            result = engine.save_daily_analysis(analysis_json)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/daily/weekly-data", methods=["GET"])
    async def api_weekly_data(request: Request) -> JSONResponse:
        """最近7天工作数据概览"""
        try:
            from devpartner_agent.core.daily_engine import get_daily_engine
            engine = get_daily_engine()
            result = engine.get_weekly_work_data()
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Knowledge Engine API（知识引擎内部服务）
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/knowledge/list", methods=["GET"])
    async def api_knowledge_list(request: Request) -> JSONResponse:
        """知识点列表"""
        try:
            domain = request.query_params.get("domain", "")
            category = request.query_params.get("category", "")
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
            from devpartner_agent.core.knowledge_engine import get_knowledge_engine
            engine = get_knowledge_engine()
            result = engine.list_points(domain, category, limit, offset)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/knowledge/search", methods=["GET"])
    async def api_knowledge_search(request: Request) -> JSONResponse:
        """搜索知识点"""
        try:
            query = request.query_params.get("query", "")
            domain = request.query_params.get("domain", "")
            limit = int(request.query_params.get("limit", 20))
            from devpartner_agent.core.knowledge_engine import get_knowledge_engine
            engine = get_knowledge_engine()
            result = engine.search(query, domain, limit)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/knowledge/create", methods=["POST"])
    async def api_knowledge_create(request: Request) -> JSONResponse:
        """创建知识点"""
        try:
            body = await request.json()
            from devpartner_agent.core.knowledge_engine import get_knowledge_engine
            engine = get_knowledge_engine()
            result = engine.create_point(
                title=body.get("title", ""),
                content=body.get("content", ""),
                domain=body.get("domain", ""),
                category=body.get("category", "concept"),
                tags_json=json.dumps(body.get("tags", [])),
                difficulty=body.get("difficulty", "medium"),
                confidence=body.get("confidence", 0.8),
            )
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/knowledge/match", methods=["POST"])
    async def api_knowledge_match(request: Request) -> JSONResponse:
        """LLM 分析用户查询 → 匹配领域 → 模糊搜索知识库"""
        try:
            body = await request.json()
            query = body.get("query", "").strip()
            if not query:
                return JSONResponse(content={"success": False, "error": "查询内容不能为空"}, status_code=400)

            from devpartner_agent.core.database import get_db
            from devpartner_agent.core.llm_engine import get_llm_engine
            from prompts import run_analysis, AnalysisTask, parse_json

            db = get_db()

            # Step 1: 获取所有 domain
            domains_rows = db.query_local(
                """SELECT DISTINCT domain FROM knowledge_points ORDER BY domain"""
            )
            domains = [r["domain"] for r in (domains_rows or []) if r.get("domain")]

            # Step 2: LLM 分析查询 → 匹配最可能的 domain
            matched_domain = ""
            match_reason = ""
            if domains and len(domains) >= 2:
                llm = get_llm_engine()
                if llm.is_available():
                    domains_list = ", ".join(domains)
                    task = AnalysisTask(
                        name="knowledge_match",
                        description="LLM 分析用户查询匹配知识领域",
                        prompt_template="""分析以下用户查询，判断它最可能属于哪个知识领域。

可用领域: {domains_list}

用户查询: "{query}"

返回 JSON:
{{"domain": "匹配的领域（必须从可用领域中选一个）", "reason": "匹配原因（一句话）"}}

如果查询与所有领域都不相关，domain 返回 "general"。
""",
                        max_tokens=128,
                        input_truncate=2000,
                    )
                    result = run_analysis(task, domains_list=domains_list, query=query)
                    if result and result.get("domain"):
                        matched_domain = result.get("domain", "")
                        match_reason = result.get("reason", "")
            elif domains:
                matched_domain = domains[0]

            # Step 3: 模糊搜索（LIKE）+ 领域过滤
            search_term = f"%{query}%"
            if matched_domain and matched_domain != "general":
                rows = db.query_local(
                    """SELECT * FROM knowledge_points
                       WHERE domain = ? AND (title LIKE ? OR content LIKE ?)
                       ORDER BY confidence DESC, usage_count DESC
                       LIMIT 20""",
                    (matched_domain, search_term, search_term)
                )
            else:
                rows = db.query_local(
                    """SELECT * FROM knowledge_points
                       WHERE title LIKE ? OR content LIKE ?
                       ORDER BY confidence DESC, usage_count DESC
                       LIMIT 20""",
                    (search_term, search_term)
                )

            # 如果模糊搜索没结果，在匹配领域内返回该领域热门条目
            if not rows and matched_domain and matched_domain != "general":
                rows = db.query_local(
                    """SELECT * FROM knowledge_points
                       WHERE domain = ?
                       ORDER BY usage_count DESC, confidence DESC
                       LIMIT 10""",
                    (matched_domain,)
                )

            items = []
            for r in (rows or []):
                content = r.get("content", "")
                items.append({
                    "knowledge_id": r.get("knowledge_id", ""),
                    "title": r.get("title", ""),
                    "summary": content[:200] + "..." if len(content) > 200 else content,
                    "domain": r.get("domain", ""),
                    "category": r.get("category", ""),
                    "difficulty": r.get("difficulty", "medium"),
                    "usage_count": r.get("usage_count", 0),
                    "confidence": r.get("confidence", 0),
                    "created_at": r.get("created_at", ""),
                })

            return JSONResponse(content={
                "success": True,
                "query": query,
                "matched_domain": matched_domain,
                "match_reason": match_reason,
                "domains_available": domains,
                "count": len(items),
                "items": items,
            })
        except Exception as e:
            logger.error(f"/api/knowledge/match 异常: {e}")
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/knowledge/get", methods=["GET"])
    async def api_knowledge_get(request: Request) -> JSONResponse:
        """获取单个知识点详情"""
        try:
            knowledge_id = request.query_params.get("id", "")
            from devpartner_agent.core.knowledge_engine import get_knowledge_engine
            engine = get_knowledge_engine()
            result = engine.get_point(knowledge_id)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from devpartner_agent.core.llm_engine import (
                is_intercept_enabled, get_intercept_logs
            )
            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": enabled,
                "log_count": len(logs),
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from devpartner_agent.core.llm_engine import (
                set_intercept_enabled, clear_intercept_logs, is_intercept_enabled
            )
            body = await request.json() if request.headers.get("content-length") else {}
            enable = body.get("enable", None)
            clear = body.get("clear", False)

            if clear:
                clear_intercept_logs()

            if enable is None:
                # 翻转当前状态
                new_state = set_intercept_enabled(not is_intercept_enabled())
            else:
                new_state = set_intercept_enabled(bool(enable))

            return JSONResponse(content={
                "enabled": new_state,
                "message": f"拦截器已{'开启' if new_state else '关闭'}",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from devpartner_agent.core.llm_engine import (
                get_intercept_logs, is_intercept_enabled
            )
            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(content={
                "enabled": is_intercept_enabled(),
                "count": len(logs),
                "logs": logs[:limit],
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=500)