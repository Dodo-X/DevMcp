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
import logging
import os as _os
from datetime import datetime
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)


def _cascade_cancel_finalize_tasks(tq, dry_run: bool = False) -> dict:
    """级联取消：找出所有 step 失败的 conversation，取消其 conversation_finalize 任务。

    逻辑：
    1. 扫描内存中所有 FAILED/DEAD 的 step_analysis 任务
    2. 找到它们对应的 conversation_id
    3. 扫描这些 conversation 的 conversation_finalize（PENDING/QUEUED）并取消
    """
    # 收集有失败 step 的 conversation_id
    failed_convs = set()
    for _, meta in list(tq._task_map.items()):
        task_type = meta.get("task_type", "")
        status = meta.get("status", "")
        if task_type == "step_analysis" and status in ["failed", "dead"]:
            conv_id = meta.get("payload", {}).get("conversation_id", "")
            if conv_id:
                failed_convs.add(conv_id)

    cascade_cancelled = {}
    for conv_id in failed_convs:
        for tid, meta in list(tq._task_map.items()):
            task_type = meta.get("task_type", "")
            status = meta.get("status", "")
            payload_conv = meta.get("payload", {}).get("conversation_id", "")
            if (
                task_type == "conversation_finalize"
                and payload_conv == conv_id
                and status in ["pending", "queued"]
            ) and (dry_run or tq.cancel_task(tid)):
                cascade_cancelled.setdefault(conv_id, []).append(tid)

    total = sum(len(v) for v in cascade_cancelled.values())
    return {
        "failed_conversations": len(failed_convs),
        "cancelled_finalize_tasks": total,
        "details": dict(cascade_cancelled.items()) if cascade_cancelled else {},
        "dry_run": dry_run,
    }


