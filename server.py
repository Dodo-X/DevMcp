"""
DevPartner MCP 服务器 v6.0.0
=============================

🎯 项目定位:
  以 MCP (Model Context Protocol) 形式对外提供服务的智能助手系统，
  包含工具层和智能管家层，支持本地开发和云端部署。

📦 系统架构:
  server.py (MCP 服务入口)
  ├── devpartner_tools/  (工具层, 无状态, 21个纯工具)
  │   ├── filesystem     文件系统操作
  │   ├── git_operations Git 命令封装
  │   ├── web_requests   HTTP 请求
  │   ├── system_utils    系统工具
  │   └── ...            其他基础工具
  │
  └── devpartner_agent/  (智能管家层, 有状态, 67+个智能工具)
      ├── core/           核心引擎 (LLM、数据库、配置)
      ├── services/       业务服务 (对话分析、LLM推理、日报生成等)
      └── skills/         技能模块 (每日总结、自我迭代等)

🔄 协议变更 (v6.0):
  ❌ 旧版: SSE协议 (Server-Sent Events)
  ✅ 新版: Streamable HTTP + /mcp 端点

  客户端调用方式:
    POST http://host:7860/mcp
    Content-Type: application/json
    Body: { "jsonrpc": "2.0", "method": "...", "params": {...} }

📍 访问地址（唯一区别）:
  本地开发:  http://127.0.0.1:7860/mcp
  云端部署:  https://modelscope.cn/studios/Pisces43/Dev-partner/mcp

🚀 启动方式（本地和云端完全一致）:
  python server.py 7860       # 启动 MCP 服务（推荐）
  start.bat                   # Windows 一键启动

  客户端配置示例 (本地):
  {
    "url": "http://127.0.0.1:7860/mcp"
  }

  客户端配置示例 (云端):
  {
    "url": "https://modelscope.cn/studios/Pisces43/Dev-partner/mcp"
  }

⚙️ 端口:
  统一使用 7860（ModelScope要求）

📂 关键目录:
  data/        运行时数据 (数据库、日志、记忆等)
  models/      LLM 推理模型 (Qwen3.5-9B-Q4_1.gguf ~5.7GB)
  Dockerfile   ModelScope 云端部署配置（位于根目录）

作者：DevPartner Team
版本：6.0.0 | 更新: 2026-07-03
"""

import sys
import json
import threading
import asyncio
from pathlib import Path
from datetime import datetime

# 将项目根目录加入 sys.path，确保包导入正常工作
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
import os as _os
import logging

# v6.0.2: 请求诊断日志 — 帮助排查 ModelScope 代理层 MCP 连接问题
_diag_logger = logging.getLogger("devpartner.diag")
_diag_logger.setLevel(logging.INFO)

# v6.0.1: 版本号从 pyproject.toml 动态读取（单一来源）
from devpartner_agent.core.config import get_project_version
VERSION = get_project_version()

# ── ClosedResourceError 补丁 ──────────────────────────────────
# 问题：SSE 连接断开后，writer.send() 继续向已关闭的流写入数据导致崩溃
# 解决：在 FastMCP/MCP 的 SSE 关键位置注入异常捕获
def _apply_sse_closed_resource_patch():
    """
    为 mcp.server.sse 中的 writer.send() 注入 ClosedResourceError 保护。

    核心修复点：
    1. handle_post_message: writer.send(session_message) 捕获 ClosedResourceError
    2. sse_writer: sse_stream_writer.send() 捕获 ClosedResourceError
    3. connect_sse finally: 增强清理逻辑，防止僵尸 session
    """
    try:
        from anyio.streams.memory import ClosedResourceError
        from mcp.server import sse as mcp_sse
        import functools
        from contextlib import asynccontextmanager

        # ── 补丁 1: 包装 handle_post_message 中的 writer.send ──
        _original_handle_post = mcp_sse.SseServerTransport.handle_post_message

        @functools.wraps(_original_handle_post)
        async def _patched_handle_post(self, scope, receive, send):
            try:
                await _original_handle_post(self, scope, receive, send)
            except ClosedResourceError:
                # SSE 连接已断开，静默忽略
                pass
            except Exception:
                raise

        mcp_sse.SseServerTransport.handle_post_message = _patched_handle_post

        # ── 补丁 2: 包装 connect_sse 中的 sse_writer ──
        _original_connect_sse = mcp_sse.SseServerTransport.connect_sse

        @functools.wraps(_original_connect_sse)
        @asynccontextmanager
        async def _patched_connect_sse(self, scope, receive, send):
            try:
                async with _original_connect_sse(self, scope, receive, send) as streams:
                    yield streams
            except ClosedResourceError:
                # 客户端断开连接，静默处理
                pass

        mcp_sse.SseServerTransport.connect_sse = _patched_connect_sse

        # ── 补丁 3: 包装 MemoryObjectSendStream.send 方法 ──
        # 这是最底层的防护：对所有 memory stream 的 send 操作统一捕获 ClosedResourceError
        try:
            from anyio.streams.memory import MemoryObjectSendStream
            _original_send = MemoryObjectSendStream.send

            @functools.wraps(_original_send)
            async def _safe_send(self, item):
                try:
                    return await _original_send(self, item)
                except ClosedResourceError:
                    # 流已关闭，静默丢弃消息
                    return None

            MemoryObjectSendStream.send = _safe_send
            print("[INFO] MemoryObjectSendStream.send ClosedResourceError 保护已注入")
        except Exception as e:
            print(f"[WARN] MemoryObjectSendStream 补丁失败: {e}")

        print("[INFO] SSE ClosedResourceError 补丁已应用")

    except ImportError:
        print("[WARN] 无法导入 anyio/mcp.server.sse，跳过 SSE 补丁")
    except Exception as e:
        print(f"[WARN] SSE 补丁应用失败: {e}")

# 立即应用补丁
_apply_sse_closed_resource_patch()

# 创建统一 MCP 实例
mcp = FastMCP("devpartner")

# ── v6.0.2: CORS 中间件 ──────────────────────────────────────────
# ModelScope 创空间的代理层可能跨域转发 MCP 请求，
# 缺少 CORS 头会导致客户端 preflight 失败 → 连接不上
# 注意: FastMCP 的 _app 属性不存在，CORSMiddleware 在 _run_mcp_service() 中
# 通过 run() 的 middleware 参数注入（见 _run_mcp_service）
print("[INFO] CORS 中间件将通过 mcp.run(middleware=...) 在启动时注入")

# ── v6.0.2: 请求诊断中间件 ────────────────────────────────────────
# 记录每个请求的关键信息，用于排查 ModelScope 代理层问题
class RequestDiagMiddleware(Middleware):
    """记录每个请求的来源、路径、方法，帮助诊断 MCP 连接问题"""
    async def on_before_request(self, context: MiddlewareContext, call_next):
        try:
            req = getattr(context, "request", None)
            if req:
                _diag_logger.info(
                    "[DIAG] %s %s | Origin=%s | Referer=%s | X-Forwarded=%s",
                    req.method, req.url.path,
                    req.headers.get("origin", "-"),
                    req.headers.get("referer", "-")[:80],
                    req.headers.get("x-forwarded-for", "-")
                )
        except Exception:
            pass
        return await call_next(context)

mcp.add_middleware(RequestDiagMiddleware())

# ── v6.0.2: 根路径和 /health 端点 ─────────────────────────────────
# ModelScope 创空间需要根路径和健康检查端点，否则可能拒绝路由流量

@mcp.custom_route("/", methods=["GET", "HEAD"])
async def root_endpoint(request: Request):
    """根路径 — ModelScope 创空间探测入口"""
    return JSONResponse({
        "service": "DevPartner v6.0",
        "version": VERSION,
        "protocol": "MCP Streamable HTTP",
        "mcp_endpoint": "/mcp",
        "health": "/health",
        "dashboard": "/dashboard",
        "status": "running",
    })

@mcp.custom_route("/health", methods=["GET", "HEAD"])
async def health_endpoint(request: Request):
    """快速健康检查 — 轻量级，仅返回存活状态"""
    return JSONResponse({"status": "healthy", "version": VERSION})

# ── v5.2: Web Dashboard 自定义路由 ──
_DASHBOARD_PATH = _os.path.join(_os.path.dirname(__file__),
                                "devpartner_agent", "dashboard.html")

@mcp.custom_route("/mcp", methods=["GET"])
async def mcp_health_check(request: Request) -> JSONResponse:
    """MCP 端点健康检查 — 响应 GET 请求，消除 405 错误"""
    try:
        from devpartner_agent.services.llm_service import get_llm_service
        llm = get_llm_service()
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
        "message": "此 GET 端点用于健康检查；MCP JSON-RPC 调用请使用 POST /mcp",
    })


@mcp.custom_route("/dashboard", methods=["GET"])
async def serve_dashboard(request: Request) -> HTMLResponse:
    """Serve the DevPartner Web Dashboard (版本动态注入)"""
    try:
        with open(_DASHBOARD_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        # v6.0.1: 版本号从 pyproject.toml 动态注入
        html = html.replace("{{VERSION}}", VERSION)
        return HTMLResponse(html)
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Dashboard not found</h1><p>Please ensure dashboard.html exists in devpartner_agent/</p>",
            status_code=404
        )


# ── v6.0: 双向成长仪表盘 API 端点 ──
from devpartner_tools.tools.growth_analytics import (
    get_user_growth_overview,
    get_system_evolution_stats,
    get_user_skill_radar,
    get_learning_timeline,
    get_user_activity_heatmap,
)

@mcp.custom_route("/api/growth/user-overview", methods=["GET"])
async def api_user_growth_overview(request: Request) -> JSONResponse:
    """获取用户成长总览数据"""
    data = json.loads(get_user_growth_overview())
    return JSONResponse(content=data)

@mcp.custom_route("/api/growth/system-evolution", methods=["GET"])
async def api_system_evolution(request: Request) -> JSONResponse:
    """获取系统进化统计数据"""
    data = json.loads(get_system_evolution_stats())
    return JSONResponse(content=data)

@mcp.custom_route("/api/growth/skill-radar", methods=["GET"])
async def api_skill_radar(request: Request) -> JSONResponse:
    """获取用户技能六维雷达图数据"""
    data = json.loads(get_user_skill_radar())
    return JSONResponse(content=data)

@mcp.custom_route("/api/growth/timeline", methods=["GET"])
async def api_learning_timeline(request: Request) -> JSONResponse:
    """获取融合时间线数据"""
    limit = int(request.query_params.get("limit", 20))
    data = json.loads(get_learning_timeline(limit=limit))
    return JSONResponse(content=data)

@mcp.custom_route("/api/growth/activity-heatmap", methods=["GET"])
async def api_activity_heatmap(request: Request) -> JSONResponse:
    """获取学习热力图数据"""
    data = json.loads(get_user_activity_heatmap())
    return JSONResponse(content=data)


# ══════════════════════════════════════════════════════════════
# v6.0: 运维视角 API 端点 (Dashboard 所需)
# ══════════════════════════════════════════════════════════════