def register_rest_routes(mcp):
    """注册所有 HTTP 路由到 MCP 实例"""

    from foundation.config.app_settings import get_project_version

    VERSION = get_project_version()

    # ── 根路径 ──
    @mcp.custom_route("/", methods=["GET", "HEAD"])
    async def root_endpoint(request: Request):
        return JSONResponse(
            {
                "service": "DevPartner v7.5",
                "version": VERSION,
                "protocol": "MCP Streamable HTTP",
                "mcp_endpoint": "/mcp",
                "health": "/health",
                "status": "running",
            }
        )

    # ── Dashboard ──
    @mcp.custom_route("/dashboard", methods=["GET"])
    async def dashboard_endpoint(request: Request):
        """返回运维面板 HTML 页面"""
        dashboard_path = Path(__file__).resolve().parent / "dashboard.html"
        if dashboard_path.exists():
            content = dashboard_path.read_text(encoding="utf-8")
            content = content.replace("{{VERSION}}", VERSION)
            return HTMLResponse(content=content)
        # 降级：返回 JSON 导航
        return JSONResponse(
            {
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
                },
            }
        )

    # ── 健康检查 ──
    @mcp.custom_route("/health", methods=["GET", "HEAD"])
    async def health_endpoint(request: Request):
        return JSONResponse({"status": "healthy", "version": VERSION})

    # ── MCP 端点健康检查 ──
    @mcp.custom_route("/mcp", methods=["GET"])
    async def mcp_health_check(request: Request) -> JSONResponse:
        try:
            from backend.core.llm_kernel.base_client import get_llm_engine

            llm = get_llm_engine()
            llm_available = llm.is_available() if llm else False
        except Exception:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            llm_available = False
        return JSONResponse(
            {
                "status": "ok",
                "server": "devpartner",
                "version": VERSION,
                "protocol": "MCP Streamable HTTP (POST /mcp)",
                "health": "/health",
                "llm_available": llm_available,
            }
        )

    # ════════════════════════════════════════════════
    # Growth Analytics API
    # ════════════════════════════════════════════════
    from backend.business.analytics.growth_analytics import (
        get_learning_timeline,
        get_user_activity_heatmap,
        get_user_growth_overview,
        get_user_skill_radar,
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
            from backend.core.database.base_conn import get_db

            db = get_db()
            today = _dt_date.today().isoformat()

            active = db.query_local(
                "SELECT COUNT(DISTINCT conversation_id) as cnt FROM conversations "
                "WHERE timestamp >= datetime('now', '-1 day')"
            )
            active_sessions = active[0]["cnt"] if active else 0

            today_new = db.query_local(
                "SELECT COUNT(DISTINCT conversation_id) as cnt FROM conversations "
                "WHERE date(timestamp) = ?",
                (today,),
            )
            today_sessions = today_new[0]["cnt"] if today_new else 0

            pending_tasks = running_tasks = completed_tasks = 0
            try:
                from backend.core.task_queue_kernel.queue_client import get_task_queue

                tq = get_task_queue()
                ts = tq.get_queue_stats()
                pending_tasks = ts.get("pending_tasks", 0)
                running_tasks = ts.get("running_tasks", 0)
                completed_tasks = ts.get("total_completed", 0)
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            kb_size = 0
            try:
                kb = db.query_local("SELECT COUNT(*) as cnt FROM knowledge_points")
                kb_size = kb[0]["cnt"] if kb else 0
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            today_knowledge = 0
            try:
                kt = db.query_local(
                    "SELECT COUNT(*) as cnt FROM knowledge_points WHERE date(created_at) = ?",
                    (today,),
                )
                today_knowledge = kt[0]["cnt"] if kt else 0
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            callback_registrations = callback_triggers = 0
            try:
                from backend.core.task_queue_kernel.callback_registry import get_callback_registry

                cr = get_callback_registry()
                cs = cr.get_stats()
                callback_registrations = cs.get("total_registrations", 0)
                callback_triggers = cs.get("total_triggered", 0)
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
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
                    pending_analyses_details.append(
                        {
                            "type": pa.get("analysis_type", ""),
                            "date": pa.get("source_date", ""),
                            "missing_dimensions": pa.get("missing_dimensions", "[]"),
                            "created_at": pa.get("created_at", ""),
                        }
                    )
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            return JSONResponse(
                content={
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
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/notifications", methods=["GET"])
    async def api_notifications(request: Request) -> JSONResponse:
        """通知中心：聚合 pending analyses / 失败任务 / 待审核建议"""
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            notifications = []

            # 1. Pending analyses
            try:
                pa = db.query_local(
                    "SELECT analysis_type, source_date, missing_dimensions, status, created_at "
                    "FROM pending_analyses WHERE status = 'pending' ORDER BY created_at ASC LIMIT 20"
                )
                for r in pa or []:
                    notifications.append(
                        {
                            "id": f"pa-{r['analysis_type']}-{r['source_date']}",
                            "type": "analysis",
                            "level": "warning",
                            "title": f"待分析: {r['analysis_type']} ({r['source_date']})",
                            "detail": f"缺失维度: {r.get('missing_dimensions', 'N/A')}",
                            "time": r.get("created_at", ""),
                        }
                    )
            except Exception:
                logger.warning("api_notifications: 查询 pending_analyses 失败", exc_info=True)

            # 2. Failed / stalled tasks
            try:
                tq_rows = db.query_local(
                    "SELECT task_id, status, queued_at, error_message "
                    "FROM task_queue WHERE status IN ('failed', 'cancelled') "
                    "ORDER BY queued_at DESC LIMIT 10"
                )
                for r in tq_rows or []:
                    notifications.append(
                        {
                            "id": f"tq-{r['task_id']}",
                            "type": "task",
                            "level": "error",
                            "title": f"任务异常: {r['task_id'][:12]}",
                            "detail": r.get("error_message", f"状态: {r.get('status', '')}"),
                            "time": r.get("queued_at", ""),
                        }
                    )
            except Exception:
                logger.warning("api_notifications: 查询 task_queue 失败", exc_info=True)

            # 按时间倒序排列, 最多 30 条
            notifications.sort(key=lambda x: x.get("time", ""), reverse=True)
            total = len(notifications)
            notifications = notifications[:30]

            return JSONResponse(
                content={
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "total": total,
                        "items": notifications,
                        "summary": {
                            "analysis": sum(1 for n in notifications if n["type"] == "analysis"),
                            "task_error": sum(1 for n in notifications if n["type"] == "task"),
                            "growth_pending": sum(
                                1 for n in notifications if n["type"] == "growth"
                            ),
                        },
                    },
                }
            )
        except Exception as e:
            logger.warning("api_notifications: 未预期的异常", exc_info=True)
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 设置 API
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/settings", methods=["GET"])
    async def api_settings_get(request: Request) -> JSONResponse:
        """读取所有设置"""
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            rows = db.query_local("SELECT key, value, updated_at FROM settings ORDER BY key")
            settings = {r["key"]: r["value"] for r in (rows or [])}
            return JSONResponse(content={"code": 0, "message": "ok", "data": settings})
        except Exception as e:
            logger.warning("api_settings_get 失败", exc_info=True)
            return JSONResponse(
                content={"code": -1, "message": str(e), "data": {}}, status_code=500
            )

    @mcp.custom_route("/api/settings", methods=["POST"])
    async def api_settings_update(request: Request) -> JSONResponse:
        """写入一个或多个设置项"""
        try:
            from backend.core.database.base_conn import get_db

            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse(
                    content={"code": -1, "message": "请求体应为 JSON 字典"}, status_code=400
                )

            db = get_db()
            updated = {}
            allowed = {"model_name", "ollama_host", "auto_refresh", "refresh_interval", "language"}
            for k, v in body.items():
                if k not in allowed:
                    continue
                db.query_local(
                    "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                    (k, str(v)),
                )
                updated[k] = str(v)

            return JSONResponse(content={"code": 0, "message": "ok", "data": {"updated": updated}})
        except Exception as e:
            logger.warning("api_settings_update 失败", exc_info=True)
            return JSONResponse(
                content={"code": -1, "message": str(e), "data": {}}, status_code=500
            )

    # ════════════════════════════════════════════════
    # 请求拦截调试 API (v9.5.1)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/debug/intercept/status", methods=["GET"])
    async def api_intercept_status(request: Request) -> JSONResponse:
        """获取拦截器状态（开关 + 日志数）"""
        try:
            from backend.core.llm_kernel.llm_utils import get_intercept_logs, is_intercept_enabled

            enabled = is_intercept_enabled()
            logs = get_intercept_logs()
            return JSONResponse(
                content={
                    "enabled": enabled,
                    "log_count": len(logs),
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/toggle", methods=["POST"])
    async def api_intercept_toggle(request: Request) -> JSONResponse:
        """切换拦截器开关"""
        try:
            from backend.core.llm_kernel.llm_utils import (
                clear_intercept_logs,
                is_intercept_enabled,
                set_intercept_enabled,
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

            return JSONResponse(
                content={
                    "enabled": new_state,
                    "message": f"拦截器已{'开启' if new_state else '关闭'}",
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/debug/intercept/logs", methods=["GET"])
    async def api_intercept_logs(request: Request) -> JSONResponse:
        """获取拦截日志列表"""
        try:
            from backend.core.llm_kernel.llm_utils import get_intercept_logs, is_intercept_enabled

            limit = int(request.query_params.get("limit", "50"))
            logs = get_intercept_logs()
            return JSONResponse(
                content={
                    "enabled": is_intercept_enabled(),
                    "count": len(logs),
                    "logs": logs[:limit],
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/pending-analyses/process", methods=["POST"])
    async def api_process_pending_analyses(request: Request) -> JSONResponse:
        """手动触发待分析数据清算（v8.0）"""
        try:
            from backend.business.task_handlers.daily_summary import process_pending_analyses

            result = process_pending_analyses()
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Task Ops API (v8.1 — 运维监管)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/tasks/diagnostics", methods=["GET"])
    async def api_tasks_diagnostics(request: Request) -> JSONResponse:
        """任务队列深度诊断（阶段锁、并发槽位、运行中任务详情）"""
        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            diag = tq.get_diagnostics()
            return JSONResponse(content=diag)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Ollama 管理 API (v8.3)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/ollama/status", methods=["GET"])
    async def api_ollama_status(request: Request) -> JSONResponse:
        """获取 Ollama 服务详细状态和启动日志"""
        try:
            from backend.core import bootstrap
            from backend.core.llm_kernel.base_client import get_llm_engine

            llm = get_llm_engine()
            llm_status = llm.get_status() if llm else {}
            logs = bootstrap.get_ollama_logs()

            ollama_url = _os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

            model_name = ""
            try:
                from foundation.config.app_settings import get_config

                cfg = get_config()
                model_name = (
                    getattr(cfg.llm, "ollama_model", "qwen3") if hasattr(cfg, "llm") else "qwen3"
                )
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                model_name = "qwen3"

            return JSONResponse(
                content={
                    "available": llm_status.get("available", False),
                    "enabled": llm_status.get("enabled", False),
                    "ollama_url": ollama_url,
                    "model_name": model_name,
                    "inference_count": llm_status.get("inference_count", 0),
                    "avg_tokens_per_second": llm_status.get("avg_tokens_per_second", 0),
                    "load_error": llm_status.get("load_error"),
                    "logs": logs,
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 用户画像 API
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/profile", methods=["GET"])
    async def api_profile(request: Request) -> JSONResponse:
        """开发者画像与能力模型"""
        try:
            from backend.business.analytics.profiling import compute_portrait
            from backend.core.database.base_conn import get_db

            db = get_db()
            cur = db.get_raw_cursor()
            portrait = compute_portrait(cur)

            return JSONResponse(
                content={
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "profile": portrait.get("profile", []),
                        "skills": portrait.get("skills", []),
                        "plans": portrait.get("plans", []),
                        "momentum": portrait.get("momentum", 0),
                        "portrait_conf": portrait.get("portrait_conf"),
                    },
                }
            )
        except Exception as e:
            logger.warning("api_profile 失败", exc_info=True)
            return JSONResponse(
                content={"code": -1, "message": str(e), "data": {}}, status_code=500
            )

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

            from backend.core.database.base_conn import get_db

            db = get_db()

            if source_period:
                rows = db.get_growth_analysis_by_period(source_period)
            elif status_filter == "pending":
                rows = db.get_pending_growth_analysis(limit=limit)
            else:
                rows = db.query_local(
                    "SELECT * FROM growth_analysis WHERE status = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (status_filter, limit),
                )

            result = []
            for r in rows or []:
                result.append(
                    {
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
                    }
                )

            return JSONResponse(content={"total": len(result), "items": result})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # 知识图谱 API
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/knowledge/graph", methods=["GET"])
    async def api_knowledge_graph(request: Request) -> JSONResponse:
        """知识图谱数据（节点 + 边）"""
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            rows = db.query_local(
                "SELECT domain, category, COUNT(*) as cnt, "
                "AVG(confidence) as avg_conf, SUM(usage_count) as total_use "
                "FROM knowledge_points GROUP BY domain, category ORDER BY cnt DESC LIMIT 80"
            )

            nodes = []
            edges = []
            node_map = {}
            for r in rows or []:
                node_id = f"{r['domain']}|{r['category']}"
                node_map[node_id] = len(nodes)
                nodes.append(
                    {
                        "id": node_id,
                        "domain": r["domain"],
                        "category": r["category"],
                        "count": r["cnt"],
                        "confidence": round(r["avg_conf"] or 0, 2),
                        "usage": r["total_use"] or 0,
                    }
                )

            # 同一 domain 下的 category 之间建边
            domain_groups = {}
            for n in nodes:
                domain_groups.setdefault(n["domain"], []).append(n["id"])
            for ids in domain_groups.values():
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        edges.append({"source": ids[i], "target": ids[j], "weight": 1})

            return JSONResponse(
                content={"code": 0, "message": "ok", "data": {"nodes": nodes, "edges": edges}}
            )
        except Exception as e:
            logger.warning("api_knowledge_graph 失败", exc_info=True)
            return JSONResponse(
                content={"code": -1, "message": str(e), "data": {}}, status_code=500
            )

    # ════════════════════════════════════════════════
    # Projects Knowledge API
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/projects/list", methods=["GET"])
    async def api_projects_list(request: Request) -> JSONResponse:
        """
        v8.5.8: 项目列表 = 通过 MCP 对接的 CodeBuddy/Trae 等客户端的项目名
        数据源: connected_systems 表（display_name / system_id 作为项目名；
                project_path 已在 v10 整改中删除，不再引用）
        回退: 如无数据，取当前工作目录名
        """
        try:
            import os as _os

            from backend.core.database.base_conn import get_db

            db = get_db()
            projects = []

            # 主数据源: connected_systems 表 — 对接的真实项目
            try:
                rows = db.query_local(
                    """SELECT system_id, display_name, system_type
                       FROM connected_systems ORDER BY last_active DESC"""
                )
                for r in rows or []:
                    # 项目名优先用 display_name，否则回退 system_id（已删除 project_path）
                    proj_name = r.get("display_name", "") or r.get("system_id", "")
                    if proj_name and proj_name not in [p["name"] for p in projects]:
                        projects.append(
                            {
                                "name": proj_name,
                                "path": r.get("system_id", ""),
                                "system_id": r.get("system_id", ""),
                                "system_type": r.get("system_type", ""),
                            }
                        )
            except Exception:
                logger.warning(
                    "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            # 回退: 如果 connected_systems 为空，用当前工作目录名
            if not projects:
                cwd = _os.getcwd()
                fallback_name = _os.path.basename(cwd.rstrip("/\\"))
                projects = [
                    {
                        "name": fallback_name,
                        "path": cwd,
                        "system_id": fallback_name,
                        "system_type": "",
                    }
                ]

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
                return JSONResponse(
                    content={"success": False, "error": "请求体为空", "results": []}
                )
            body = _json.loads(raw_body)
            question = (body.get("question") or "").strip()
            project_name = (body.get("project_name") or "").strip()
            category = (body.get("category") or "").strip()
            limit = min(body.get("limit", 10) or 10, 50)

            from backend.core.database.base_conn import get_db

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

            rows = (
                db.query_local(sql, tuple(params))
                if params
                else db.query_local(sql.replace("WHERE 1=1", "").replace("WHERE 1=1", ""))
            )

            results = []
            for row in rows or []:
                tags = row.get("tags", "[]")
                if isinstance(tags, str):
                    try:
                        tags = _json.loads(tags)
                    except Exception:
                        logger.warning(
                            "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）",
                            exc_info=True,
                        )
                        tags = [tags]
                content = row.get("content") or ""
                results.append(
                    {
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
                    }
                )

            return JSONResponse(
                content={
                    "success": True,
                    "question": question,
                    "project_name": project_name,
                    "category_filter": category,
                    "total": len(results),
                    "results": results,
                }
            )
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
            from backend.business.system_ops.system_engine import get_system_engine

            engine = get_system_engine()
            result = engine.check_data_integrity()
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
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

            from backend.business.task_handlers.daily_summary import (
                generate_annual_report,
                generate_monthly_report,
                generate_weekly_report,
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
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
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

            from backend.business.task_handlers.daily_summary import generate_daily_summary
            from backend.business.vault_export.vault_exporter import get_vault_exporter

            exporter = get_vault_exporter()
            target_file = exporter._calendar_dir / f"{date_str}.md"

            if target_file.exists() and not force_overwrite:
                return JSONResponse(
                    content={
                        "success": True,
                        "method": "skipped",
                        "file_path": str(target_file),
                        "note": f"日报已存在: {date_str}.md（勾选覆盖可重新生成）",
                    }
                )

            result = generate_daily_summary(date_str)

            # v9.3.3: 字段映射 + MD 导出，对齐前端 method 字段和周/月/年报行为
            method = result.get("analysis_method", "unknown")
            file_path = None

            if method == "llm":
                # LLM 分析成功 → 导出 MD 日报
                try:
                    from backend.business.vault_export.vault_exporter import get_vault_exporter

                    exporter = get_vault_exporter()
                    file_path = str(exporter.export_daily_report(date_str, result))
                    if file_path:
                        logger.info(f"📅 日报已导出到 Calendar: {file_path}")
                except Exception as export_err:
                    logger.warning(f"⚠️ 日报 MD 导出失败: {export_err}")

            # v9.8.2: 画像/系统合并已移除 — 由 finalize 子任务实时处理，不需要每日二次合并

            return JSONResponse(
                content={
                    "success": result.get("success", True),
                    "method": method,
                    "file_path": file_path,
                    "date": result.get("date", date_str),
                    "summary": result.get("summary", {}),
                    "raw_data": result.get("raw_data"),
                    "note": result.get("note", ""),
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/reports/list", methods=["GET"])
    async def api_reports_list(request: Request) -> JSONResponse:
        """列出已有报告（日报/周报/月报/年报）"""
        try:
            from backend.business.vault_export.vault_exporter import get_vault_exporter

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
                            logger.warning(
                                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）",
                                exc_info=True,
                            )
                            pass
                        items.append(
                            {
                                "name": f.stem,
                                "title": title,
                                "file": f.name,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "path": str(f),
                            }
                        )
                return items

            daily = scan_dir(exporter._calendar_dir, "daily")
            weekly = scan_dir(exporter._reports_dir / "Weekly", "weekly")
            monthly = scan_dir(exporter._reports_dir / "Monthly", "monthly")
            annual = scan_dir(exporter._reports_dir / "Annual", "annual")

            return JSONResponse(
                content={
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
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
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

            from backend.business.vault_export.vault_exporter import get_vault_exporter

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
            return JSONResponse(
                content={
                    "success": True,
                    "name": name,
                    "type": report_type,
                    "content": content,
                    "size": file_path.stat().st_size,
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/reports/search", methods=["GET"])
    async def api_reports_search(request: Request) -> JSONResponse:
        """跨报告全文搜索（标题 + 内容包含关键词）"""
        try:
            q = (request.query_params.get("q", "") or "").strip()
            if not q:
                return JSONResponse(
                    content={"success": False, "error": "缺少 q 参数"}, status_code=400
                )

            from backend.business.vault_export.vault_exporter import get_vault_exporter

            exporter = get_vault_exporter()
            buckets = [
                ("daily", exporter._calendar_dir),
                ("weekly", exporter._reports_dir / "Weekly"),
                ("monthly", exporter._reports_dir / "Monthly"),
                ("annual", exporter._reports_dir / "Annual"),
            ]

            results = []
            ql = q.lower()
            for rtype, directory in buckets:
                if not directory.exists():
                    continue
                for f in sorted(directory.glob("*.md")):
                    try:
                        text = f.read_text(encoding="utf-8")
                    except Exception:
                        logger.warning(
                            "api_reports_search: 读取报告失败（P-17 收口）", exc_info=True
                        )
                        continue
                    if ql not in text.lower():
                        continue
                    # 提取首个匹配行作为摘要
                    snippet = ""
                    for line in text.splitlines():
                        if ql in line.lower():
                            snippet = line.strip()[:120]
                            break
                    title = f.stem
                    first = text.split("\n", 1)[0]
                    if first.startswith("# "):
                        title = first[2:].strip()
                    results.append(
                        {
                            "type": rtype,
                            "name": f.stem,
                            "title": title,
                            "snippet": snippet,
                            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                        }
                    )
                    if len(results) >= 50:
                        break
                if len(results) >= 50:
                    break

            return JSONResponse(
                content={"success": True, "query": q, "count": len(results), "results": results}
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: /api/reports/search 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/export/report", methods=["GET"])
    async def api_export_report(request: Request) -> Response:
        """下载报告 Markdown 文件"""
        try:
            report_type = request.query_params.get("type", "daily")
            name = request.query_params.get("name", "")
            if not name:
                return JSONResponse(
                    content={"success": False, "error": "缺少 name 参数"}, status_code=400
                )

            from backend.business.vault_export.vault_exporter import get_vault_exporter

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
            # 防目录穿越：规范化后必须仍在目标目录内
            file_path = (target_dir / f"{name}.md").resolve()
            if not str(file_path).startswith(str(target_dir.resolve())) or not file_path.exists():
                return JSONResponse(
                    content={"success": False, "error": f"报告不存在: {name}.md"},
                    status_code=404,
                )

            from starlette.responses import FileResponse

            return FileResponse(
                path=str(file_path),
                media_type="text/markdown",
                filename=f"{name}.md",
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: /api/export/report 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Daily Engine API（日报引擎内部服务）
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/daily/summary", methods=["GET"])
    async def api_daily_summary(request: Request) -> JSONResponse:
        """每日工作总结"""
        try:
            date = request.query_params.get("date", "")
            from backend.business.task_handlers.daily_summary import generate_daily_summary

            result = generate_daily_summary(date)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
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
            from backend.business.knowledge_extractor.knowledge_engine import get_knowledge_engine

            engine = get_knowledge_engine()
            result = engine.list_points(domain, category, limit, offset)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Knowledge Search & Match API
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/knowledge/search", methods=["GET"])
    async def api_knowledge_search(request: Request) -> JSONResponse:
        """搜索知识点"""
        try:
            query = request.query_params.get("query", "")
            limit = int(request.query_params.get("limit", 50))
            from backend.core.database.base_conn import get_db

            db = get_db()
            rows = db.query_local(
                "SELECT * FROM knowledge_points WHERE title LIKE ? OR content LIKE ? "
                "ORDER BY usage_count DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            )
            items = []
            for r in rows or []:
                content = r.get("content", "")
                items.append(
                    {
                        "knowledge_id": r.get("knowledge_id", ""),
                        "title": r.get("title", ""),
                        "summary": content[:200] + "..." if len(content) > 200 else content,
                        "domain": r.get("domain", ""),
                        "category": r.get("category", ""),
                        "difficulty": r.get("difficulty", "medium"),
                        "usage_count": r.get("usage_count", 0),
                        "confidence": r.get("confidence", 0),
                        "created_at": r.get("created_at", ""),
                    }
                )
            return JSONResponse(
                content={"success": True, "data": {"items": items, "total": len(items)}}
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/knowledge/match", methods=["POST"])
    async def api_knowledge_match(request: Request) -> JSONResponse:
        """AI 匹配知识点"""
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            query = (body.get("query") or "").strip()
            if not query:
                return JSONResponse(content={"error": "缺少 query 参数"}, status_code=400)
            from backend.business.knowledge_extractor.knowledge_engine import get_knowledge_engine

            engine = get_knowledge_engine()
            result = engine.match_knowledge(query)
            # 前端直接使用 d.matched_domain / d.count / d.items，扁平化返回
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/knowledge/get", methods=["GET"])
    async def api_knowledge_get(request: Request) -> JSONResponse:
        """获取单个知识点详情"""
        try:
            knowledge_id = request.query_params.get("id", "")
            from backend.business.knowledge_extractor.knowledge_engine import get_knowledge_engine

            engine = get_knowledge_engine()
            result = engine.get_point(knowledge_id)
            return JSONResponse(content={"success": True, "data": result})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Task Queue Management API
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/tasks/list", methods=["GET"])
    async def api_tasks_list(request: Request) -> JSONResponse:
        """任务队列列表"""
        try:
            limit = int(request.query_params.get("limit", 20))
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            tasks = tq.list_tasks(limit=limit)
            return JSONResponse(content=[dict(t) for t in tasks])
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/stats", methods=["GET"])
    async def api_tasks_stats(request: Request) -> JSONResponse:
        """任务统计"""
        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            stats = tq.get_queue_stats()
            return JSONResponse(content=stats)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/cancel", methods=["POST"])
    async def api_tasks_cancel(request: Request) -> JSONResponse:
        """取消任务"""
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            task_id = body.get("task_id", "")
            if not task_id:
                return JSONResponse(content={"error": "缺少 task_id"}, status_code=400)
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            result = tq.cancel_task(task_id)
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/retry", methods=["POST"])
    async def api_tasks_retry(request: Request) -> JSONResponse:
        """手动重试失败任务"""
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            task_id = body.get("task_id", "")
            if not task_id:
                return JSONResponse(content={"error": "缺少 task_id"}, status_code=400)
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            result = tq.retry_task(task_id)
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/handlers", methods=["GET"])
    async def api_tasks_handlers(request: Request) -> JSONResponse:
        """已注册的 handler 列表"""
        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            handlers = tq.get_handlers()
            return JSONResponse(content={"total": len(handlers), "handlers": handlers})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/recover", methods=["POST"])
    async def api_tasks_recover(request: Request) -> JSONResponse:
        """v9.5.4: 手动从 DB 恢复 pending 任务到内存队列。

        用于修复启动时序 bug 导致的 pending 任务积压问题，
        无需重启服务即可触发恢复。
        """
        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            recovered = tq.recover_pending_tasks()
            stats = tq.get_queue_stats()
            return JSONResponse(
                content={
                    "success": True,
                    "recovered": recovered,
                    "pending_tasks": stats.get("pending_tasks", 0),
                    "running_tasks": stats.get("running_tasks", 0),
                    "total_completed": stats.get("total_completed", 0),
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/progress", methods=["GET"])
    async def api_tasks_progress(request: Request) -> JSONResponse:
        """运行中任务的进度"""
        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            tasks = tq.get_running_tasks_with_progress()
            return JSONResponse(content={"tasks": tasks})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/job-status", methods=["GET"])
    async def api_tasks_job_status(request: Request) -> JSONResponse:
        """查询任务状态"""
        try:
            task_id = request.query_params.get("task_id", "")
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            status = tq.get_task_status(task_id)
            return JSONResponse(content=status)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/tasks/progress/stream", methods=["GET"])
    async def api_tasks_progress_stream(request: Request) -> StreamingResponse:
        """SSE 推送任务队列进度（替代轮询）"""
        import asyncio

        async def event_stream():
            import json as _json

            from backend.core.database.base_conn import get_db
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            db = get_db()
            while True:
                try:
                    # 收集任务状态
                    stats = tq.get_queue_stats()
                    running = tq.get_running_tasks_with_progress()
                    # 收集 pending analyses
                    pa = db.query_local(
                        "SELECT COUNT(*) as cnt FROM pending_analyses WHERE status = 'pending'"
                    )
                    pending_analysis = (pa[0]["cnt"] if pa else 0) if pa else 0

                    data = {
                        "pending_tasks": stats.get("pending_tasks", 0),
                        "running_tasks": stats.get("running_tasks", 0),
                        "completed_tasks": stats.get("total_completed", 0),
                        "failed_tasks": stats.get("total_failed", 0),
                        "pending_analysis": pending_analysis,
                        "tasks": running,  # ← 新：运行中任务的阶段进度
                    }

                    yield f"data: {_json.dumps(data)}\n\n"
                except Exception:
                    yield f"data: {_json.dumps({})}\n\n"
                await asyncio.sleep(3)  # 每 3 秒推送（原 5 秒→加快刷新）

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @mcp.custom_route("/api/tasks/cleanup-pending", methods=["POST"])
    async def api_tasks_cleanup_pending(request: Request) -> JSONResponse:
        """批量清理指定时间范围内的 pending/queued 任务。

        请求体:
          - before_hours: float 清理多久之前的任务（默认 24 小时）
          - task_types: list 限定任务类型（可选，如 ["step_analysis", "conversation_finalize"]）
          - conversation_id: str 限定 conversation（可选）
          - dry_run: bool 是否只统计不执行（默认 false）
          - cascade: bool 是否级联取消（step 失败→取消对应的 conversation_finalize，默认 false）
        """
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            before_hours = float(body.get("before_hours", 24))
            task_types = body.get("task_types", None)
            conversation_id = body.get("conversation_id", None)
            dry_run = body.get("dry_run", False)
            cascade = body.get("cascade", False)

            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()

            # 级联模式：先找出所有 step_analysis 失败的 conversation，
            # 然后取消对应的 conversation_finalize 任务
            cascade_result = None
            if cascade:
                cascade_result = _cascade_cancel_finalize_tasks(tq, dry_run)

            result = tq.cleanup_pending_tasks(
                before_hours=before_hours,
                task_types=task_types,
                conversation_id=conversation_id,
                dry_run=dry_run,
            )
            if cascade_result:
                result["cascade"] = cascade_result
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # System Monitoring API
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/system/memory", methods=["GET"])
    async def api_system_memory(request: Request) -> JSONResponse:
        """系统内存使用"""
        try:
            import psutil

            process = psutil.Process()
            mem = process.memory_info()
            vm = psutil.virtual_memory()
            return JSONResponse(
                content={
                    "used_mb": round(mem.rss / 1024 / 1024, 1),
                    "total_mb": round(vm.total / 1024 / 1024, 1),
                    "percent": vm.percent,
                }
            )
        except ImportError:
            return JSONResponse(
                content={
                    "used_mb": 0,
                    "total_mb": 0,
                    "percent": 0,
                    "note": "psutil 未安装，内存信息不可用。运行 pip install psutil 安装。",
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/diagnose", methods=["GET"])
    async def api_system_diagnose(request: Request) -> JSONResponse:
        """系统诊断"""
        try:
            from backend.business.system_ops.system_engine import get_system_engine

            engine = get_system_engine()
            result = engine.system_diagnose()
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/health", methods=["GET"])
    async def api_system_health(request: Request) -> JSONResponse:
        """系统整体健康状态"""
        try:
            from backend.business.system_ops.system_engine import get_system_engine

            engine = get_system_engine()
            result = engine.get_system_health()
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/llm-status", methods=["GET", "POST"])
    async def api_llm_status(request: Request) -> JSONResponse:
        """LLM 服务状态查看或控制"""
        try:
            action = request.query_params.get("action", "status")
            from backend.business.system_ops.system_engine import get_system_engine

            engine = get_system_engine()
            result = engine.llm_status(action)
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/system/cleanup", methods=["POST"])
    async def api_system_cleanup(request: Request) -> JSONResponse:
        """数据清理"""
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            scope = body.get("scope", "all")
            dry_run = body.get("dry_run", False)
            from backend.business.system_ops.system_engine import get_system_engine

            engine = get_system_engine()
            result = engine.cleanup_data(scope=scope, dry_run=dry_run)
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Callbacks & Health API
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/callbacks/stats", methods=["GET"])
    async def api_callbacks_stats(request: Request) -> JSONResponse:
        """回调统计"""
        try:
            from backend.core.task_queue_kernel.callback_registry import get_callback_registry

            cr = get_callback_registry()
            stats = cr.get_stats()
            return JSONResponse(content=stats)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/health/check", methods=["GET"])
    async def api_health_check(request: Request) -> JSONResponse:
        """服务健康检查"""
        try:
            from backend.core.database.base_conn import get_db
            from backend.core.llm_kernel.base_client import get_llm_engine

            llm = get_llm_engine()
            db = get_db()
            services = {
                "database": {"healthy": db is not None},
                "llm": {"healthy": llm.is_available() if llm else False},
            }
            return JSONResponse(content={"services": services})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/trends/system", methods=["GET"])
    async def api_trends_system(request: Request) -> JSONResponse:
        """系统趋势数据（支持 ?days=7|30|90 时间范围，默认 30）"""
        try:
            try:
                days = int(request.query_params.get("days", "30"))
            except ValueError:
                days = 30
            if days not in (7, 30, 90):
                days = 30

            from backend.core.database.base_conn import get_db

            db = get_db()
            rows = db.query_local(
                "SELECT date(timestamp) as d, COUNT(*) as cnt "
                "FROM conversations "
                f"WHERE timestamp >= datetime('now', '-{days} days') "
                "GROUP BY d ORDER BY d"
            )
            timestamps = [r["d"] for r in (rows or [])]
            sessions = [r["cnt"] for r in (rows or [])]
            return JSONResponse(
                content={"timestamps": timestamps, "sessions": sessions, "days": days}
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Growth Review & Apply API
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/growth/review", methods=["POST"])
    async def api_growth_review(request: Request) -> JSONResponse:
        """审核优化建议"""
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            analysis_id = body.get("id")
            action = body.get("action", "approved")
            reviewer = body.get("reviewer", "admin")
            comment = body.get("comment", "")
            if not analysis_id:
                return JSONResponse(content={"error": "缺少 id"}, status_code=400)
            from backend.core.database.base_conn import get_db

            db = get_db()
            db.query_local(
                "UPDATE growth_analysis SET status=?, reviewer=?, review_comment=?, reviewed_at=datetime('now') "
                "WHERE id=?",
                (action, reviewer, comment, analysis_id),
            )
            return JSONResponse(content={"success": True})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/growth/apply", methods=["POST"])
    async def api_growth_apply(request: Request) -> JSONResponse:
        """标记优化建议已应用"""
        try:
            body = await request.json() if request.headers.get("content-length") else {}
            analysis_id = body.get("id")
            if not analysis_id:
                return JSONResponse(content={"error": "缺少 id"}, status_code=400)
            from backend.core.database.base_conn import get_db

            db = get_db()
            db.query_local(
                "UPDATE growth_analysis SET status='applied', applied_at=datetime('now') WHERE id=?",
                (analysis_id,),
            )
            return JSONResponse(content={"success": True})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Archive & Ollama Management
    # ════════════════════════════════════════════════

    @mcp.custom_route("/api/archive/cleanup", methods=["POST"])
    async def api_archive_cleanup(request: Request) -> JSONResponse:
        """数据归档"""
        try:
            from backend.business.data_cleanup.cleanup_service import get_cleanup_scheduler

            scheduler = get_cleanup_scheduler()
            result = scheduler.run_now()
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/ollama/start", methods=["POST"])
    async def api_ollama_start(request: Request) -> JSONResponse:
        """手动启动/重连 Ollama 服务"""
        try:
            from backend.core import bootstrap

            body = await request.json() if request.headers.get("content-length") else {}
            timeout = int(body.get("timeout", 30)) if body else 30
            result = bootstrap.start_ollama_service(timeout=timeout)
            if result["success"]:
                try:
                    from backend.core.llm_kernel.base_client import get_llm_engine

                    llm = get_llm_engine()
                    llm.recheck()  # v9.5.2: 用 recheck 清除陈旧 load_error
                except Exception:
                    logger.warning(
                        "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                    )
                    pass
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/ollama/recheck", methods=["POST"])
    async def api_ollama_recheck(request: Request) -> JSONResponse:
        """v9.5.2: 清除陈旧的 load_error 并重新验证模型可用性。

        启动时 preload() 可能因时序问题失败，load_error 被永久缓存。
        此端点调用 recheck() 清除旧错误后重新验证。
        """
        try:
            from backend.core.llm_kernel.base_client import get_llm_engine

            llm = get_llm_engine()
            result = llm.recheck()
            return JSONResponse(content=result)
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    @mcp.custom_route("/api/ollama/stop", methods=["POST"])
    async def api_ollama_stop(request: Request) -> JSONResponse:
        """停止 Ollama 服务"""
        try:
            import subprocess

            result = subprocess.run(["ollama", "stop"], capture_output=True, text=True, timeout=10)
            from backend.core import bootstrap

            bootstrap.reset_ollama_state()
            bootstrap._ollama_log("Ollama 服务已手动停止", "INFO")
            return JSONResponse(
                content={
                    "success": result.returncode == 0,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                }
            )
        except FileNotFoundError:
            return JSONResponse(content={"success": False, "error": "ollama 命令未找到"})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

    # ════════════════════════════════════════════════
    # Temporary: Conversation Status Query (for debugging)
    # ════════════════════════════════════════════════
    @mcp.custom_route("/api/conversation/status", methods=["GET"])
    async def api_conversation_status(request: Request) -> JSONResponse:
        """查询单个 conversation 的详细状态"""
        try:
            conversation_id = request.query_params.get("conversation_id", "")
            if not conversation_id:
                return JSONResponse(content={"error": "缺少 conversation_id 参数"}, status_code=400)
            from backend.business.conversation_mgr import get_conversation_engine

            engine = get_conversation_engine()
            status = engine.get_conversation_status(conversation_id)
            if status is None:
                return JSONResponse(content={"found": False, "conversation_id": conversation_id})
            return JSONResponse(content={"found": True, **status})
        except Exception as e:
            logger.warning(
                "register_rest_routes: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return JSONResponse(content={"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/conversations", methods=["GET"])
    async def api_conversations_list(request: Request) -> JSONResponse:
        """分页浏览会话历史（支持状态/类型/关键词筛选）"""
        try:
            try:
                limit = int(request.query_params.get("limit", "50"))
                offset = int(request.query_params.get("offset", "0"))
            except ValueError:
                limit, offset = 50, 0
            status = request.query_params.get("status", "")
            task_type = request.query_params.get("task_type", "")
            keyword = request.query_params.get("keyword", "")

            from backend.business.conversation_mgr import get_conversation_engine

            engine = get_conversation_engine()
            result = engine.list_conversations(
                limit=limit, offset=offset, status=status, task_type=task_type, keyword=keyword
            )
            return JSONResponse(
                content={
                    "code": 0,
                    "message": "ok",
                    "data": result,
                }
            )
        except Exception as e:
            logger.warning(
                "register_rest_routes: /api/conversations 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            return JSONResponse(content={"code": 1, "message": str(e), "data": {}}, status_code=500)

    @mcp.custom_route("/api/conversations/{conversation_id:path}", methods=["GET"])
    async def api_conversation_detail(request: Request) -> JSONResponse:
        """会话详情：会话信息 + 步骤 + 进度 + 分析"""
        try:
            conversation_id = request.path_params.get("conversation_id", "")
            if not conversation_id:
                return JSONResponse(
                    content={"code": 1, "message": "缺少 conversation_id", "data": {}},
                    status_code=400,
                )

            from backend.business.conversation_mgr import get_conversation_engine

            engine = get_conversation_engine()
            status = engine.get_conversation_status(conversation_id)
            if status is None:
                return JSONResponse(
                    content={
                        "code": 1,
                        "message": f"会话不存在: {conversation_id}",
                        "data": {},
                    },
                    status_code=404,
                )
            return JSONResponse(content={"code": 0, "message": "ok", "data": status})
        except Exception as e:
            logger.warning(
                "register_rest_routes: /api/conversations/{{id}} 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            return JSONResponse(content={"code": 1, "message": str(e), "data": {}}, status_code=500)