@mcp.custom_route("/api/system/status", methods=["GET"])
async def api_system_status(request: Request) -> JSONResponse:
    """获取系统核心指标（当前会话数、任务、知识库、回调）"""
    try:
        from devpartner_agent.core.database import get_db
        from datetime import date as _dt_date

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
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@mcp.custom_route("/api/tasks/list", methods=["GET"])
async def api_tasks_list(request: Request) -> JSONResponse:
    """获取任务队列列表（按排队时间排序，最早的在前面）"""
    try:
        limit = int(request.query_params.get("limit", 20))
        from devpartner_agent.services.task_queue import get_task_queue
        tq = get_task_queue()
        tasks = []
        for task_id, task_data in tq._task_map.items():
            payload = task_data.get("payload", {})
            # 从 payload 中提取更友好的任务名称
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
        # 按排队时间升序，None/空字符串放最后
        tasks.sort(key=lambda t: t["created_at"] or "z")
        return JSONResponse(content=tasks[:limit])
    except Exception as e:
        _diag_logger.error(f"API /api/tasks/list error: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)


@mcp.custom_route("/api/system/memory", methods=["GET"])
async def api_system_memory(request: Request) -> JSONResponse:
    """获取内存使用情况"""
    try:
        import psutil
        process = psutil.Process()
        mem_info = process.memory_info()
        used_mb = round(mem_info.rss / 1024 / 1024, 1)
        total_mb = round(psutil.virtual_memory().total / 1024 / 1024)
        percent = round((used_mb / max(1, total_mb)) * 100, 1)

        details = [
            {"name": "RSS 物理内存", "size_mb": used_mb, "percent": percent},
            {"name": "VMS 虚拟内存", "size_mb": round(mem_info.vms / 1024 / 1024, 1),
             "percent": percent},
        ]

        vm = psutil.virtual_memory()
        sys_used = round(vm.used / 1024 / 1024)
        details.append({"name": "系统总使用", "size_mb": sys_used, "percent": vm.percent})

        return JSONResponse(content={
            "used_mb": used_mb,
            "total_mb": total_mb,
            "percent": percent,
            "details": details,
        })
    except ImportError:
        try:
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            stats = tq.get_queue_stats()
            return JSONResponse(content={
                "used_mb": stats.get("memory_usage_mb", 0),
                "total_mb": stats.get("memory_limit_mb", 500),
                "percent": stats.get("utilization_percent", 0),
                "details": [{
                    "name": "任务队列估算",
                    "size_mb": stats.get("memory_usage_mb", 0),
                    "percent": stats.get("utilization_percent", 0),
                }],
            })
        except Exception:
            return JSONResponse(content={
                "used_mb": 0, "total_mb": 1, "percent": 0, "details": []
            })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@mcp.custom_route("/api/callbacks/stats", methods=["GET"])
async def api_callback_stats(request: Request) -> JSONResponse:
    """获取回调统计信息"""
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
    """系统健康检查"""
    import os as _os
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
        from devpartner_agent.services.llm_service import get_llm_service
        llm = get_llm_service()
        available = llm.is_available() if llm else False
        result["services"]["llm_service"] = {
            "healthy": available,
            "detail": "Ollama 已连接" if available else "Ollama 不可达",
        }
    except Exception as e:
        result["services"]["llm_service"] = {"healthy": False, "detail": str(e)}

    try:
        test_path = Path(_os.path.dirname(__file__)) / "data"
        writable = _os.access(str(test_path), _os.W_OK) if test_path.exists() else False
        result["services"]["filesystem"] = {
            "healthy": test_path.exists() and writable,
            "detail": "可读写" if writable else (
                "目录不存在" if not test_path.exists() else "无写入权限"
            ),
        }
    except Exception as e:
        result["services"]["filesystem"] = {"healthy": False, "detail": str(e)}

    return JSONResponse(content=result)


@mcp.custom_route("/api/trends/system", methods=["GET"])
async def api_system_trends(request: Request) -> JSONResponse:
    """获取系统运行趋势"""
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
        try:
            from devpartner_agent.services.task_queue import get_task_queue
            tq = get_task_queue()
            completed = tq.get_queue_stats().get("total_completed", 0)
        except Exception:
            pass

        triggered = 0
        try:
            from devpartner_agent.services.callback_registry import get_callback_registry
            cr = get_callback_registry()
            triggered = cr.get_stats().get("total_triggered", 0)
        except Exception:
            pass

        n = max(1, len(timestamps))
        tasks = [max(0, completed // n)] * n
        callbacks = [max(0, triggered // n)] * n

        return JSONResponse(content={
            "timestamps": timestamps,
            "sessions": sessions,
            "tasks_completed": tasks,
            "callbacks_triggered": callbacks,
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ── 项目知识库查询 API（v7.4.0）──
@mcp.custom_route("/api/projects/list", methods=["GET"])
async def api_projects_list(request: Request) -> JSONResponse:
    """获取有业务知识的项目列表（供前端下拉框）"""
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
    """交互式项目知识搜索（支持 project_name + type 筛选）"""
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


print("=" * 60)
print(f"  DevPartner 服务器 v{VERSION} 启动中...")
print("  devpartner-tools + devpartner-agent → 单一入口")
print(f"  v{VERSION}: LLM驱动分析引擎 + 总分总对话录制 + 知识图谱 + 双向仪表盘")
print("=" * 60)


# ============================================================
# 自动日志中间件 + 智能触发引擎
# ============================================================

# 排除自动记录的工具（避免自己记录自己）
_AUTO_LOG_SKIP_TOOLS = {
    # 纯查询/元数据工具（不涉及对话内容）
    "get_rules", "check_rule",
    "system_diagnose", "get_tool_registry", "get_capabilities",
    "get_daily_summary", "read_daily_log", "list_logs", "check_log_gaps",
    "get_daily_work_data", "get_weekly_work_data", "get_work_schema_guide",
    "get_approval_chain", "check_module_messages",
    "list_directory", "search_files", "search_content",
    "detect_client", "environment_scan", "validate_path",
    "get_auto_log_stats", "check_optimization_needed",
    "mark_optimization_done",
    # v2.4.0 元工具（不产生对话内容）
    "get_skill_profile", "get_optimization_report",
    "apply_optimization", "file_watcher_control",
    "get_skill_domains",
    "save_self_iterate_results",
    # record_dialogue/record_conversation/process_user_feedback 不再跳过
    # 它们通过 _NO_FEEDBACK_DETECTION_TOOLS 排除反馈检测，但仍参与工具计数和有意义对话计数
}

# 不参与反馈检测但仍需记录调用次数的工具（避免误触发用户反馈检测）
_NO_FEEDBACK_DETECTION_TOOLS = {
    "record_dialogue", "record_conversation", "process_user_feedback",
}

# 用户反馈关键词 —— 用于检测用户对AI回答的纠正/不满/补充
_USER_FEEDBACK_PATTERNS = [
    (r"(?:不对|不正确|不是这样|错误|搞错了|有问题|修正|改正|纠正|修复一下|改一下)", "纠正"),
    (r"(?:补充|还要|再加上|还需要|别忘了|缺少)", "补充"),
    (r"(?:不满意|不好|不够好|太差|太慢|太复杂|没法用|跑不通|不行|不能用)", "不满"),
    (r"(?:重新|再来|换一种|换个方式)", "重试"),
    (r"(?:为什么|怎么会|原理是|详细|深入|展开)", "追问"),
]

# ── 持久化优化状态（写入 SQLite，重启不丢失）──
# 统计数据从 mcp_tool_registry 表实时查询，不再使用内存变量
_auto_log_lock = threading.Lock()
_optimization_state = {
    "last_optimization_at": None,   # 上次触发优化的时间
    "last_summary_at": None,        # 上次触发总结的时间
    "optimization_pending": False,  # 是否有待处理的优化
}
# 优化状态持久化文件
_OPTIMIZATION_STATE_FILE = Path(__file__).parent / "data" / ".optimization_state.json"

# ── 后台任务队列（v5.2 异步化优化）──
# 将耗时操作（LLM 分析、数据校验、自动分析触发）放入后台线程异步执行
# 避免阻塞 MCP 工具调用的主流程
import queue as _queue
_background_task_queue: _queue.Queue = _queue.Queue()
_background_worker_started: bool = False
_background_worker_lock = threading.Lock()


def _start_background_worker():
    """启动后台任务处理线程（懒启动，首次 record_dialogue 时触发）"""
    global _background_worker_started
    with _background_worker_lock:
        if _background_worker_started:
            return
        _background_worker_started = True

    def _worker():
        while True:
            try:
                task = _background_task_queue.get(timeout=5)
                if task is None:  # 哨兵：停止 worker
                    break
                try:
                    task["func"](*task.get("args", []), **task.get("kwargs", {}))
                except Exception:
                    pass  # 后台任务失败静默
            except _queue.Empty:
                continue

    t = threading.Thread(target=_worker, daemon=True, name="devpartner-bg-worker")
    t.start()
    print("[INFO] 后台任务处理线程已启动（异步数据分析/校验/归档）")


def _enqueue_background_task(func, *args, **kwargs):
    """将耗时任务放入后台队列异步执行"""
    _start_background_worker()
    _background_task_queue.put({"func": func, "args": args, "kwargs": kwargs})


def _load_optimization_state():
    """从文件加载优化状态（持久化，重启不丢失）"""
    global _optimization_state
    try:
        if _OPTIMIZATION_STATE_FILE.exists():
            with open(_OPTIMIZATION_STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                _optimization_state.update(saved)
    except Exception:
        pass


def _save_optimization_state():
    """持久化优化状态到文件"""
    try:
        _OPTIMIZATION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_OPTIMIZATION_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_optimization_state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_tool_call_stats() -> dict:
    """从数据库实时查询工具调用统计（替代内存变量）"""
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()
        return db.get_tool_stats()
    except Exception:
        return {"total_tools": 0, "total_calls": 0}


# 启动时加载持久化状态
_load_optimization_state()


class AutoLogMiddleware(Middleware):
    """
    智能工具调用中间件 (v4.0.0)

    功能：
    1. 记录所有工具调用次数到 mcp_tool_registry 表（用于使用率分析）
    2. 检测用户反馈信号（纠正/不满/重试/追问），写入 optimization_hint.json
    3. 区分"有意义的对话工具"和"简单查询工具"
       - 有意义：record_dialogue, record_conversation, self_iterate, self_upgrade 等
       - 简单查询：read_file, search_content, list_directory 等
    4. 有意义对话计数持久化到 data/.conversation_counter.json

    触发链：
      有意义对话累计 20 次 → check_optimization_needed 返回 should_optimize=true
      → AI 客户端调用 self_iterate → 系统分析优化
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = getattr(context.message, "name", "unknown") if hasattr(context, "message") else "unknown"

        # 尝试获取用户输入（用于反馈检测）
        user_input = ""
        try:
            if hasattr(context, "params") and context.params:
                if isinstance(context.params, dict):
                    for key in ("content", "query", "prompt", "message", "user_input",
                                 "description", "topic", "text", "user_question"):
                        val = context.params.get(key, "")
                        if isinstance(val, str) and len(val) > 3:
                            user_input += val + " "
        except Exception:
            pass

        # 执行实际的工具调用
        result = await call_next(context)

        # 跳过不需要记录的工具
        if tool_name in _AUTO_LOG_SKIP_TOOLS:
            return result

        # 异步记录工具调用计数 + 反馈检测 + 有意义对话计数
        try:
            _on_tool_call_done(tool_name, user_input)
        except Exception:
            pass

        return result


# ── 有意义对话计数持久化 ──
_MEANINGFUL_CONVERSATION_TOOLS = {
    "record_dialogue", "record_conversation",
    "self_iterate", "self_upgrade", "self_create_file",
    "process_user_feedback",
}

_CONVERSATION_COUNTER_FILE = Path(__file__).parent / "data" / ".conversation_counter.json"


def _load_conversation_counter() -> dict:
    """加载有意义对话计数器"""
    try:
        if _CONVERSATION_COUNTER_FILE.exists():
            with open(_CONVERSATION_COUNTER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"total_count": 0, "last_optimize_count": 0, "daily_counts": {}}


def _save_conversation_counter(counter: dict):
    """持久化对话计数器"""
    try:
        _CONVERSATION_COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONVERSATION_COUNTER_FILE, "w", encoding="utf-8") as f:
            json.dump(counter, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_meaningful_tool(tool_name: str) -> bool:
    """判断工具调用是否代表一次有意义的对话"""
    return tool_name in _MEANINGFUL_CONVERSATION_TOOLS


def _on_tool_call_done(tool_name: str, user_input: str = ""):
    """
    工具调用后的智能处理（v5.2 优化版）

    三件事：
    1. 更新 mcp_tool_registry 表中的调用计数
    2. 如果是有意义的对话工具，更新对话计数器
    3. 检测用户反馈信号（排除 record_dialogue 等自身记录工具）
    """
    from devpartner_agent.core.database import get_db

    # ── 1. 记录工具调用次数（用于使用率分析）──
    try:
        db = get_db()
        db.record_tool_call(tool_name)
    except Exception:
        pass

    # ── 2. 有意义对话计数 ──
    if _is_meaningful_tool(tool_name):
        with _auto_log_lock:
            counter = _load_conversation_counter()
            counter["total_count"] = counter.get("total_count", 0) + 1
            today = datetime.now().strftime("%Y-%m-%d")
            counter["daily_counts"][today] = counter["daily_counts"].get(today, 0) + 1
            _save_conversation_counter(counter)

            # 每 20 次有意义对话触发一次优化检查
            meaningful_since_last = counter["total_count"] - counter.get("last_optimize_count", 0)
            if meaningful_since_last >= 20:
                _optimization_state["optimization_pending"] = True
                _save_optimization_state()
                _write_optimization_hint("auto_trigger",
                    extra_reason=f"已累计 {meaningful_since_last} 次有意义对话（总计 {counter['total_count']} 次），建议触发自我迭代")

    # ── 3. 用户反馈检测（跳过 record_dialogue/record_conversation 等自身工具）──
    if tool_name in _NO_FEEDBACK_DETECTION_TOOLS:
        return  # 数据记录工具自身不检测用户反馈

    feedback_detected = False
    feedback_type = ""
    if user_input:
        user_lower = user_input.lower()
        for pattern, ftype in _USER_FEEDBACK_PATTERNS:
            if re.search(pattern, user_lower):
                feedback_detected = True
                feedback_type = ftype
                break

    if feedback_detected:
        with _auto_log_lock:
            _optimization_state["optimization_pending"] = True
            _save_optimization_state()
        _write_optimization_hint(feedback_type)


def _write_optimization_hint(feedback_type: str = "", extra_reason: str = ""):
    """
    写入优化提示文件，供 AI 客户端在下次对话时感知。

    当检测到用户纠正/不满/重试等信号，或有意义对话累计达到 20 次时，
    标记 optimization_pending=True，
    AI 客户端下次可通过 check_optimization_needed 检查并触发 self_iterate。
    """
    try:
        from devpartner_agent.core.config import get_config
        hint_path = Path(get_config().data.temp_dir) / "optimization_hint.json"
    except Exception:
        hint_path = _project_root / "data" / "temp" / "optimization_hint.json"
    hint_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().isoformat()
    stats = _get_tool_call_stats()

    # 读取对话计数器
    with _auto_log_lock:
        counter = _load_conversation_counter()

    # 从数据库获取使用率最低和最高的工具
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()
        tools = db.get_registered_tools()
        sorted_tools = sorted(tools, key=lambda t: t.get("call_count", 0))
        unused_tools = [t["tool_name"] for t in sorted_tools if t.get("call_count", 0) == 0][:10]
        hot_tools = [t["tool_name"] for t in sorted(sorted_tools, key=lambda t: t.get("call_count", 0), reverse=True)][:5]
    except Exception:
        unused_tools = []
        hot_tools = []

    # 获取 conversations 表中最近的有意义对话数
    try:
        db = get_db()
        meaningful_from_db = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversations WHERE task_type != '工具调用'"
        )
        db_meaningful_count = meaningful_from_db[0]["cnt"] if meaningful_from_db else 0
    except Exception:
        db_meaningful_count = 0

    hint_data = {
        "timestamp": now,
        "stats": stats,
        "unused_tools": unused_tools,
        "hot_tools": hot_tools,
        "feedback_detected": bool(feedback_type),
        "feedback_type": feedback_type,
        "optimization_pending": _optimization_state.get("optimization_pending", False),
        "last_optimization_at": _optimization_state.get("last_optimization_at"),
        "last_summary_at": _optimization_state.get("last_summary_at"),
        "conversation_counter": counter,
        "db_meaningful_count": db_meaningful_count,
        "suggested_actions": [],
    }

    if feedback_type:
        hint_data["suggested_actions"].append({
            "tool": "check_optimization_needed",
            "reason": f"检测到用户反馈: {feedback_type}",
        })

    if extra_reason:
        hint_data["suggested_actions"].append({
            "tool": "check_optimization_needed",
            "reason": extra_reason,
        })

    try:
        with open(hint_path, "w", encoding="utf-8") as f:
            json.dump(hint_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# 注册中间件
mcp.add_middleware(AutoLogMiddleware())
print("[INFO] 智能自动日志中间件已注册 - 每次工具调用自动记录 + 反馈感知")


# ============================================================
# 注册 devpartner-tools 的所有工具（无状态纯工具层）
# ============================================================

print("[INFO] 加载 devpartner-tools 工具层...")

try:
    from devpartner_tools.tools.filesystem import (
        read_file, write_file, list_directory, search_files, search_content
    )
    from devpartner_tools.tools.git_operations import (
        git_status, git_log, git_diff
    )
    from devpartner_tools.tools.web_requests import (
        fetch_url, github_search_code, github_search_repositories, context7_search
    )
    from devpartner_tools.tools.system_utils import (
        execute_system_command, detect_client, environment_scan, validate_path
    )

    # 注册所有工具
    mcp.tool(read_file)
    mcp.tool(write_file)
    mcp.tool(list_directory)
    mcp.tool(search_files)
    mcp.tool(search_content)
    mcp.tool(git_status)
    mcp.tool(git_log)
    mcp.tool(git_diff)
    mcp.tool(fetch_url)
    mcp.tool(github_search_code)
    mcp.tool(github_search_repositories)
    mcp.tool(context7_search)
    mcp.tool(execute_system_command)
    mcp.tool(detect_client)
    mcp.tool(environment_scan)
    mcp.tool(validate_path)

    _tools_count = 21
    print(f"[INFO] devpartner-tools: {_tools_count} 个纯工具已注册")
    # 调试: 验证工具是否在 mcp 实例上
    try:
        _reg_tools = [t.name for t in asyncio.run(mcp._list_tools())]
        print(f"[DEBUG] mcp 实例上注册的工具: {_reg_tools}")
    except Exception as de:
        print(f"[DEBUG] 无法列出工具: {de}")

except Exception as e:
    print(f"[WARN] devpartner-tools 加载失败: {e}")
    print("[WARN] 纯工具层将不可用，仅管家层运行")
    _tools_count = 0


# ============================================================
# 注册 devpartner-agent 的所有工具（智能管家层）
# ============================================================

print("[INFO] 加载 devpartner-agent 智能管家层...")

# ── 核心初始化 ──────────────────────────────────────────────
_core_initialized = False

def _ensure_core():
    """确保核心模块已初始化（首次调用时初始化DB）"""
    global _core_initialized
    if _core_initialized:
        return True

    try:
        from devpartner_agent.core.config import get_config
        from devpartner_agent.core.database import get_db

        cfg = get_config()
        db_path = str(Path(cfg.data.databases_dir) / "devpartner.db")
        get_db().init_local(db_path)
        
        # v6.0.1: 确保 conversations.conversation_id 唯一约束（FK依赖）
        try:
            db = get_db()
            cursor = db._local_conn.cursor()
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique 
                ON conversations(conversation_id)
            """)
            db._local_conn.commit()
        except Exception:
            pass  # 可能已存在或数据不兼容，由 record_step 自修复兜底

        # 预热其他核心模块
        from devpartner_agent.core.rule_engine import get_engine
        from devpartner_agent.core.identity import get_identity
        from devpartner_agent.core.evolution import get_evolution_engine

        # 启动自动清理调度器
        try:
            from devpartner_agent.services.cleanup_scheduler import get_cleanup_scheduler
            scheduler = get_cleanup_scheduler()
            cleanup_interval = (
                cfg.data_lifecycle.auto_cleanup_interval_hours
                if hasattr(cfg.data_lifecycle, 'auto_cleanup_interval_hours')
                else 24
            )
            if cfg.data_lifecycle.auto_cleanup:
                scheduler.start(interval_hours=cleanup_interval)
                print(f"[INFO] 自动清理调度器已启动，间隔 {cleanup_interval} 小时")
        except Exception as e:
            print(f"[WARN] 自动清理调度器启动失败: {e}")

        # v7.0: 启动任务数据清理服务（软删除 + 物理删除 + VACUUM）
        try:
            from devpartner_agent.services.cleanup_service import get_cleanup_service
            cs = get_cleanup_service()  # 构造即启动后台线程
            print("[INFO] 任务数据清理服务已启动 (v7.0)")
        except Exception as e:
            print(f"[WARN] 任务数据清理服务启动失败: {e}")

        # ── v2.4.0 启动文件监控 ──
        try:
            from devpartner_agent.services.file_watcher import get_watcher
            watcher = get_watcher()
            # 使用环境变量或默认路径
            watcher.start()
        except Exception as e:
            print(f"[WARN] 文件监控启动失败: {e}")

        # ── v4.4 预加载本地 LLM（可选）──
        try:
            if cfg.llm.enabled and cfg.llm.preload:
                from devpartner_agent.services.llm_service import get_llm_service
                llm = get_llm_service()
                if llm.preload():
                    print(f"[INFO] Ollama LLM 已就绪: {getattr(cfg.llm, 'ollama_model', 'qwen3')}")
                elif llm.is_enabled():
                    status = llm.get_status()
                    print(f"[WARN] 本地 LLM 预加载跳过: {status.get('load_error') or '模型不可用'}")
        except Exception as e:
            print(f"[WARN] 本地 LLM 初始化失败: {e}")

        _core_initialized = True
        return True
    except Exception as e:
        print(f"[WARN] 核心模块初始化失败: {e}")
        print("[WARN] Agent 将以降级模式运行（仅基础功能可用）")
        return False


# ── 模块协作消息 ─────────────────────────────────────────────
def send_module_message(target_module: str, message: str,
                        message_type: str = "info",
                        priority: int = 1) -> str:
    """
    发送模块间协作消息（devpartner-tools ↔ devpartner-agent 内部通信）
    """
    _ensure_core()
    try:
        from devpartner_agent.services.dialogue_service import get_dialogue
        dialogue_svc = get_dialogue()

        msg_data = {
            "from": "devpartner-agent" if target_module == "tools" else "devpartner-tools",
            "to": target_module,
            "message": message,
            "type": message_type,
            "priority": priority,
            "timestamp": datetime.now().isoformat()
        }

        result = dialogue_svc.send_message(msg_data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def check_module_messages() -> str:
    """检查未读的模块间消息"""
    _ensure_core()
    try:
        from devpartner_agent.services.dialogue_service import get_dialogue
        dialogue_svc = get_dialogue()
        messages = dialogue_svc.get_unread_messages()
        return json.dumps({"success": True, "messages": messages, "count": len(messages)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 自我迭代引擎 ─────────────────────────────────────────────
def self_iterate(mode: str = "auto", dry_run: bool = False,
                 require_approval: bool = False) -> str:
    """
    执行自我迭代流程（带审批链）

    这是 DevPartner 最核心的自我进化能力：
    1. 收集系统数据（使用频率、错误日志、用户反馈）
    2. 通过 AI 分析生成改进建议
    3. 识别可自动执行的代码变更
    4. 审批链检查（自动→AI→用户）
    5. 在安全模式下执行变更（备份+回滚+Git提交）

    Args:
        mode: 运行模式
            - 'auto': 自动选择（无Git则本地模式，有Git则完整模式）
            - 'local': 本地模式（仅生成变更，不执行Git操作）
            - 'full': 完整模式（Git分支+提交+PR）
            - 'analyze': 仅分析不执行变更（同 dry_run=True）
        dry_run: 预览模式，不实际执行变更
        require_approval: 是否要求高风险操作经过审批

    Returns:
        JSON: 迭代结果（包含建议、变更、审批状态、Git状态等）
    """
    _ensure_core()
    try:
        from devpartner_agent.skills.self_iterate import run_self_iterate
        from devpartner_agent.core.approval_chain import ApprovalChain, create_approval_request

        chain = ApprovalChain(
            auto_approve_enabled=True,
            user_approve_enabled=require_approval,
            dry_run=dry_run or mode == "analyze"
        )

        approval_req = create_approval_request(
            operation="self_iterate",
            description=f"自我迭代分析 - 模式: {mode}",
            risk_level="medium" if mode in ("full", "auto") else "low",
            mode=mode,
            dry_run=dry_run or mode == "analyze"
        )

        approval_result = chain.process(approval_req)

        if approval_result.status.value == "rejected":
            return json.dumps({
                "success": False,
                "error": f"审批被拒绝: {approval_result.reason}",
                "approval": {
                    "status": approval_result.status.value,
                    "reason": approval_result.reason,
                    "approved_by": approval_result.approved_by,
                }
            }, ensure_ascii=False)

        if approval_result.status.value == "skipped":
            mode = "analyze"

        result = run_self_iterate(mode)

        # 增强结果：补充用户画像、技能评估等维度数据
        try:
            from devpartner_agent.skills.self_iterate import _collect_system_data, _generate_data_driven_suggestions
            enhanced_data = _collect_system_data()
            enhanced_suggestions = _generate_data_driven_suggestions(enhanced_data)
            result["system_data"] = enhanced_data
            result["suggestions_generated"] = enhanced_suggestions
        except Exception:
            pass

        result["approval"] = {
            "status": approval_result.status.value,
            "reason": approval_result.reason,
            "approved_by": approval_result.approved_by,
            "approved_at": approval_result.approved_at,
        }
        result["approval_summary"] = chain.get_summary()

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "steps": []}, ensure_ascii=False)


def self_upgrade(file_path: str, new_content: str,
                 validate: bool = True) -> str:
    """自我升级 - 修改自身代码（备份+验证+回滚）"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.upgrade_file(file_path, new_content, validate)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def self_create_file(file_path: str, content: str,
                     validate: bool = True) -> str:
    """自我创建新文件"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.create_file(file_path, content, validate)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 规则引擎 ─────────────────────────────────────────────────
def get_rules() -> str:
    """获取所有已注册的规则"""
    _ensure_core()
    try:
        from devpartner_agent.core.rule_engine import get_engine
        engine = get_engine()
        rules = engine.get_all()
        from dataclasses import asdict
        rules_list = [{"name": k, **{key: val for key, val in asdict(v).items() if key != 'handler'}} for k, v in rules.items()]
        return json.dumps({"success": True, "rules": rules_list, "count": len(rules_list)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def trigger_rule(rule_name: str, context: str = "{}") -> str:
    """手动触发指定规则"""
    _ensure_core()
    try:
        from devpartner_agent.core.rule_engine import get_engine
        engine = get_engine()
        ctx = json.loads(context) if isinstance(context, str) else context
        result = engine.trigger(rule_name, ctx)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 日志管理 ─────────────────────────────────────────────────
def get_daily_summary(date: str = "") -> str:
    """获取每日工作总结"""
    _ensure_core()
    try:
        from devpartner_agent.skills.daily_summary import generate_daily_summary
        result = generate_daily_summary(date)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def read_daily_log(date: str = "") -> str:
    """读取指定日期的对话日志（v6.2: 从数据库读取）"""
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        # 从 conversation_archive 表读取指定日期的对话（v7.0: 表可能不存在）
        try:
            archives = db.query_local(
                """SELECT conversation_id, timestamp, summary, raw_content, complexity, skill_domains
                   FROM conversation_archive
                   WHERE date(timestamp) = ?
                   ORDER BY timestamp ASC""",
                (date,)
            )
        except Exception:
            archives = []
        conversations = db.query_local(
            """SELECT * FROM conversations
               WHERE date(timestamp) = ?
               ORDER BY timestamp ASC""",
            (date,)
        )
        return json.dumps({
            "success": True,
            "date": date,
            "archives": archives or [],
            "conversations": conversations or [],
            "archive_count": len(archives) if archives else 0,
            "conversation_count": len(conversations) if conversations else 0,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def list_logs() -> str:
    """列出所有有对话记录的日期（v6.2: 从数据库读取）"""
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()
        # 从 conversations 表按天聚合
        daily = db.query_local(
            """SELECT date(timestamp) as date, COUNT(*) as count
               FROM conversations
               GROUP BY date(timestamp)
               ORDER BY date DESC"""
        )
        return json.dumps({
            "success": True,
            "daily_summary": daily or [],
            "total_dates": len(daily) if daily else 0,
            "note": "v6.2: 数据来自 SQLite，不再依赖 Markdown 文件",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def check_log_gaps(date: str = "") -> str:
    """检查指定日期对话的时间间隙（v6.2: 从数据库读取）"""
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        rows = db.query_local(
            """SELECT timestamp FROM conversations
               WHERE date(timestamp) = ?
               ORDER BY timestamp ASC""",
            (date,)
        )
        if not rows:
            return json.dumps({"has_gaps": False, "message": f"日期 {date} 暂无对话记录", "total_entries": 0})

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

        return json.dumps({
            "has_gaps": len(gaps) > 0,
            "gap_count": len(gaps),
            "gaps": gaps,
            "total_entries": len(rows),
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 每日总结数据接口 ─────────────────────────────────────────
def get_daily_work_data(date: str = "", fallback_to_log: bool = True) -> str:
    """获取指定日期的工作原始数据（供 AI 客户端分析用）"""
    _ensure_core()
    try:
        from devpartner_agent.skills.daily_summary import get_daily_work_data as get_data
        result = get_data(date if date else None, fallback_to_log)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def save_daily_analysis(analysis_json: str) -> str:
    """保存 AI 客户端的每日分析结果"""
    _ensure_core()
    try:
        from devpartner_agent.skills.daily_summary import save_daily_analysis as save_analysis
        result = save_analysis(analysis_json)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def get_weekly_work_data() -> str:
    """获取最近7天的工作数据概览"""
    _ensure_core()
    try:
        from devpartner_agent.skills.daily_summary import get_weekly_work_data as get_weekly
        result = get_weekly()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def get_work_schema_guide() -> str:
    """获取 save_daily_analysis 所需的数据结构说明"""
    schema = {
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
    return json.dumps(schema, ensure_ascii=False, indent=2)



# ── 并行任务分解引擎 ─────────────────────────────────────────
def parallel_plan(tasks: str) -> str:
    """
    并行任务分解引擎

    分析任务列表，找出可并行执行的任务，生成最优执行计划。
    """
    try:
        task_list = json.loads(tasks) if isinstance(tasks, str) else tasks
        return json.dumps(_analyze_parallel_plan(task_list), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _analyze_parallel_plan(tasks):
    """分析并行执行计划"""
    if not tasks:
        return {"success": False, "error": "任务列表为空"}

    result = {
        "success": True,
        "total_tasks": len(tasks),
        "parallel_groups": [],
        "sequential_chains": [],
        "execution_order": [],
        "critical_path": []
    }

    task_map = {}
    for task in tasks:
        name = task.get("name", task.get("id", str(len(task_map))))
        deps = task.get("dependencies", task.get("deps", []))
        task_map[name] = {"name": name, "deps": deps if isinstance(deps, list) else []}

    remaining = set(task_map.keys())

    while remaining:
        available = set()
        for name in remaining:
            if all(d not in remaining for d in task_map[name]["deps"]):
                available.add(name)

        if not available:
            result["execution_order"].append(list(remaining))
            result["parallel_groups"].append(list(remaining))
            break

        result["parallel_groups"].append(list(available))
        for name in available:
            result["execution_order"].append(name)
        remaining -= available

    chain = [name for name in result["execution_order"]]
    if chain:
        result["sequential_chains"].append(chain)
        result["critical_path"] = chain

    return result


# ── 注册表管理 ───────────────────────────────────────────────
def get_tool_registry() -> str:
    """获取工具注册表"""
    _ensure_core()
    try:
        from devpartner_agent.core.tool_registry import get_tool_registry as get_registry
        registry = get_registry()
        result = registry.get_summary()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def register_custom_tool(tool_name: str, tool_code: str,
                         category: str = "custom") -> str:
    """注册自定义工具"""
    _ensure_core()
    try:
        from devpartner_agent.core.tool_registry import get_tool_registry as get_registry
        registry = get_registry()
        result = registry.register(tool_name, category=category)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 能力授权 ─────────────────────────────────────────────────
def get_capabilities() -> str:
    """获取当前能力授权状态"""
    _ensure_core()
    try:
        from devpartner_agent.core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        result = mgr.get_status_report()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def authorize_capability(module: str, capability: str,
                         reason: str = "") -> str:
    """授权指定模块的能力"""
    _ensure_core()
    try:
        from devpartner_agent.core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        result = mgr.authorize(module, capability, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def revoke_capability(module: str, capability: str,
                      reason: str = "") -> str:
    """撤销指定模块的能力授权"""
    _ensure_core()
    try:
        from devpartner_agent.core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        result = mgr.revoke(module, capability, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 审批链管理 ───────────────────────────────────────────────
def get_approval_chain(operation: str = "") -> str:
    """获取审批链状态"""
    _ensure_core()
    try:
        from devpartner_agent.core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        result = chain.get_status(operation) if operation else chain.get_all_status()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def approve_operation(operation_id: str, reason: str = "") -> str:
    """手动审批操作"""
    _ensure_core()
    try:
        from devpartner_agent.core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        result = chain.manual_approve(operation_id, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def reject_operation(operation_id: str, reason: str) -> str:
    """拒绝审批操作"""
    _ensure_core()
    try:
        from devpartner_agent.core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        result = chain.manual_reject(operation_id, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 规则检测 ─────────────────────────────────────────────────
def check_rule(rule_name: str, content: str = "") -> str:
    """检查指定规则是否会被触发"""
    _ensure_core()
    try:
        from devpartner_agent.core.rule_engine import get_engine
        engine = get_engine()
        result = engine.check_rule(rule_name, content)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 热重载 ───────────────────────────────────────────────────
def hot_reload(module: str = "all") -> str:
    """热重载指定模块"""
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()

        if module == "all":
            targets = [
                "devpartner_tools",
                "devpartner_tools.tools.filesystem",
                "devpartner_tools.tools.git_operations",
                "devpartner_tools.tools.web_requests",
                "devpartner_tools.tools.system_utils",
                "devpartner_tools.tools.growth_analytics",
                "devpartner_agent",
                "devpartner_agent.core",
                "devpartner_agent.services",
                "devpartner_agent.skills",
            ]
        elif module == "tools":
            targets = [
                "devpartner_tools",
                "devpartner_tools.tools.filesystem",
                "devpartner_tools.tools.git_operations",
                "devpartner_tools.tools.web_requests",
                "devpartner_tools.tools.system_utils",
                "devpartner_tools.tools.growth_analytics",
            ]
        elif module == "agent":
            targets = [
                "devpartner_agent",
                "devpartner_agent.core",
                "devpartner_agent.services",
                "devpartner_agent.skills",
            ]
        else:
            targets = [module]

        reloaded = []
        failed = []
        for target in targets:
            r = engine.hot_reload_module(target)
            if r.get("success"):
                reloaded.append({"module": target, "action": r.get("action", "reloaded")})
            else:
                failed.append({"module": target, "error": r.get("error", "unknown")})

        result = {
            "success": len(failed) == 0,
            "reloaded": reloaded,
            "failed": failed,
            "timestamp": datetime.now().isoformat()
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 自动日志统计 ─────────────────────────────────────────────
def get_auto_log_stats() -> str:
    """
    获取系统工具调用统计与优化状态。

    数据来源：
    - 工具调用次数：从 mcp_tool_registry 表实时查询
    - 优化状态：从持久化文件读取（重启不丢失）

    Returns:
        JSON: {success, stats: {total_tools, total_calls, optimization_pending,
               last_optimization_at, last_summary_at}}
    """
    try:
        stats = _get_tool_call_stats()
        with _auto_log_lock:
            state = dict(_optimization_state)
        stats.update(state)
        return json.dumps({"success": True, "stats": stats}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 优化触发检查（v4.0.0 对话驱动版）─────────────────────────
def check_optimization_needed() -> str:
    """
    检查系统是否需要自我优化。

    基于 conversations 表中的有意义对话数 + optimization_hint.json 提示文件，
    判断是否达到优化触发条件。

    触发条件（对话驱动）：
    - 每积累 20 次有意义的对话 → 建议触发 self_iterate
    - 检测到用户反馈信号 → 建议触发 self_iterate
    - optimization_hint.json 中有待处理标记 → 建议触发
    - 有大量未使用的 MCP 工具 → 建议审视

    此工具**不自动执行** self_iterate，只返回建议。
    AI 客户端根据返回结果决定是否调用 self_iterate。

    Returns:
        JSON: {success, should_optimize, reason, stats: {total_calls, meaningful_conversations, ...},
               unused_tools, hot_tools, conversation_counter, db_meaningful_count}
    """
    try:
        stats = _get_tool_call_stats()
        total_calls = stats.get("total_calls", 0)

        # 读取对话计数器
        with _auto_log_lock:
            counter = _load_conversation_counter()
        meaningful_total = counter.get("total_count", 0)
        meaningful_since_last = meaningful_total - counter.get("last_optimize_count", 0)

        # 从 DB 查询有意义对话数
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            db_meaningful = db.query_local(
                "SELECT COUNT(*) as cnt FROM conversations WHERE task_type != '工具调用'"
            )
            db_meaningful_count = db_meaningful[0]["cnt"] if db_meaningful else 0
        except Exception:
            db_meaningful_count = 0

        # 读取优化提示文件
        hint_data = {}
        try:
            from devpartner_agent.core.config import get_config
            hint_path = Path(get_config().data.temp_dir) / "optimization_hint.json"
        except Exception:
            hint_path = _project_root / "data" / "temp" / "optimization_hint.json"
        if hint_path.exists():
            with open(hint_path, "r", encoding="utf-8") as f:
                hint_data = json.load(f)

        should_optimize = False
        reason = ""
        reasons = []

        # 条件 1: 每 20 次有意义对话
        if meaningful_since_last >= 20:
            should_optimize = True
            reasons.append(f"已累计 {meaningful_since_last} 次有意义对话（总计 {meaningful_total} 次），建议触发自我迭代")

        # 条件 2: 数据库中有意义对话数达标（兜底，防止计数器丢失）
        if db_meaningful_count > 0 and db_meaningful_count % 20 == 0:
            should_optimize = True
            reasons.append(f"数据库中已有 {db_meaningful_count} 条有意义对话记录，建议审视系统")

        # 条件 3: 提示文件中有待处理标记
        if hint_data.get("optimization_pending"):
            should_optimize = True
            reasons.append(hint_data.get("suggested_actions", [{}])[0].get("reason", "有待处理的优化建议"))

        # 条件 4: 有反馈信号
        if hint_data.get("feedback_detected"):
            should_optimize = True
            feedback_type = hint_data.get("feedback_type", "")
            reasons.append(f"检测到用户反馈信号: {feedback_type}")

        # 条件 5: 有大量未使用的工具
        unused = hint_data.get("unused_tools", [])
        if len(unused) > 5 and not should_optimize:
            should_optimize = True
            reasons.append(f"有 {len(unused)} 个工具从未被调用，建议审视是否需要精简")

        reason = "; ".join(reasons) if reasons else ""

        return json.dumps({
            "success": True,
            "should_optimize": should_optimize,
            "reason": reason,
            "stats": stats,
            "conversation_counter": counter,
            "meaningful_since_last_optimize": meaningful_since_last,
            "db_meaningful_count": db_meaningful_count,
            "unused_tools": hint_data.get("unused_tools", []),
            "hot_tools": hint_data.get("hot_tools", []),
            "optimization_pending": hint_data.get("optimization_pending", False),
            "last_optimization_at": _optimization_state.get("last_optimization_at"),
            "hint": "建议调用 self_iterate 进行系统审视（用户画像/技能评估/批评指点/未来规划/MCP工具优化）" if should_optimize else "系统运行正常，暂无需优化",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def mark_optimization_done(action_type: str = "optimize") -> str:
    """
    标记优化/总结已完成。

    在完成 self_iterate 或 daily_summary 后调用此工具，
    清除 optimization_hint.json 提示文件，重置对话计数器，避免重复触发。

    Args:
        action_type: 操作类型
            - "optimize": 标记优化完成，重置有意义对话计数器
            - "summary": 标记总结完成
            - "all": 全部重置

    Returns:
        JSON: {success, reset_stats}
    """
    try:
        now = datetime.now().isoformat()
        with _auto_log_lock:
            if action_type in ("optimize", "all"):
                _optimization_state["last_optimization_at"] = now
                _optimization_state["optimization_pending"] = False
                # 重置对话计数器基准
                counter = _load_conversation_counter()
                counter["last_optimize_count"] = counter.get("total_count", 0)
                _save_conversation_counter(counter)
            if action_type in ("summary", "all"):
                _optimization_state["last_summary_at"] = now
            _save_optimization_state()

            # 清除提示文件
            try:
                from devpartner_agent.core.config import get_config
                hint_path = Path(get_config().data.temp_dir) / "optimization_hint.json"
            except Exception:
                hint_path = _project_root / "data" / "temp" / "optimization_hint.json"
            if hint_path.exists():
                hint_path.unlink()

        stats = _get_tool_call_stats()
        return json.dumps({"success": True, "action": action_type, "stats": stats}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 安全审计 ─────────────────────────────────────────────────
def security_audit(scope: str = "quick") -> str:
    """执行安全审计"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.security_audit(scope)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 系统诊断 ─────────────────────────────────────────────────
def system_diagnose() -> str:
    """系统诊断"""
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db

        issues = []
        checks = {}

        # 数据库检查
        try:
            db = get_db()
            checks["database"] = "healthy"
        except Exception as e:
            checks["database"] = f"unhealthy: {e}"
            issues.append(f"数据库异常: {e}")

        # 日志目录检查
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

        # 规则引擎检查
        try:
            from devpartner_agent.core.rule_engine import get_engine
            engine = get_engine()
            rules = engine.get_all()
            checks["rules"] = f"healthy ({len(rules)} 条规则)"
        except Exception as e:
            checks["rules"] = f"error: {e}"

        return json.dumps({
            "success": True,
            "health": "healthy" if not issues else "degraded",
            "checks": checks,
            "issues": issues,
            "recommendations": ["重启服务"] if issues else []
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 数据完整性检查（v4.3 新增）───────────────────────────────
def check_data_integrity(include_write_stats: bool = True) -> str:
    """
    [v4.3 NEW] 检查数据库数据完整性：关键字段非空 + FK 关联有效性 + 写入成功率。

    检查范围：
    - conversations 表 topic/task_type/skill_domains/feedback_type/analyzed 非空检查
    - 4 张子表 FK 关联有效性（conversations_id 指向有效记录）
    - conversation_archive.analyzed 与 conversations.analyzed 一致性
    - 三大写入链路（record_dialogue/record_conversation/save_self_iterate）成功率

    Args:
        include_write_stats: 是否包含写入成功率统计（默认 true）

    Returns:
        JSON: {success, status, issues, null_fields, orphaned_fks, write_stats}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        from devpartner_agent.services.data_integrity import check_and_log_integrity

        db = get_db()
        result = check_and_log_integrity(db)

        return json.dumps({
            "success": True,
            **result,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 数据清理 ─────────────────────────────────────────────────
def cleanup_data(scope: str = "all", dry_run: bool = False) -> str:
    """
    数据清理（v7.0 增强 — 支持任务级清理）

    scope 取值:
      - "all": 全面清理（对话旧记录 + 软删除任务）
      - "conversations": 仅清理过期对话记录
      - "tasks": 仅清理软删除的任务数据
      - "tasks_force": 强制清理所有软删除任务（忽略保留天数）
      - "stats": 仅返回清理统计信息
    """
    _ensure_core()
    try:
        from devpartner_agent.services.cleanup_scheduler import get_cleanup_scheduler
        from devpartner_agent.services.cleanup_service import get_cleanup_service

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

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# v7.3 对话系统重构：统一为总分总模式（3个工具）
# ============================================================
# 删除了 record_conversation / record_dialogue（冗余入口）
# 统一使用: start_conversation → record_step ×N → finalize_conversation


def _get_project_analysis_strategy(project_id: str) -> dict:
    """
    v4.3: 根据 project_id 返回项目级分析策略，调整各维度的权重和关注点。

    策略分类：
    - database/db → 加重 skills_observed(SQL/ORM)、mistakes(数据完整性)
    - ui/frontend/react → 加重 skills_observed(框架/样式)、behavior_notes
    - ai/ml/model → 加重 tech_interests、skills_observed(算法/训练)
    - infra/ops/devops → 加重 areas_for_growth(稳定性)、decision_pattern
    - default → 通用策略，均匀覆盖 9 维
    """
    pid = (project_id or "").lower()
    strategies = {
        "database": {
            "type": "数据库类项目",
            "focus_dimensions": ["skills_observed", "mistakes"],
            "light_dimensions": ["tech_interests", "emotional_state"],
            "notes": "重点关注 SQL/数据建模/存储方案能力，数据完整性相关错误分析",
        },
        "db": {
            "type": "数据库类项目",
            "focus_dimensions": ["skills_observed", "mistakes"],
            "light_dimensions": ["tech_interests", "emotional_state"],
            "notes": "重点关注 SQL/数据建模/存储方案能力，数据完整性相关错误分析",
        },
        "ui": {
            "type": "前端/UI类项目",
            "focus_dimensions": ["skills_observed", "behavior_notes"],
            "light_dimensions": ["areas_for_growth"],
            "notes": "重点关注前端框架/样式/交互能力，用户的视觉/UX偏好",
        },
        "frontend": {
            "type": "前端/UI类项目",
            "focus_dimensions": ["skills_observed", "behavior_notes"],
            "light_dimensions": ["areas_for_growth"],
            "notes": "重点关注前端框架/样式/交互能力，用户的视觉/UX偏好",
        },
        "react": {
            "type": "前端/UI类项目",
            "focus_dimensions": ["skills_observed", "behavior_notes"],
            "light_dimensions": ["areas_for_growth"],
            "notes": "重点关注前端框架/样式/交互能力，用户的视觉/UX偏好",
        },
        "ai": {
            "type": "AI/ML类项目",
            "focus_dimensions": ["tech_interests", "skills_observed"],
            "light_dimensions": ["communication_style", "decision_pattern"],
            "notes": "重点关注算法/模型/训练/推理能力，用户对AI前沿的关注度",
        },
        "ml": {
            "type": "AI/ML类项目",
            "focus_dimensions": ["tech_interests", "skills_observed"],
            "light_dimensions": ["communication_style", "decision_pattern"],
            "notes": "重点关注算法/模型/训练/推理能力，用户对AI前沿的关注度",
        },
        "model": {
            "type": "AI/ML类项目",
            "focus_dimensions": ["tech_interests", "skills_observed"],
            "light_dimensions": ["communication_style", "decision_pattern"],
            "notes": "重点关注算法/模型/训练/推理能力，用户对AI前沿的关注度",
        },
        "infra": {
            "type": "基础设施类项目",
            "focus_dimensions": ["areas_for_growth", "decision_pattern"],
            "light_dimensions": ["emotional_state"],
            "notes": "重点关注稳定性/监控/性能优化意识，用户的系统架构决策模式",
        },
        "ops": {
            "type": "基础设施类项目",
            "focus_dimensions": ["areas_for_growth", "decision_pattern"],
            "light_dimensions": ["emotional_state"],
            "notes": "重点关注稳定性/监控/性能优化意识，用户的系统架构决策模式",
        },
        "devops": {
            "type": "基础设施类项目",
            "focus_dimensions": ["areas_for_growth", "decision_pattern"],
            "light_dimensions": ["emotional_state"],
            "notes": "重点关注稳定性/监控/性能优化意识，用户的系统架构决策模式",
        },
    }

    # 匹配 project_id 中的关键词
    for keyword, strategy in strategies.items():
        if keyword in pid:
            return strategy

    return {
        "type": "通用策略",
        "focus_dimensions": [],
        "light_dimensions": [],
        "notes": "均匀覆盖全部 9 个维度，无特殊加权",
    }


def _apply_user_traits(traits: dict, source: str, conversations_id: int = None) -> dict:
    """v4.2: 将客户端/LLM 分析的用户特征融合到 MCP 数据层（委托 user_profile_service）"""
    from devpartner_agent.services.user_profile_service import apply_user_traits
    return apply_user_traits(traits, source, conversations_id)


# ── 处理用户反馈（优化闭环入口）───────────────────────────────
def process_user_feedback(tool_name: str, feedback: str,
                           result_content: str = "",
                           conversation_context: str = "") -> str:
    """
    处理用户对 MCP 工具的反馈，自动诊断问题并生成优化方案。

    这是优化闭环的核心入口：
    用户反馈 → 自我检索 → 定位问题（缺工具/描述弱/逻辑错/规则缺失/规则过激）
    → 生成优化方案 → 存入数据库

    Args:
        tool_name: 被反馈的工具名称
        feedback: 用户反馈内容（如"结果不对，缺少xxx信息"）
        result_content: 工具返回的原始结果（用于质量检查）
        conversation_context: 对话上下文（可选）

    Returns:
        JSON: {success, diagnosis, root_cause, optimization_plan}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.optimization_loop import get_optimization_loop

        loop = get_optimization_loop()
        result = loop.process_feedback(
            tool_name=tool_name,
            feedback=feedback,
            result_content=result_content,
            conversation_context=conversation_context,
        )

        return json.dumps({
            "success": True,
            "message": "反馈已处理",
            "root_cause": result["root_cause"],
            "diagnosis": result["diagnosis"],
            "optimization_plan": result["optimization_plan"],
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 获取技能画像 ─────────────────────────────────────────────
def get_skill_profile(domain: str = "") -> str:
    """
    获取个人技能画像，包括各技术领域的熟练度和成长趋势。

    用于：
    - 技能评估：了解自己在各领域的水平分布
    - 职业规划：识别强项和待提升领域
    - 学习建议：基于历史对话数据给出学习方向建议

    Args:
        domain: 指定领域（留空则返回全部）

    Returns:
        JSON: {success, profile, summary, domain_stats, learning_suggestions}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db

        db = get_db()
        profile = db.get_skill_profile(domain if domain else None)
        summary = db.get_skill_summary()
        domain_stats = db.get_domain_stats()

        # 生成学习建议
        suggestions = []
        for ds in domain_stats:
            level = "unknown"
            for p in profile:
                if p["skill_domain"] == ds["skill_domain"]:
                    level = p.get("skill_level", "beginner")
                    break
            hours = ds.get("total_hours", 0) or 0

            if level == "beginner" and hours < 1:
                suggestions.append({
                    "domain": ds["skill_domain"],
                    "suggestion": f"投入时间较少（{hours}h），建议增加实践",
                    "priority": "medium",
                })
            elif level == "intermediate" and hours > 5:
                suggestions.append({
                    "domain": ds["skill_domain"],
                    "suggestion": f"已积累 {hours}h 经验，可挑战更复杂的项目",
                    "priority": "low",
                })

        return json.dumps({
            "success": True,
            "profile": profile,
            "summary": summary,
            "domain_stats": domain_stats,
            "learning_suggestions": suggestions,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 获取优化报告 ─────────────────────────────────────────────
def get_optimization_report() -> str:
    """
    获取 MCP 优化报告：汇总所有待处理的反馈，给出优先级排序的优化建议。

    报告内容包括：
    - 待处理优化数量（按类型分组）
    - 优先级排序的优化建议
    - 技能画像摘要
    - 领域投入统计

    Returns:
        JSON: {success, pending_optimizations, suggestions, skill_summary, ...}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.optimization_loop import get_optimization_loop

        loop = get_optimization_loop()
        report = loop.generate_optimization_report()

        return json.dumps({
            "success": True,
            **report,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 应用优化 ─────────────────────────────────────────────────
def apply_optimization(feedback_id: int) -> str:
    """
    应用指定的优化建议（标记为已处理）。

    Args:
        feedback_id: 优化反馈 ID（来自 get_optimization_report 的结果）

    Returns:
        JSON: {success, message}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.optimization_loop import get_optimization_loop

        loop = get_optimization_loop()
        result = loop.apply_optimization(feedback_id)

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 保存自我迭代结果到数据库（v4.0 新增）────────────────────
def save_self_iterate_results(results_json: str, conversations_id: int = 0) -> str:
    """
    将 self_iterate 的分析结果写入数据库对应表，并执行 MCP 工具优化。

    功能：
    1. 用户画像 → user_skills 表
    2. 技能规划 → user_skill_plan 表
    3. 批评指点 → improvement_log 表（v4.3: 绑定 conversations_id）
    4. 系统反馈 → optimization_feedback 表（v4.3: 绑定 conversations_id）
    5. [v4.1 NEW] MCP 工具优化 → mcp_tool_registry 表
       - 零使用工具 → status='disabled'
       - 高频工具 → 标记需要增强
       - 新增工具建议 → improvement_log

    Args:
        results_json: self_iterate 返回的完整 JSON 结果字符串
        conversations_id: (v4.3) 触发优化的原始会话 ID（关联 conversations.id）

    Returns:
        JSON: {success, saved: {skills, plans, improvements, feedbacks, tools_disabled, tools_enhanced}}
    """
    _ensure_core()
    try:
        results = json.loads(results_json) if isinstance(results_json, str) else results_json
        from devpartner_agent.core.database import get_db
        db = get_db()
        saved = {
            "skills": 0, "plans": 0, "improvements": 0, "feedbacks": 0,
            "tools_disabled": 0, "tools_enhanced": 0,
        }
        now = datetime.now().isoformat()
        # v4.3: conversations_id 默认 0 → None（表示无关联会话）
        _cid = conversations_id if conversations_id > 0 else None

        # ── 1. 用户画像 → user_skills 表 ──
        system_data = results.get("system_data", {})
        user_profile = system_data.get("user_profile", {})
        domain_stats = user_profile.get("domain_stats", [])
        for ds in domain_stats:
            domain = ds.get("skill_domain", "")
            hours = ds.get("total_hours", 0) or 0
            count = ds.get("cnt", 0)
            if domain:
                try:
                    db.upsert_user_skills(domain, {
                        "skill_level": "intermediate" if hours > 3 else "beginner",
                        "sub_skills": "",
                        "evidence": f"来自 self_iterate 分析: {count} 次对话, {hours}h",
                        "conversation_ids": "",
                        "hours_spent": 0,
                        "growth_trend": "stable",
                    })
                    saved["skills"] += 1
                except Exception:
                    pass

        # ── 2. 技能规划建议 → user_skill_plan 表 ──
        suggestions = results.get("suggestions_generated", [])
        for s in suggestions:
            if s.get("category") in ("skill_plan_progress", "future_plan_growth", "learning_suggestion"):
                detail = s.get("detail", {})
                domain = detail.get("domain", "")
                target = detail.get("target", "")
                if domain:
                    try:
                        db.set_skill_plan(
                            domain=domain,
                            goal=s.get("suggestion", "")[:200],
                            target_level=target or "intermediate",
                        )
                        saved["plans"] += 1
                    except Exception:
                        pass

        # ── 3. 批评指点 → improvement_log 表（v4.3: 绑定 conversations_id）──
        for s in suggestions:
            if s.get("category", "").startswith("critique_"):
                try:
                    db.insert_improvement(
                        category=s.get("category", "critique"),
                        suggestion=s.get("suggestion", "")[:500],
                        priority=s.get("priority", "medium"),
                        conversations_id=_cid,
                    )
                    saved["improvements"] += 1
                except Exception:
                    pass

        # ── 4. 系统反馈 → optimization_feedback 表（v4.3: 绑定 conversations_id）──
        for s in suggestions:
            if s.get("category") in ("mcp_tool_cleanup", "mcp_tool_utilization",
                                       "system_feedback", "system_growth",
                                       "mcp_tool_hotspot"):
                try:
                    result = db.insert_optimization_feedback({
                        "source": "self_iterate",
                        "feedback_type": s.get("category", "system"),
                        "description": s.get("suggestion", "")[:500],
                        "suggestion": json.dumps(s.get("detail", {}), ensure_ascii=False),
                        "priority": s.get("priority", "medium"),
                        "status": "applied",  # 自动标记为已应用
                        "conversations_id": _cid,  # v4.3: 关联原始会话
                    })
                    # 获取刚插入的 feedback id，标记 applied
                    feedback_id = result[0].get("last_id") if result else None
                    if feedback_id:
                        db.mark_optimization_applied(
                            feedback_id,
                            result=f"self_iterate 自动执行优化: {s.get('category', '')}"
                        )
                    saved["feedbacks"] += 1
                except Exception:
                    pass

        # ═══════════════════════════════════════════════════════
        # 5. [v4.1 NEW] MCP 工具优化执行 ──
        #   根据 self_iterate 分析结果，自动执行工具状态更新
        # ═══════════════════════════════════════════════════════
        mcp_tool_actions = results.get("mcp_tool_actions", [])
        if not mcp_tool_actions:
            # 兼容旧格式：从 suggestions 中提取 mcp_tool_cleanup 类别的操作
            for s in suggestions:
                if s.get("category") == "mcp_tool_cleanup":
                    detail = s.get("detail", {})
                    action = detail.get("action", "")
                    tool_names = detail.get("unused_sample", [])
                    if action == "disable" and tool_names:
                        mcp_tool_actions.append({
                            "action": "disable",
                            "tool_names": tool_names,
                            "reason": s.get("suggestion", ""),
                        })
                    elif action == "deprecate" and tool_names:
                        mcp_tool_actions.append({
                            "action": "deprecate",
                            "tool_names": tool_names,
                            "reason": s.get("suggestion", ""),
                        })

        for action_item in mcp_tool_actions:
            action = action_item.get("action", "")
            tool_names = action_item.get("tool_names", [])
            reason = action_item.get("reason", "")

            if not tool_names:
                continue

            if action == "disable":
                try:
                    count = db.batch_update_tool_status(tool_names, "disabled")
                    saved["tools_disabled"] += count
                    # 记录到 evolution_log（系统级操作，不绑定 conversations_id）
                    db.log_evolution(
                        change_type="tool_disabled",
                        description=f"self_iterate 自动禁用 {count} 个零使用工具: {', '.join(tool_names[:5])}... 原因: {reason[:200]}",
                        files_changed="mcp_tool_registry",
                        version=VERSION,
                    )
                except Exception:
                    pass

            elif action == "deprecate":
                try:
                    count = db.batch_update_tool_status(tool_names, "deprecated")
                    saved["tools_disabled"] += count
                    db.log_evolution(
                        change_type="tool_deprecated",
                        description=f"self_iterate 标记废弃 {count} 个工具: {', '.join(tool_names[:5])}... 原因: {reason[:200]}",
                        files_changed="mcp_tool_registry",
                        version=VERSION,
                    )
                except Exception:
                    pass

            elif action == "enhance":
                # 高频工具标记为需要增强（记录到 improvement_log）
                for t in tool_names:
                    try:
                        db.insert_improvement(
                            category="tool_enhance",
                            suggestion=f"MCP 工具 [{t}] 使用频率高，建议增强性能/稳定性/描述: {reason[:300]}",
                            priority="high",
                            conversations_id=_cid,
                        )
                        saved["tools_enhanced"] += 1
                    except Exception:
                        pass

        # ── 记录本次优化到 evolution_log（v4.3: 绑定 conversations_id）──
        try:
            db.log_evolution(
                change_type="self_iterate_saved",
                description=f"self_iterate 分析结果已入库: "
                            f"skills={saved['skills']}, plans={saved['plans']}, "
                            f"improvements={saved['improvements']}, feedbacks={saved['feedbacks']}, "
                            f"tools_disabled={saved['tools_disabled']}, tools_enhanced={saved['tools_enhanced']}",
                files_changed="user_skills,user_skill_plan,improvement_log,optimization_feedback,mcp_tool_registry",
                version=VERSION,
                conversations_id=_cid,
            )
        except Exception:
            pass

        # v4.3: 写入成功追踪
        try:
            from devpartner_agent.services.data_integrity import log_write_result
            log_write_result("save_self_iterate", True, f"saved={saved}")
        except Exception:
            pass

        return json.dumps({
            "success": True,
            "message": f"自我迭代结果已写入数据库",
            "saved": saved,
        }, ensure_ascii=False)
    except Exception as e:
        try:
            from devpartner_agent.services.data_integrity import log_write_result
            log_write_result("save_self_iterate", False, str(e)[:200])
        except Exception:
            pass
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 用户画像 CRUD ───────────────────────────────────────────
def get_user_profile(domain: str = "") -> str:
    """
    获取完整的用户画像数据（技能、领域统计、对话历史摘要）。

    这是 MCP 数据层的统一用户画像入口，替代分散在各处的 skill_profile 查询。
    可用于 AI 客户端在会话开始时了解用户背景。

    Args:
        domain: 指定领域（留空则返回全部）

    Returns:
        JSON: {success, profile: {skills, domains, plans, summary}}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        skills = db.get_skill_profile(domain if domain else None)
        summary = db.get_skill_summary()
        domains = db.get_domain_stats()
        plans = db.get_skill_plan(domain if domain else None)

        return json.dumps({
            "success": True,
            "profile": {
                "skills": skills,
                "summary": summary,
                "domain_stats": domains,
                "skill_plans": plans,
            },
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 跨会话记忆管理 ──────────────────────────────────────────
def get_memory(key: str = "") -> str:
    """
    获取跨会话持久记忆（替代本地 MEMORY.md / YYYY-MM-DD.md）。

    用于 AI 客户端在会话开始时恢复历史上下文，或查询特定主题的过往决策。

    Args:
        key: 记忆键（留空则返回最近的所有记忆）

    Returns:
        JSON: {success, memories: [{key, value, timestamp}]}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        try:
            if key:
                rows = db.query_local(
                    "SELECT * FROM conversation_archive WHERE summary LIKE ? ORDER BY timestamp DESC LIMIT 10",
                    (f"%{key}%",)
                )
            else:
                rows = db.query_local(
                    "SELECT * FROM conversation_archive WHERE analyzed = 1 ORDER BY timestamp DESC LIMIT 20"
                )
        except Exception:
            rows = []  # v7.0: 表可能不存在

        memories = []
        for row in rows:
            memories.append({
                "key": row.get("summary", "")[:100],
                "content": row.get("raw_content", "")[:500],
                "timestamp": row.get("timestamp", ""),
                "conversation_id": row.get("conversation_id", ""),
                "skill_domains": row.get("skill_domains", ""),
            })

        return json.dumps({
            "success": True,
            "memories": memories,
            "count": len(memories),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def update_memory(key: str, content: str, category: str = "general") -> str:
    """
    写入/更新跨会话持久记忆。

    替代本地 MEMORY.md 文件写入。记忆以 conversation_archive 形式存储，
    可通过 get_memory() 检索。

    Args:
        key: 记忆主题/键
        content: 记忆内容
        category: 分类（general/preference/decision/lesson）

    Returns:
        JSON: {success, memory_id}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        conv_id = f"memory_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        db.archive_conversation({
            "timestamp": datetime.now().isoformat(),
            "source": "memory",
            "client": "system",
            "conversation_id": conv_id,
            "raw_content": content,
            "summary": f"[{category}] {key}",
            "skill_domains": json.dumps([category], ensure_ascii=False),
            "complexity": "simple",
            "tool_calls": "",
            "user_feedback": "",
        })

        return json.dumps({
            "success": True,
            "memory_id": conv_id,
            "key": key,
            "category": category,
            "message": f"记忆已保存: [{category}] {key}",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 对话检索 ────────────────────────────────────────────────
def search_conversations(keyword: str, limit: int = 10) -> str:
    """
    按关键词检索历史对话记录。

    跨 conversations 和 conversation_archive 两张表搜索，
    帮助 AI 客户端查找相关的历史上下文。

    Args:
        keyword: 检索关键词
        limit: 返回数量上限（默认 10）

    Returns:
        JSON: {success, results: [{source, topic, summary, timestamp, conversation_id}]}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        results = []
        like_kw = f"%{keyword}%"

        # 搜索 conversations 表
        conv_rows = db.query_local(
            """SELECT conversation_id, topic, task_type, timestamp, raw_json
               FROM conversations
               WHERE topic LIKE ? OR user_intent LIKE ? OR problems LIKE ?
               ORDER BY timestamp DESC LIMIT ?""",
            (like_kw, like_kw, like_kw, limit),
        )
        for row in conv_rows:
            results.append({
                "source": "conversations",
                "topic": row.get("topic", ""),
                "task_type": row.get("task_type", ""),
                "timestamp": row.get("timestamp", ""),
                "conversation_id": row.get("conversation_id", ""),
            })

        # 搜索 archive 表（v7.0: 表可能不存在）
        try:
            arch_rows = db.query_local(
                """SELECT conversation_id, summary, complexity, timestamp
                   FROM conversation_archive
                   WHERE summary LIKE ? OR raw_content LIKE ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (like_kw, like_kw, limit),
            )
        except Exception:
            arch_rows = []
        for row in arch_rows:
            results.append({
                "source": "conversation_archive",
                "topic": row.get("summary", ""),
                "task_type": row.get("complexity", ""),
                "timestamp": row.get("timestamp", ""),
                "conversation_id": row.get("conversation_id", ""),
            })

        return json.dumps({
            "success": True,
            "keyword": keyword,
            "results": results[:limit],
            "count": len(results),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 本地 LLM 状态 ─────────────────────────────────────────────
def llm_status(action: str = "status") -> str:
    """
    查看或控制本地 LLM 服务（Ollama）。

    Args:
        action: 操作类型
            - "status": 查看 LLM 配置与运行状态
            - "preload": 手动预加载模型

    Returns:
        JSON: {enabled, model_loaded, model_path, inference_count, ...}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.llm_service import get_llm_service
        llm = get_llm_service()

        if action == "preload":
            loaded = llm.preload()
            status = llm.get_status()
            status["preload_result"] = loaded
            return json.dumps({"success": loaded, **status}, ensure_ascii=False)

        return json.dumps({"success": True, **llm.get_status()}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 版本升级记录 ─────────────────────────────────────────────
def record_version_upgrade(
    version: str = "",
    previous_version: str = "",
    change_summary: str = "",
    changelog: str = "",
    triggered_by: str = "manual",
    bug_fix: str = "",
    new_feature: str = "",
    data_change: str = "",
) -> str:
    """
    手动记录版本升级到 version_history 表。

    在版本发布或重大变更后调用此工具，将变更信息持久化到数据库。
    如果未提供 version，自动从 pyproject.toml 读取当前版本号。

    Args:
        version: 新版本号（留空自动检测）
        previous_version: 上一个版本号
        change_summary: 变更摘要（一句话）
        changelog: 完整变更日志（Markdown 格式）
        triggered_by: 触发方式: manual(手动) / startup(启动检测) / auto(自动)
        bug_fix: Bug 修复说明
        new_feature: 新功能说明
        data_change: 数据变更说明（如 Schema 迁移）

    Returns:
        JSON: {success, version, previous_version, recorded_at}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        from devpartner_agent.core.config import get_project_version

        db = get_db()

        if not version:
            version = get_project_version()

        if not previous_version:
            latest = db.get_latest_version()
            previous_version = latest or "unknown"

        db.record_version(
            version=version,
            previous_version=previous_version,
            change_summary=change_summary,
            changelog=changelog,
            triggered_by=triggered_by,
            bug_fix=bug_fix,
            new_feature=new_feature,
            data_change=data_change,
        )

        import datetime as _dt
        return json.dumps({
            "success": True,
            "version": version,
            "previous_version": previous_version,
            "recorded_at": _dt.datetime.now().isoformat(),
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 文件监控控制 ─────────────────────────────────────────────
def file_watcher_control(action: str = "status",
                          watch_path: str = "",
                          source: str = "") -> str:
    """
    控制文件监控服务：启动/停止/状态/强制扫描。

    Args:
        action: 操作类型
            - "status": 查看监控状态
            - "start": 启动监控（需指定 watch_path）
            - "stop": 停止监控
            - "force_scan": 强制执行一次全量扫描
        watch_path: 监控路径（action=start 时必填）
        source: 客户端来源标识（action=start 时可选）

    Returns:
        JSON: {success, status/message}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.file_watcher import get_watcher

        watcher = get_watcher()

        if action == "status":
            return json.dumps({
                "success": True,
                "status": watcher.get_status(),
            }, ensure_ascii=False)

        elif action == "start":
            if not watch_path:
                return json.dumps({
                    "success": False,
                    "error": "启动监控需要指定 watch_path 参数",
                }, ensure_ascii=False)
            watcher.start(watch_path=watch_path, source=source or None)
            return json.dumps({
                "success": True,
                "message": f"文件监控已启动: {watch_path}",
                "status": watcher.get_status(),
            }, ensure_ascii=False)

        elif action == "stop":
            watcher.stop()
            return json.dumps({
                "success": True,
                "message": "文件监控已停止",
            }, ensure_ascii=False)

        elif action == "force_scan":
            count = watcher.force_scan()
            return json.dumps({
                "success": True,
                "message": f"强制扫描完成，处理了 {count} 个文件",
            }, ensure_ascii=False)

        else:
            return json.dumps({
                "success": False,
                "error": f"未知操作: {action}，支持: status/start/stop/force_scan",
            }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 获取已知领域映射 ─────────────────────────────────────────
def get_skill_domains() -> str:
    """
    获取当前已知的技能领域映射（包括自动发现的新术语）。

    Returns:
        JSON: {success, domains, total_keywords}
    """
    try:
        from devpartner_agent.services.conversation_analyzer import get_analyzer

        analyzer = get_analyzer()
        domains = analyzer.get_known_domains()
        total_kw = sum(len(kws) for kws in domains.values())

        return json.dumps({
            "success": True,
            "domains": {k: len(v) for k, v in domains.items()},
            "total_keywords": total_kw,
            "full_mapping": domains,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 用户画像分析请求（MCP → 客户端主动下发）────────────────
def request_user_profile_analysis(analysis_scope: str = "full",
                                   conversation_id: str = "",
                                   project_id: str = "") -> str:
    """
    [v4.2 NEW] MCP 主动向客户端下发用户全维度画像分析任务。

    这是 MCP→客户端 双向交互的主动下发通道。当 MCP 检测到需要深度分析
    用户画像时（如累计 N 条对话、检测到技能变化趋势等），通过此工具
    返回分析指令，客户端执行分析后通过 record_dialogue 的 user_traits
    参数回传结果。

    分析维度（9 维）：
    1. skills_observed：技术技能观察
    2. behavior_notes：行为模式
    3. mistakes：本次对话中的错误/教训
    4. strengths：强项/优势
    5. communication_style：沟通风格
    6. decision_pattern：决策模式
    7. tech_interests：技术兴趣方向
    8. areas_for_growth：待提升领域
    9. emotional_state：情绪状态

    Args:
        analysis_scope: 分析范围
            - "full": 全维度分析（默认，覆盖全部 9 个维度）
            - "skills": 仅技能维度（skills_observed / tech_interests / areas_for_growth）
            - "behavior": 仅行为维度（behavior_notes / communication_style / decision_pattern）
            - "quick": 快速分析（仅 emotional_state + mistakes）
        conversation_id: 要分析的会话 ID（留空则分析最近一次）
        project_id: 项目标识（用于 MCP 自适应调整分析策略）

    Returns:
        JSON: {
            success,
            analysis_request: {
                scope, dimensions, instructions,
                target_tool: "record_dialogue",
                user_traits_schema: {...},
                return_channel: "调用 record_dialogue 的 user_traits 参数回传"
            }
        }
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        # 确定分析维度
        scope_dimensions = {
            "full": [
                "skills_observed", "behavior_notes", "mistakes", "strengths",
                "communication_style", "decision_pattern", "tech_interests",
                "areas_for_growth", "emotional_state"
            ],
            "skills": ["skills_observed", "tech_interests", "areas_for_growth"],
            "behavior": ["behavior_notes", "communication_style", "decision_pattern"],
            "quick": ["emotional_state", "mistakes"],
        }
        dimensions = scope_dimensions.get(analysis_scope, scope_dimensions["full"])

        # v4.3: 根据 project_id 调整分析策略（加重/减轻维度权重提示）
        project_strategy = _get_project_analysis_strategy(project_id)

        # 如果有 conversation_id，获取对话上下文
        context = {}
        if conversation_id:
            conv_rows = db.query_local(
                "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
            )
            if conv_rows:
                c = conv_rows[0]
                context = {
                    "topic": c.get("topic", ""),
                    "task_type": c.get("task_type", ""),
                    "skill_domains": c.get("skill_domains", ""),
                    "complexity": c.get("complexity", ""),
                }

        # 获取已有用户画像摘要
        profile_summary = db.get_skill_summary()
        recent_skills = db.get_skill_profile()
        recent_plans = db.get_skill_plan()

        return json.dumps({
            "success": True,
            "message": f"已生成 {analysis_scope} 范围的用户画像分析请求",
            "analysis_request": {
                "scope": analysis_scope,
                "dimensions": dimensions,
                "context": context,
                "current_profile": {
                    "summary": profile_summary,
                    "skills": [{"domain": s["skill_domain"], "level": s["skill_level"]}
                               for s in recent_skills[:10]],
                    "plans": [{"domain": p["skill_domain"], "goal": p["goal"][:80]}
                              for p in recent_plans[:5]],
                },
                "target_tool": "record_dialogue",
                "instructions": (
                    f"请对当前用户进行 {analysis_scope} 范围的全维度分析，覆盖以下维度: "
                    f"{', '.join(dimensions)}。分析完成后调用 record_dialogue 工具，"
                    f"将分析结果填入 user_traits 参数（JSON 格式）回传给 MCP。"
                ),
                "user_traits_schema": {
                    "skills_observed": ["string[] - 观察到的技术技能"],
                    "behavior_notes": "string - 行为模式描述",
                    "mistakes": ["string[] - 本次对话中的错误/教训"],
                    "strengths": ["string[] - 用户强项"],
                    "communication_style": "string - 沟通风格（直接/委婉/详细/简洁）",
                    "decision_pattern": "string - 决策模式（数据驱动/直觉/谨慎/大胆）",
                    "tech_interests": ["string[] - 技术兴趣方向"],
                    "areas_for_growth": ["string[] - 需要提升的领域"],
                    "emotional_state": "string - 情绪状态（专注/焦虑/兴奋/疲惫）",
                    "learning_progress": "string - 学习进度观察（可选）",
                },
                "return_channel": "调用 record_dialogue 工具，将分析结果填入 user_traits 参数（JSON字符串）",
                "project_id": project_id,
                "project_strategy": project_strategy,  # v4.3: 项目级分析策略
            },
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── Git 版本控制 ─────────────────────────────────────────────
@mcp.tool()
def git_auto_branch(description: str, base_branch: str = "main") -> str:
    """自动创建 Git 分支"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.git_auto_branch(description, base_branch)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def git_auto_commit(message: str, files: str = "[]",
                    auto_push: bool = False) -> str:
    """自动提交 Git 变更"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        file_list = json.loads(files) if isinstance(files, str) else files
        result = engine.git_auto_commit(message, file_list, auto_push)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def git_auto_push(remote: str = "origin", branch: str = "") -> str:
    """自动推送 Git 变更到远程仓库"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.git_auto_push(remote, branch)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def git_rollback(commit_hash: str = "HEAD~1", hard: bool = False) -> str:
    """Git 回滚"""
    _ensure_core()
    try:
        from devpartner_agent.core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.git_rollback(commit_hash, hard)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 版本记录 & 工具注册
# ============================================================

def _record_version_on_startup():
    """
    启动时记录版本快照（仅版本号 + 工具数，不含 changelog 文本）

    v7.2: 精简为轻量级启动记录。
    - 相同版本重复启动 → 跳过（不污染历史）
    - 版本升级时仅写入 version + tools_count + triggered_by="startup"
    - 完整的 changelog/summary/diff_detail 等 5 个结构化字段
      由人工通过 MCP 工具 record_version_upgrade() 单独填写
    """
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()
        previous = db.get_latest_version()

        if previous == VERSION:
            print(f"[INFO] 版本未变化 ({VERSION})，跳过版本记录")
            return

        total_tools = _tools_count + _agent_tools_count
        if total_tools <= _tools_count:
            try:
                total_tools = len(asyncio.run(mcp._list_tools()))
            except Exception:
                pass
        if total_tools <= 0:
            total_tools = _tools_count

        is_upgrade = previous and previous != VERSION

        db.record_version(
            version=VERSION,
            previous_version=previous or "",
            change_summary=f"v{VERSION} 启动",
            changelog=f"系统启动时自动记录，详细变更请使用 record_version_upgrade() 补充",
            tools_count=total_tools,
            triggered_by="startup",
            diff_detail="",
            optimize_point="",
            bug_fix="",
            new_feature="",
            data_change="",
        )
        if is_upgrade:
            print(f"[INFO] 版本升级: {previous} → {VERSION}（changelog 待补充）")
        else:
            print(f"[INFO] 首次版本记录: {VERSION}")
    except Exception as e:
        print(f"[WARN] 版本记录失败: {e}")


def record_version_upgrade(
    version: str,
    change_summary: str = "",
    changelog: str = "",
    diff_detail: str = "",
    optimize_point: str = "",
    bug_fix: str = "",
    new_feature: str = "",
    data_change: str = "",
) -> str:
    """
    人工记录版本升级信息（补充启动时自动记录的空缺字段）

    启动时 _record_version_on_startup() 仅写入 version + tools_count，
    完整的变更描述由人工通过此工具填写。

    Args:
        version: 版本号（如 "7.3.0"）
        change_summary: 一句话总结（如 "v7.3 性能优化 + 新功能X"）
        changelog: 详细变更描述（支持多行，用分号/换行分隔）
        diff_detail: 代码差异详情
        optimize_point: 优化点说明
        bug_fix: Bug 修复列表
        new_feature: 新功能列表
        data_change: 数据库 Schema 变更

    Returns:
        JSON: {"success": true, "version": "7.3.0", "updated": true}
    """
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        previous = db.get_latest_version() or ""

        db.record_version(
            version=version,
            previous_version=previous,
            change_summary=change_summary or f"v{version} 升级",
            changelog=changelog or f"版本 {version} 发布",
            tools_count=_tools_count + _agent_tools_count,
            triggered_by="manual",
            diff_detail=diff_detail,
            optimize_point=optimize_point,
            bug_fix=bug_fix,
            new_feature=new_feature,
            data_change=data_change,
        )

        return json.dumps({
            "success": True,
            "version": version,
            "previous_version": previous,
            "updated": True,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# v7.3: 对话生命周期管理工具（3个核心工具）
# ══════════════════════════════════════════════════════════════
# start_conversation → record_step ×N → finalize_conversation
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def start_conversation(client: str = "unknown", topic: str = "",
                       task_type: str = "general", user_intent: str = "",
                       priority: str = "medium") -> str:
    """
    【总分总·总】开始一次新对话，创建会话并获取唯一 conversation_id。

    每次有意义的对话开始前都应调用此工具获取会话 ID，
    后续的 record_step 和 finalize_conversation 都需要此 ID。

    对话流程：start_conversation → record_step ×N → finalize_conversation

    Args:
        client: 客户端标识（codebuddy/trae/cursor 等）
        topic: 对话主题（一句话描述）
        task_type: 任务类型（general/debugging/refactoring/learning/testing/deployment/design）
        user_intent: 用户意图描述（可选，帮助后续分析）
        priority: 优先级（low/medium/high/critical）

    Returns:
        JSON: {"conversation_id": "conv_xxx...", "status": "active", ...}
    """
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        mgr = get_conversation_manager()
        conv_id = mgr.create_conversation(
            client=client, topic=topic, task_type=task_type,
            user_intent=user_intent, priority=priority
        )
        status = mgr.get_conversation_status(conv_id)
        return json.dumps(status, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_conversation_status(conversation_id: str) -> str:
    """
    查询会话的详细状态，包括所有步骤的执行进度。

    Args:
        conversation_id: 会话唯一ID（由 start_conversation 返回）

    Returns:
        JSON: 会话详情 + 步骤列表 + 进度百分比
    """
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        mgr = get_conversation_manager()
        status = mgr.get_conversation_status(conversation_id)
        if status is None:
            return json.dumps({"error": f"会话不存在: {conversation_id}"}, ensure_ascii=False)
        return json.dumps(status, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)





def execute_single_step(step_id: str, force_retry: bool = False) -> str:
    """
    执行或重试单个步骤。

    Args:
        step_id: 步骤ID
        force_retry: 是否强制重试（忽略状态检查）

    Returns:
        JSON: 执行结果
    """
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        mgr = get_conversation_manager()
        result = mgr.execute_single_step(step_id, force_retry=force_retry)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# v5.0: 异步任务队列管理工具
# ══════════════════════════════════════════════════════════════

def get_task_status(task_id: str) -> str:
    """
    查询异步任务的状态和进度。

    Args:
        task_id: 任务ID

    Returns:
        JSON: 任务状态、进度、结果等
    """
    try:
        from devpartner_agent.services.task_queue import get_task_queue
        queue = get_task_queue()
        status = queue.get_task_status(task_id)
        if status is None:
            return json.dumps({"error": f"任务不存在: {task_id}"}, ensure_ascii=False)
        return json.dumps(status, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_queue_stats() -> str:
    """
    获取任务队列的统计信息，包括资源使用和并发状态。

    Returns:
        JSON: 队列统计（pending/running 任务数、内存使用、并发槽位等）
    """
    try:
        from devpartner_agent.services.task_queue import get_task_queue
        queue = get_task_queue()
        stats = queue.get_queue_stats()
        return json.dumps(stats, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def cancel_task(task_id: str) -> str:
    """
    取消等待中的异步任务（仅在 pending/queued 状态有效）。

    Args:
        task_id: 任务ID

    Returns:
        JSON: {"success": true/false, "message": "..."}
    """
    try:
        from devpartner_agent.services.task_queue import get_task_queue
        queue = get_task_queue()
        success = queue.cancel_task(task_id)
        return json.dumps({
            "success": success,
            "task_id": task_id,
            "message": "任务已取消" if success else "任务无法取消（可能已在执行或已完成）",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# v5.0: 知识库管理工具
# ══════════════════════════════════════════════════════════════

def list_knowledge_points(domain: str = "", category: str = "",
                          limit: int = 50, offset: int = 0) -> str:
    """
    获取知识库中的知识点列表，支持按领域和分类过滤。

    Args:
        domain: 技术领域过滤（如 Python、前端、DevOps，留空=全部）
        category: 分类过滤（skill/concept/pattern/troubleshooting/best_practice）
        limit: 返回数量上限（默认 50）
        offset: 分页偏移

    Returns:
        JSON: 知识点列表
    """
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        conditions = []
        params = []

        if domain:
            conditions.append("domain = ?")
            params.append(domain)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM knowledge_points {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = db.query_local(sql, tuple(params))
        count_sql = f"SELECT COUNT(*) as total FROM knowledge_points {where}"
        total = db.query_local(count_sql, tuple(params[:-2]))[0]["total"]

        return json.dumps({
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(r) for r in rows],
        }, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def search_knowledge(query: str, domain: str = "", limit: int = 20) -> str:
    """
    搜索知识库中的知识点。

    支持在标题、内容和标签中模糊搜索。

    Args:
        query: 搜索关键词
        domain: 限定技术领域（可选）
        limit: 返回数量上限

    Returns:
        JSON: 匹配的知识点列表
    """
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        params = [f"%{query}%", f"%{query}%"]
        domain_filter = ""
        if domain:
            domain_filter = "AND domain = ?"
            params.append(domain)

        sql = f"""
            SELECT * FROM knowledge_points
            WHERE (title LIKE ? OR content LIKE ?) {domain_filter}
            ORDER BY confidence DESC, usage_count DESC
            LIMIT ?
        """
        params.append(limit)

        rows = db.query_local(sql, tuple(params))
        return json.dumps({
            "query": query,
            "results": len(rows),
            "items": [dict(r) for r in rows],
        }, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def create_knowledge_point(title: str, content: str, domain: str,
                           category: str = "concept", tags_json: str = "[]",
                           difficulty: str = "medium", confidence: float = 0.8) -> str:
    """
    手动创建知识点。

    Args:
        title: 知识点标题
        content: 知识点详细内容
        domain: 技术领域
        category: 分类（skill/concept/pattern/troubleshooting/best_practice）
        tags_json: 标签 JSON 数组，如 '["Python", "设计模式"]'
        difficulty: 难度（easy/medium/hard/expert）
        confidence: 置信度（0.0-1.0）

    Returns:
        JSON: {"knowledge_id": "kp_xxx", ...}
    """
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        mgr = get_conversation_manager()

        tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
        kp_id = mgr._create_knowledge_point(
            title=title, content=content, category=category,
            domain=domain, tags=tags, source_type="manual",
        )

        if kp_id:
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local(
                "UPDATE knowledge_points SET confidence = ?, difficulty = ? WHERE knowledge_id = ?",
                (confidence, difficulty, kp_id),
            )

        return json.dumps({
            "success": bool(kp_id),
            "knowledge_id": kp_id,
            "title": title,
            "domain": domain,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


# ── 知识检索（v7.4.0 扩展：支持 type + project_name 筛选）──────────
@mcp.tool()
def question_with_context(question: str, project_name: str = "",
                           category: str = "", limit: int = 5) -> str:
    """
    基于知识库的智能问答。根据用户问题检索相关的技能知识和业务知识。

    v7.4.0 扩展：
    - 支持 project_name 筛选业务知识（限定 type='business' AND domain=project_name）
    - 支持 category 过滤（skill / business / all）
    - 使用 type 字段区分技能和业务知识（数据层隔离）

    Args:
        question: 用户的问题
        project_name: 项目名称（用于筛选业务知识，不传则返回所有知识）
        category: 知识类型过滤（'skill'/'business'/''，空=全部）
        limit: 返回数量限制（默认 5）

    Returns:
        JSON: {"results": [{"title","content","type","domain","knowledge_id",...}], ...}
    """
    _ensure_core()
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        # 构建查询条件
        conditions = []
        params = []

        # 类型过滤
        if category and category in ("skill", "business"):
            conditions.append("kp.type = ?")
            params.append(category)

        # 项目过滤（仅对 business 类型生效）
        if project_name:
            conditions.append("(kp.type = 'business' AND kp.domain = ?)")
            params.append(project_name)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 先按 question 关键词匹配 title/content（简单的 LIKE 搜索）
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

        rows = db.query_local(sql, tuple(params))

        if not rows:
            # 无精确匹配时返回最相关的记录
            sql_fallback = f"""
                SELECT kp.knowledge_id, kp.title, kp.content, kp.type, kp.domain,
                       kp.tags, kp.category, kp.difficulty, kp.usage_count, kp.created_at
                FROM knowledge_points kp
                WHERE {where_clause}
                ORDER BY kp.usage_count DESC, kp.created_at DESC
                LIMIT ?
            """
            rows = db.query_local(sql_fallback, (*params[:len(params)-2], limit))

        results = []
        for row in (rows or []):
            tags = row.get("tags", "[]")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = [tags]

            # 截取内容摘要（前 300 字符）
            content = row.get("content", "")
            summary = content[:300] + "..." if len(content) > 300 else content

            results.append({
                "knowledge_id": row["knowledge_id"],
                "title": row["title"],
                "summary": summary,
                "type": row.get("type", "skill"),
                "domain": row.get("domain", ""),
                "tags": tags,
                "category": row.get("category", ""),
                "difficulty": row.get("difficulty", "medium"),
                "usage_count": row.get("usage_count", 0),
            })

        return json.dumps({
            "success": True,
            "question": question,
            "project_name": project_name,
            "category_filter": category,
            "total": len(results),
            "results": results,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 知识库全量导出工具（v7.4.0）──
def export_knowledge_to_vault() -> str:
    """
    全量导出所有 auto_synced_to_md=1 的知识点到 Obsidian Vault。

    用于首次同步或修复 MD 文件缺失的情况。
    """
    _ensure_core()
    try:
        from devpartner_agent.services.vault_exporter import get_vault_exporter
        exporter = get_vault_exporter()
        result = exporter.export_all_knowledge()
        return json.dumps({
            "success": True,
            **result,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── Vault 双向同步工具（v7.4.0）──
def sync_vault_to_db(full_scan: bool = False) -> str:
    """
    将 Obsidian Vault 中手动修改的知识卡片同步回数据库。

    场景：用户在 Obsidian 中编辑了知识卡片的标题/内容/标签后，
    调用此工具将修改回写到数据库。

    Args:
        full_scan: True=全量扫描所有文件，False=仅扫描有变更的文件

    Returns:
        JSON: {"synced": N, "skipped": N, "errors": [...]}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.vault_watchdog import get_vault_watchdog
        watchdog = get_vault_watchdog()
        result = watchdog.sync_vault_to_db(full_scan=full_scan)
        return json.dumps({
            "success": True,
            "direction": "vault→db",
            **result,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def start_vault_watchdog(interval: int = 30) -> str:
    """
    启动 Vault 后台自动同步监控。

    启动后，系统会每隔 interval 秒自动扫描 Vault 中的 MD 文件变化，
    并将用户手动修改的内容回写到数据库。

    Args:
        interval: 扫描间隔（秒），默认 30

    Returns:
        JSON: {"running": true, "interval": 30}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.vault_watchdog import get_vault_watchdog
        watchdog = get_vault_watchdog()
        watchdog.start_watchdog(interval=interval)
        return json.dumps({
            "success": True,
            "running": True,
            "interval": interval,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def stop_vault_watchdog() -> str:
    """
    停止 Vault 后台自动同步监控。

    Returns:
        JSON: {"running": false}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.vault_watchdog import get_vault_watchdog
        watchdog = get_vault_watchdog()
        watchdog.stop_watchdog()
        return json.dumps({"success": True, "running": False}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def get_system_health() -> str:
    """
    获取 DevPartner 系统整体健康状态。

    Returns:
        JSON: 会话管理、任务队列、资源使用等综合健康指标
    """
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        from devpartner_agent.services.task_queue import get_task_queue

        mgr = get_conversation_manager()
        queue = get_task_queue()

        conv_health = mgr.get_system_health()
        queue_stats = queue.get_queue_stats()

        from devpartner_agent.core.database import get_db
        db = get_db()
        kp_total = db.query_local("SELECT COUNT(*) as cnt FROM knowledge_points")[0]["cnt"]
        kp_by_domain = db.query_local(
            "SELECT domain, COUNT(*) as cnt FROM knowledge_points GROUP BY domain ORDER BY cnt DESC LIMIT 10"
        )

        return json.dumps({
            "conversation_manager": conv_health,
            "task_queue": queue_stats,
            "knowledge_base": {
                "total_points": kp_total,
                "by_domain": {r["domain"]: r["cnt"] for r in kp_by_domain},
            },
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_v5_status() -> str:
    """
    检查 DevPartner v5.0 升级状态和核心功能可用性。

    Returns:
        JSON: 新表状态、字段完整性、数据统计
    """
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

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

        return json.dumps({
            "version": "5.0",
            "new_tables": new_tables,
            "conversations_fields": v5_columns,
            "total_conversations": total_conv,
            "all_new_tables_exist": all(t["exists"] for t in new_tables.values()),
            "all_v5_columns_exist": all(v5_columns.values()),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_callback_stats() -> str:
    """
    获取回调注册表的统计信息。

    Returns:
        JSON: 活跃注册数、总触发次数、错误计数等
    """
    try:
        from devpartner_agent.services.callback_registry import get_callback_registry
        registry = get_callback_registry()
        stats = registry.get_stats()
        return json.dumps(stats, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════
# v5.2: 知识图谱工具
# ══════════════════════════════════════════════════════════

def build_knowledge_graph(force: str = "false") -> str:
    """
    构建知识图谱索引。从 knowledge_points 表自动分析知识点间的关联关系。

    Args:
        force: "true" 强制重建索引, "false" 仅在未构建时构建

    Returns:
        JSON: 构建统计（节点数、边数、领域数、耗时等）
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        result = kg.build_index(force=(force.lower() == "true"))
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_knowledge_graph_stats() -> str:
    """
    获取知识图谱统计信息。包括节点总数、边总数、Top 领域分布、Hub 节点排名等。

    Returns:
        JSON: 图谱统计信息
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        stats = kg.get_stats()
        return json.dumps(stats, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_knowledge_neighbors(knowledge_id: str, max_depth: str = "1",
                            min_weight: str = "0.3") -> str:
    """
    获取知识图谱中某个知识点的邻居节点。

    Args:
        knowledge_id: 知识点ID（如 kp_20260701_120000_abc12345）
        max_depth: 最大深度（1=直接邻居，2=邻居的邻居）
        min_weight: 最小关联权重（0.0-1.0，默认 0.3）

    Returns:
        JSON: 节点详情及其邻居列表（按权重降序）
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        # Ensure index is built
        kg.build_index()
        result = kg.get_neighbors(
            knowledge_id,
            max_depth=int(max_depth),
            min_weight=float(min_weight),
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def find_knowledge_path(source_id: str, target_id: str,
                        max_depth: str = "5") -> str:
    """
    查找两个知识点之间的最短关联路径（BFS 算法）。

    Args:
        source_id: 起始知识点ID
        target_id: 目标知识点ID
        max_depth: 最大搜索深度（默认 5）

    Returns:
        JSON: 路径节点列表 + 边关系详情
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        kg.build_index()
        result = kg.find_path(source_id, target_id, max_depth=int(max_depth))
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def sync_knowledge_relations(min_weight: str = "0.5") -> str:
    """
    v7.2: 将知识图谱中发现的共现关联同步回 knowledge_points.related_knowledge_ids。

    基于现有图谱边的权重筛选高质量关联（≥ min_weight），
    以逗号分隔的 knowledge_id 列表写回数据库。

    Args:
        min_weight: 最小关联权重阈值（0.0-1.0，默认 0.5）

    Returns:
        JSON: {"updated": N, "skipped": M, "nodes_with_relations": K}
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        kg.build_index()
        result = kg.sync_relations_to_db(min_weight=float(min_weight))
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def get_knowledge_cluster(domain: str = "", tag: str = "") -> str:
    """
    获取某个领域或标签的知识点聚类。

    Args:
        domain: 按领域过滤（如 "Python", "Database"）
        tag: 按标签过滤（如 "async", "testing"）
              domain 和 tag 至少提供一个

    Returns:
        JSON: 聚类节点列表 + 内部边关系
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        kg.build_index()
        result = kg.get_cluster(domain=domain or None, tag=tag or None)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


def export_knowledge_graph(format: str = "nodes_and_edges") -> str:
    """
    导出知识图谱数据，用于外部可视化（如 D3.js、Gephi）。

    Args:
        format: 导出格式 - "nodes_and_edges" (默认) 或 "adjacency"

    Returns:
        JSON: 图数据（nodes + edges 或 adjacency list）
    """
    try:
        from devpartner_agent.services.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        kg.build_index()
        result = kg.export_graph(format=format)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# v7.3: 总分总对话分析 — record_step + finalize_conversation
# ══════════════════════════════════════════════════════════════

@mcp.tool()
def record_step(conversation_id: str, step_name: str, step_type: str = "general",
                content: str = "", files_changed: str = "",
                symptom: str = "", root_cause: str = "", solution: str = "",
                knowledge_points: str = "", user_question: str = "") -> str:
    """
    【总分总·分】记录对话中一个子任务的详细信息，提交到后台异步分析。

    设计理念：
      - 对话被拆分为多个子任务（todo items），每个子任务完成后立即调用此工具
      - 数据提交后立即返回，不阻塞 Agent 继续处理下一个任务
      - 后端异步执行：内容分析 → 知识点提取 → 用户画像更新

    调用时机：
      每完成一个 todo 项（文件修改、问题排查、配置变更等）后立即调用。

    Args:
        conversation_id: 会话唯一ID（由 start_conversation 返回）
        step_name: 步骤名称（对应 todo 项名称，如 "修复数据库锁问题"）
        step_type: 步骤类型
            - "code_change": 代码变更（创建/修改/删除文件）
            - "debug": 问题排查与修复
            - "config": 配置变更
            - "design": 架构/设计决策
            - "learn": 知识学习与研究
            - "deploy": 部署/运维操作
            - "general": 其他
        content: 本步骤的详细描述（做了什么、为什么这样做、关键决策点）
        files_changed: 修改的文件列表（JSON数组字符串，如 '["server.py","database.py"]'）
        symptom: 问题现象（如果是排查类步骤）
        root_cause: 根因分析（如果是排查类步骤）
        solution: 解决方案（如果是排查类步骤）
        knowledge_points: 本步骤沉淀的知识点（JSON数组，格式 [{"title":"xxx","desc":"yyy"}]）
        user_question: 触发本步骤的原始用户问题（可选）

    Returns:
        JSON: {"success": true, "step_id": "xxx", "queued": true, ...}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        from devpartner_agent.services.task_queue import get_task_queue
        from devpartner_agent.core.database import get_db

        db = get_db()
        mgr = get_conversation_manager()
        queue = get_task_queue()

        # v6.0.3: FK 自保护 — 确保会话父行存在，规避 create/record 跨请求可见性竞态
        # （共享 WAL 连接的读快照可能尚未看到刚创建的会话，导致 conversation_steps FK 失败）
        mgr.ensure_conversation_exists(conversation_id, client="codebuddy", topic=step_name[:200] or "自动创建的会话")

        # 解析参数
        def _safe_json(val, default):
            if not val: return default
            if isinstance(val, (list, dict)): return val
            try: return json.loads(val)
            except (json.JSONDecodeError, TypeError): return default

        files_list = _safe_json(files_changed, [])
        kp_list = _safe_json(knowledge_points, [])

        # 创建步骤
        step_id = f"{conversation_id}_step_{datetime.now().strftime('%H%M%S%f')}"

        # 构建步骤输入数据
        # v6.0.2: 移除硬截断 — 总分总模式下每个 task 数据量小且精确，截断会丢失关键信息
        # 仅保留安全上限（防止极端情况），正常使用不会触发
        step_input = {
            "step_name": step_name,
            "step_type": step_type,
            "content": content[:100000] if content else "",
            "files_changed": files_list,
            "symptom": symptom[:50000] if symptom else "",
            "root_cause": root_cause[:50000] if root_cause else "",
            "solution": solution[:50000] if solution else "",
            "knowledge_points": kp_list,
            "user_question": user_question[:10000] if user_question else "",
            "recorded_at": datetime.now().isoformat(),
        }

        # 写入 conversation_steps 表
        db.query_local("""
            INSERT INTO conversation_steps (
                step_id, conversation_id, step_order, step_type,
                step_name, status, input_data, max_retries,
                timeout_seconds, priority, depends_on, created_at
            ) VALUES (?, ?,
                (SELECT COALESCE(MAX(step_order), 0) + 1 FROM conversation_steps WHERE conversation_id = ?),
                'analysis', ?, 'pending', ?, 3, 300, 5, '', ?
            )
        """, (
            step_id, conversation_id, conversation_id,
            step_name, json.dumps(step_input, ensure_ascii=False),
            datetime.now().isoformat()
        ))

        # v7.2: 设置 started_at 为当前时间
        db.query_local("""
            UPDATE conversation_steps SET started_at = ? WHERE step_id = ?
        """, (datetime.now().isoformat(), step_id))

        # 更新会话总步骤数
        total = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversation_steps WHERE conversation_id = ?",
            (conversation_id,)
        )[0]["cnt"]
        db.query_local("""
            UPDATE conversations SET total_steps = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (total, datetime.now().isoformat(), conversation_id))

        # 提交异步分析任务
        # v6.0.2: 数据不截断 — task 粒度小，保留完整信息
        task_payload = {
            "conversation_id": conversation_id,
            "step_id": step_id,
            "step_name": step_name,
            "step_type": step_type,
            "content": content[:100000] if content else "",
            "knowledge_points": kp_list,
            "files_changed": files_list,
            "symptom": symptom[:50000] if symptom else "",
            "root_cause": root_cause[:50000] if root_cause else "",
            "solution": solution[:50000] if solution else "",
        }

        task_id = queue.submit_task(
            task_type="step_analysis",
            payload=task_payload,
            priority=8,  # 中等偏高优先级
            estimated_memory_mb=100,
        )

        return json.dumps({
            "success": True,
            "step_id": step_id,
            "task_id": task_id,
            "queued": True,
            "conversation_id": conversation_id,
            "total_steps": total,
        }, ensure_ascii=False)

    except Exception as e:
        error_msg = str(e)
        print(f"[record_step] ERROR: {error_msg}")
        
        # v6.0.1: FK 约束自修复 — 如果 FOREIGN KEY 失败，自动尝试修复
        if "FOREIGN KEY" in error_msg.upper():
            try:
                from devpartner_agent.core.database import get_db
                db = get_db()
                cursor = db._local_conn.cursor()
                
                # 1. 确保 conversations.conversation_id 有 UNIQUE 索引
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique 
                    ON conversations(conversation_id)
                """)
                
                # 2. 确保会话记录存在
                exists = cursor.execute(
                    "SELECT id FROM conversations WHERE conversation_id = ?",
                    (conversation_id,)
                ).fetchone()
                
                if not exists:
                    ts = datetime.now().isoformat()
                    cursor.execute("""
                        INSERT INTO conversations (conversation_id, timestamp, client, topic, task_type, status, priority, created_at, updated_at)
                        VALUES (?, ?, 'codebuddy', ?, 'general', 'active', 'medium', ?, ?)
                    """, (conversation_id, ts,
                          step_name[:200] if step_name else '自动创建',
                          ts, ts))
                    db._local_conn.commit()
                    print(f"[record_step] ✅ 自动创建 conversations 记录: {conversation_id}")
                
                # 3. FK 修复后重试
                print(f"[record_step] 🔄 FK 已修复，重试 INSERT...")
                step_id = f"{conversation_id}_step_{datetime.now().strftime('%H%M%S%f')}"
                step_input = {
                    "step_name": step_name,
                    "step_type": step_type,
                    "content": content[:100000] if content else "",
                    "files_changed": files_list,
                    "symptom": symptom[:50000] if symptom else "",
                    "root_cause": root_cause[:50000] if root_cause else "",
                    "solution": solution[:50000] if solution else "",
                    "knowledge_points": kp_list,
                    "user_question": user_question[:10000] if user_question else "",
                    "recorded_at": datetime.now().isoformat(),
                }
                db.query_local("""
                    INSERT INTO conversation_steps (
                        step_id, conversation_id, step_order, step_type,
                        step_name, status, input_data, max_retries,
                        timeout_seconds, priority, depends_on, created_at
                    ) VALUES (?, ?,
                        (SELECT COALESCE(MAX(step_order), 0) + 1 FROM conversation_steps WHERE conversation_id = ?),
                        'analysis', ?, 'pending', ?, 3, 300, 5, '', ?
                    )
                """, (
                    step_id, conversation_id, conversation_id,
                    step_name, json.dumps(step_input, ensure_ascii=False),
                    datetime.now().isoformat()
                ))
                
                print(f"[record_step] ✅ FK 自修复后重试成功: {step_id}")
                return json.dumps({
                    "success": True,
                    "step_id": step_id,
                    "auto_repaired": True,
                    "conversation_id": conversation_id,
                }, ensure_ascii=False)
                
            except Exception as retry_err:
                print(f"[record_step] ❌ FK 自修复失败: {retry_err}")
                return json.dumps({
                    "success": False, 
                    "error": str(e),
                    "repair_error": str(retry_err),
                    "hint": "请重启服务器以完成数据库迁移"
                }, ensure_ascii=False)
        
        return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)


@mcp.tool()
def finalize_conversation(conversation_id: str, summary: str = "",
                          user_traits: str = "",
                          key_decisions: str = "",
                          knowledge_graph: str = "",
                          self_reflection: str = "") -> str:
    """
    【总分总·总】对话结束时调用，提交全局总结并触发全面分析。

    设计理念：
      - 所有子任务完成后，对整个对话做全局视角的分析
      - 分析维度：技术决策链、用户画像演进、知识图谱更新、系统优化建议
      - 异步执行，不阻塞客户端

    调用时机：
      对话中所有 todo 项完成、record_step 全部调用完毕后调用。
      短对话（无需拆分步骤）可直接在 start_conversation 后调用，跳过 record_step。

    Args:
        conversation_id: 会话唯一ID（由 start_conversation 返回）
        summary: 对话全局总结（技术要点、关键决策、值得记住的解决方案）
        user_traits: 用户画像特征（JSON）
            包含: skills_observed, behavior_notes, mistakes, strengths,
                  communication_style, decision_pattern, tech_interests, areas_for_growth
        key_decisions: 关键决策列表（JSON数组，每项 {"decision":"xxx","reason":"yyy","tradeoff":"zzz"}）
        knowledge_graph: 本次对话涉及的知识关联（JSON，格式 {"nodes":[],"edges":[]}）
        self_reflection: AI 自我复盘（聚焦机制/架构缺陷，不重复描述故障）

    Returns:
        JSON: {"success": true, "conversation_id": "xxx", "analysis_queued": true, ...}
    """
    _ensure_core()
    try:
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        from devpartner_agent.services.task_queue import get_task_queue
        from devpartner_agent.core.database import get_db

        db = get_db()
        mgr = get_conversation_manager()
        queue = get_task_queue()

        def _safe_json(val, default):
            if not val: return default
            if isinstance(val, (list, dict)): return val
            try: return json.loads(val)
            except (json.JSONDecodeError, TypeError): return default

        decisions_list = _safe_json(key_decisions, [])
        kg_data = _safe_json(knowledge_graph, {})
        traits_data = _safe_json(user_traits, {})

        # 更新 conversations 表的全局总结字段
        # v6.0.2: 数据不截断 — 全局总结不应丢失关键信息
        db.query_local("""
            UPDATE conversations SET
                self_reflection = ?,
                updated_at = ?
            WHERE conversation_id = ?
        """, (self_reflection[:50000] if self_reflection else "", datetime.now().isoformat(), conversation_id))

        # 如果有关键决策，写入 actions 字段
        if decisions_list:
            db.query_local("""
                UPDATE conversations SET
                    decisions = ?
                WHERE conversation_id = ?
            """, (json.dumps(decisions_list, ensure_ascii=False)[:50000], conversation_id))

        # 提交全局分析任务（异步）
        final_payload = {
            "conversation_id": conversation_id,
            "summary": summary[:50000] if summary else "",
            "user_traits": traits_data,
            "key_decisions": decisions_list,
            "knowledge_graph": kg_data,
            "self_reflection": self_reflection[:50000] if self_reflection else "",
            "finalized_at": datetime.now().isoformat(),
        }

        task_id = queue.submit_task(
            task_type="conversation_finalize",
            payload=final_payload,
            priority=10,  # 高优先级：全局分析很重要
            estimated_memory_mb=200,
        )

        # 标记会话为已完成
        mgr.complete_conversation(conversation_id)

        # v7.0: 标记总结已生成（清理前置校验） + 触发软删除
        db.query_local("""
            UPDATE conversations SET summary_generated = 1, updated_at = ?
            WHERE conversation_id = ?
        """, (datetime.now().isoformat(), conversation_id))

        # 异步软删除：不在主流程中阻塞
        def _soft_delete():
            try:
                from devpartner_agent.services.cleanup_service import get_cleanup_service
                cs = get_cleanup_service()
                cs.soft_delete_conversation_tasks(conversation_id)
            except Exception as e:
                logger.warning(f"软删除失败（非致命）: {e}")

        threading.Thread(target=_soft_delete, daemon=True).start()

        return json.dumps({
            "success": True,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "analysis_queued": True,
            "analysis_dimensions": [
                "技术决策链分析",
                "用户画像更新",
                "知识图谱构建",
                "系统优化建议",
                "对话质量评估",
            ],
        }, ensure_ascii=False)

    except Exception as e:
        print(f"[finalize_conversation] ERROR: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _register_all_tools_to_db():
    """将所有已注册的 MCP 工具持久化到数据库"""
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        registered = 0
        for tool_name in _all_tool_names:
            db.register_tool(
                tool_name=tool_name,
                module="devpartner",
                description=f"MCP工具: {tool_name}",
                version=VERSION,
            )
            registered += 1

        print(f"[INFO] MCP 工具已注册到数据库: {registered} 个")
    except Exception as e:
        print(f"[WARN] MCP 工具注册到数据库失败: {e}")

# 工具名收集
_all_tool_names = []
_agent_tools_count = 0

def _collect_tool_names():
    """从 mcp 实例中收集所有已注册的工具名"""
    global _all_tool_names, _agent_tools_count
    try:
        _all_tool_names = sorted(t.name for t in asyncio.run(mcp._list_tools()))
        _agent_tools_count = len(_all_tool_names) - _tools_count
        if _agent_tools_count < 0:
            _agent_tools_count = 0
    except Exception:
        pass


# ============================================================
# 启动入口
# ============================================================

ALLOWED_PORTS = {7860, 8080}
DEFAULT_PORT = 7860

if __name__ == "__main__":
    print("")
    print(f"  工具层: {_tools_count} 个纯工具")
    agent_ok = _ensure_core()
    print(f"  管家层: {'已加载' if agent_ok else '降级模式'}")
    print("")

    # 记录版本到数据库（必须在 _collect_tool_names 之前调用，因为需要 tools_count）
    _record_version_on_startup()

    # 收集所有工具名并注册到数据库
    _collect_tool_names()
    _register_all_tools_to_db()

    print("")
    print("  能力: 文件系统 | Git | Web | 推理 | MCP发现 | 系统工具")
    print("        对话记录 | 模块协作 | 自我进化 | 数据清理")
    print("        审批链 | 能力授权 | 注册表 | 并行任务分解")
    print("        日志管理 | 每日总结 | 系统诊断 | 规则检测")
    print("        热重载 | 安全审计 | Git版本控制")
    print("        [NEW v7.3.0] Ollama引擎 | 总分总会话 | 知识图谱 | 双向仪表盘")
    print("=" * 60)

    # ============================================================
    # v6.0: 统一启动逻辑 - MCP 服务（本地和云端完全一致）
    # ============================================================
    #
    # 🎯 核心原则: 本地和云端都是 MCP 服务，无本质区别！
    #
    # 系统架构:
    #   devpartner_tools/  → 工具层 (21个纯工具, 无状态)
    #   devpartner_agent/  → 智能管家层 (67+个智能工具, 有状态)
    #   server.py          → MCP 服务入口 (统一对外接口)
    #
    # 部署方式:
    #   1. 本地开发: python server.py 7860
    #      → 访问地址: http://127.0.0.1:7860/mcp
    #
    #   2. ModelScope云端: Dockerfile自动构建
    #      → 访问地址: https://modelscope.cn/studios/Pisces43/Dev-partner/mcp
    #
    # 协议 (v6.0):
    #   ✅ Streamable HTTP + /mcp 端点（统一标准）
    #   ❌ SSE协议已废弃
    #
    # 端口:
    #   统一使用 7860（ModelScope要求）
    #
    # ============================================================

    def _run_mcp_service(port):
        """启动 MCP 服务（Streamable HTTP + /mcp 端点）"""

        import os

        # 检测当前环境
        is_docker = os.path.exists("/.dockerenv")
        is_modelscope = os.environ.get("MODELSCOPE_ENVIRONMENT") == "true"

        if is_docker or is_modelscope:
            env_name = "ModelScope 云端" if is_modelscope else "Docker 容器"
            access_url = f"https://modelscope.cn/studios/Pisces43/Dev-partner/mcp"
        else:
            env_name = "本地开发"
            access_url = f"http://127.0.0.1:{port}/mcp"

        print("  启动模式: MCP 服务 (Streamable HTTP)")
        print(f"  运行环境: {env_name}")
        print(f"  监听端口: {port}")
        print(f"  MCP端点: {access_url}")
        print("")
        print("  [系统架构]")
        print("     [工具层] devpartner_tools: 21个纯工具 (无状态)")
        print("     [智能层] devpartner_agent: 67+个智能工具 (有状态)")
        print("")
        print("  [可用功能]")
        print(f"     [MCP] POST {access_url}")
        print(f"     [仪表盘] http://localhost:{port}/dashboard")
        print(f"     [API文档] http://localhost:{port}/docs")
        print(f"     [健康检查] http://localhost:{port}/health")
        print("")
        print("  待命状态: 等待 MCP 客户端连接...")
        print("=" * 60)

        # 启动 Streamable HTTP 服务
        # v6.0.3: CORSMiddleware 作为 ASGI 中间件传入，解决 ModelScope 跨域问题
        # 使用 starlette.middleware.Middleware 包装，符合 Starlette 中间件注册规范
        from starlette.middleware import Middleware as _Middleware
        from starlette.middleware.cors import CORSMiddleware as _CORSMiddleware
        
        # v6.0.4: 禁用 Accept header 强制检查
        # CodeBuddy 等 MCP 客户端可能不发送 Accept: application/json
        # 但 mcp 0.x 内部严格要求，否则返回 406 Not Acceptable
        try:
            from mcp.server.streamable_http import StreamableHTTPServerTransport as _ST
            if not getattr(_ST._validate_accept_header, '_patched', False):
                async def _patched_validate(self, request, scope, send):
                    return True
                _ST._validate_accept_header = _patched_validate
                _ST._validate_accept_header._patched = True
                print("[INFO] Accept header 检查已禁用 (兼容 CodeBuddy 等 MCP 客户端)")
        except Exception as _e:
            print(f"[WARN] Accept header 补丁失败: {_e}")
        
        mcp.run(transport="streamable-http",
                 host="0.0.0.0",
                 port=port,
                 json_response=True,
                 stateless_http=True,
                 middleware=[_Middleware(
                     _CORSMiddleware,
                     allow_origins=["*"],
                     allow_credentials=True,
                     allow_methods=["*"],
                     allow_headers=["*"],
                     expose_headers=["Mcp-Session-Id"],
                 )])

    # 判断启动模式
    if len(sys.argv) > 1:
        arg = sys.argv[1]

        # 模式1: 提供端口号 → 启动 MCP 服务
        if arg.isdigit():
            port = int(arg)
            if port not in ALLOWED_PORTS:
                print(f"[ERROR] 不允许的端口 {port}，仅支持: {sorted(ALLOWED_PORTS)}")
                sys.exit(1)
            _run_mcp_service(port)

        # 模式2: 兼容旧的 "sse" 参数（已废弃）
        elif arg.lower() in ["sse", "streamable"]:
            port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
            if port not in ALLOWED_PORTS:
                print(f"[ERROR] 不允许的端口 {port}，仅支持: {sorted(ALLOWED_PORTS)}")
                sys.exit(1)
            print(f"  ⚠️ 已弃用: '{arg}' 参数将在未来版本移除")
            print(f"  请直接使用端口号: python server.py {port}")
            _run_mcp_service(port)

        else:
            print(f"[ERROR] 未知参数: {arg}")
            print("")
            print("  用法:")
            print("    python server.py 7860          # 启动 MCP 服务（推荐）")
            print("")
            print("  说明:")
            print("    本地和云端都是 MCP 服务，统一使用 Streamable HTTP 协议")
            print("    端口固定为 7860，MCP 端点为 /mcp")
            sys.exit(1)
    else:
        # 无参数: 默认启动 MCP 服务（端口 7860）
        print("  [INFO] 未指定端口，使用默认配置")
        print("  [INFO] 启动 MCP 服务 (端口: 7860)")
        _run_mcp_service(DEFAULT_PORT)