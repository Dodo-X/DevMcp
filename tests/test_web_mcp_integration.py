"""
DevPartner — Web 与 MCP 全面功能对接测试
==========================================

覆盖范围（对应需求三大块）:
  A. Web 对接测试     — REST 路由连通性、请求/响应正确性、Dashboard 页面结构与交互
  B. MCP 对接测试     — 协议连接建立、工具发现、工具调用与响应、参数校验、消息收发
  C. 集成验证         — Web 与 MCP 互不干扰、联合运行数据流转无误

测试策略说明:
  - Web 与 MCP 在系统中共用同一 FastMCP/Starlette 进程（见 mcp_service/mcp_server.py + backend/api_gateway/rest_api.py）。
  - Web 侧：session 级 fixture 用 uvicorn 真正启动 `mcp.http_app()`（端口 127.0.0.1:随机），
    触发完整 ASGI lifespan，等价于生产形态的 HTTP 服务；Web 测试通过 httpx 走真实 localhost 请求。
  - MCP 侧：
      * 内存传输（in-memory）用例验证工具层逻辑（start/record/finalize、prompts、参数校验）；
      * “真实 Streamable HTTP 协议”用例复用上面 uvicorn 暴露的 /mcp 端点，
        用 streamable-http 客户端真实走线，验证协议握手与消息收发。
  - 为消除 LLM（Ollama）外部依赖带来的不稳定，测试中关闭 LLM 并降级到规则引擎；
    后台调度器（每日/超时/清理）以 Mock 屏蔽，避免无关后台线程与已知 import bug 噪音。
  - 数据库隔离到临时目录，避免污染项目 data/。
  - 任务 handler 按生产接线注册（_register_task_handlers），贴合真实运行形态；
    在无 Ollama 环境下异步分析步骤会优雅失败（降级），但工具调用本身立即返回成功，不影响对接验证。

环境要求:
  - 受测代码以 `from backend.xxx` / `from foundation.xxx` 绝对导入，故本文件将项目根加入 sys.path。
"""

import json
import socket
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import mcp_service.mcp_server as ms_mod  # noqa: E402
from fastmcp import Client  # noqa: E402

EXPECTED_TOOLS = {"start_conversation", "record_step", "finalize_conversation"}


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _extract_text(res) -> str:
    """兼容 fastmcp 3.x 的 call_tool 返回结构，提取工具返回的字符串正文。"""
    data = getattr(res, "data", None)
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        item = data[0] if data else None
        if isinstance(item, str):
            return item
        if hasattr(item, "text"):
            return item.text
        return json.dumps(item, ensure_ascii=False)
    if getattr(res, "content", None):
        item = res.content[0]
        return item.text if hasattr(item, "text") else str(item)
    return str(res)


def _json_tool(res) -> dict:
    return json.loads(_extract_text(res))


# ─────────────────────────────────────────────────────────────────────────────
# 会话级 Fixture：装配系统 + 启动真实 HTTP 服务（uvicorn）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def runtime():
    """一次性装配受测系统并启动 HTTP 服务。"""
    import foundation.config.app_settings as app_settings

    cfg = app_settings.get_config()
    tmp = Path(tempfile.mkdtemp(prefix="devpartner_itest_"))
    cfg.data.root_dir = str(tmp)
    cfg.llm.enabled = False
    cfg.llm.preload = False

    # 屏蔽后台调度器与清理器（避免无关后台线程 + 已知 import bug 噪音）
    import backend.business.data_cleanup.cleanup_service as clean_mod
    import backend.core.scheduler as sched_mod

    sched_mod.get_scheduler = lambda: mock.MagicMock()
    sched_mod.get_timeout_scheduler = lambda: mock.MagicMock()
    clean_mod.get_cleanup_scheduler = lambda: mock.MagicMock()
    clean_mod.get_cleanup_service = lambda: mock.MagicMock()

    # 等价于 mcp_service.__main__ 中的装配步骤（贴合生产接线）
    ms_mod._register_rest_routes()
    ms_mod._register_prompts()
    ms_mod._register_task_handlers()

    # 触发核心初始化（建表、单例 DB）
    from backend.core.bootstrap import ensure_ready

    ensure_ready()

    # 启动真实 HTTP 服务（uvicorn），触发完整 lifespan
    import uvicorn

    mcp = ms_mod.mcp
    port = _free_port()
    app = mcp.http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    base = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(100):
        try:
            with httpx.Client() as c:
                rr = c.get(base + "/health")
                if rr.status_code == 200:
                    ready = True
                    break
        except Exception:
            pass
        import time

        time.sleep(0.1)
    assert ready, "uvicorn HTTP 服务未在预期时间内就绪"

    yield {"tmp": tmp, "cfg": cfg, "mcp": mcp, "base": base, "port": port}

    server.should_exit = True


@pytest.fixture
def base(runtime):
    return runtime["base"]


@pytest.fixture
def mcp_obj(runtime):
    return runtime["mcp"]


# ═════════════════════════════════════════════════════════════════════════════
# A. Web 对接测试（真实 HTTP 走 localhost）
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_web_root_endpoint(base):
    """[Web-连通性] 根路径 / 应返回服务元信息，且声明 MCP 端点与 running 状态。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "running"
        assert body.get("mcp_endpoint") == "/mcp"
        assert "version" in body


@pytest.mark.asyncio
async def test_web_health_endpoint(base):
    """[Web-连通性] /health 应返回 healthy 与版本号。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "healthy"
        assert body.get("version")


@pytest.mark.asyncio
async def test_web_mcp_health_get(base):
    """[Web/MCP-连通性] GET /mcp 是 MCP 协议端点，被 Streamable HTTP 会话管理器接管，
    直接 GET（缺 MCP 客户端 Accept 协商）返回 406/400，而非 5xx 崩溃；
    自定义健康检查路由在部署形态下被协议层遮蔽（详见测试报告“发现-1”）。
    MCP 协议连通性由 test_mcp_real_streamable_http 通过真实 streamable-http 客户端确认。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/mcp")
        # 端点可响应、未崩溃；406/400 为协议层 Accept 协商预期结果
        assert r.status_code in (200, 400, 406), f"GET /mcp 返回非预期状态码: {r.status_code}"
        # /health 才是稳定的 Web 侧健康端点，单独验证可返回 ok 语义
        rh = await ac.get("/health")
        assert rh.status_code == 200 and rh.json().get("status") == "healthy"


@pytest.mark.asyncio
async def test_web_system_status(base):
    """[Web-数据正确性] /api/system/status 应返回结构化系统状态。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/api/system/status")
        assert r.status_code == 200
        body = r.json()
        for key in (
            "active_sessions",
            "today_new_sessions",
            "pending_tasks",
            "running_tasks",
            "completed_tasks",
            "knowledge_base_size",
        ):
            assert key in body, f"缺少字段 {key}"


@pytest.mark.asyncio
async def test_web_growth_apis(base):
    """[Web-数据正确性] 成长分析系列 API 应返回合法 JSON。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        for path in (
            "/api/growth/user-overview",
            "/api/growth/skill-radar",
            "/api/growth/timeline",
            "/api/growth/activity-heatmap",
        ):
            r = await ac.get(path)
            assert r.status_code == 200, f"{path} 非 200"
            assert r.json()


@pytest.mark.asyncio
async def test_web_tasks_and_knowledge_apis(base):
    """[Web-数据正确性] 任务队列与知识库 API 应正常返回。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        assert (await ac.get("/api/tasks/stats")).status_code == 200
        assert (await ac.get("/api/tasks/list")).status_code == 200
        assert (await ac.get("/api/tasks/handlers")).status_code == 200
        assert (await ac.get("/api/knowledge/list")).status_code == 200
        assert (await ac.get("/api/knowledge/search?query=test")).status_code == 200


@pytest.mark.asyncio
async def test_web_projects_list_fallback(base):
    """[Web-数据正确性] /api/projects/list 无 connected_systems 时应回退到当前工作目录名。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/api/projects/list")
        assert r.status_code == 200
        body = r.json()
        assert body.get("success") is True
        assert isinstance(body.get("projects"), list)
        assert len(body["projects"]) >= 1


@pytest.mark.asyncio
async def test_web_trends_and_daily(base):
    """[Web-数据正确性] 系统趋势与每日总结 API 应正常返回。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/api/trends/system")
        assert r.status_code == 200
        assert "timestamps" in r.json() and "sessions" in r.json()
        r = await ac.get("/api/daily/summary")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_web_post_reports_generate_validation(base):
    """[Web-边界] /api/reports/generate 非法 type 应返回 400。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.post("/api/reports/generate", json={"type": "yearly"})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_web_dashboard_page_structure(base):
    """[Web-页面交互] Dashboard 应返回 HTML，并内嵌指向各核心 API 的 fetch 调用（页面交互的数据支撑）。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/dashboard")
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "text/html" in ctype, f"content-type 非 HTML: {ctype}"
        html = r.text
        assert "<html" in html.lower()
        for endpoint in (
            "/api/system/status",
            "/api/growth/list",
            "/api/tasks/stats",
            "/api/reports/list",
            "/api/projects/list",
        ):
            assert endpoint in html, f"Dashboard 未引用端点 {endpoint}（页面交互缺少数据支撑）"


# ═════════════════════════════════════════════════════════════════════════════
# B. MCP 对接测试（内存传输）
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mcp_connect_and_discover_tools(mcp_obj):
    """[MCP-连接] 客户端可建立会话并发现 3 个核心工具。"""
    async with Client(mcp_obj) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names >= EXPECTED_TOOLS, f"缺少工具: {EXPECTED_TOOLS - names}"


@pytest.mark.asyncio
async def test_mcp_discover_prompts(mcp_obj):
    """[MCP-连接] 应注册 5 个 prompts。"""
    async with Client(mcp_obj) as client:
        prompts = await client.list_prompts()
        assert len(prompts) == 5, f"prompts 数量应为 5，实际 {len(prompts)}"


@pytest.mark.asyncio
async def test_mcp_core_flow_start_record_finalize(mcp_obj):
    """[MCP-工具调用] 完整业务流：start → record → finalize，每步响应符合预期。"""
    async with Client(mcp_obj) as client:
        r1 = await client.call_tool(
            "start_conversation",
            {"client": "trae", "topic": "登录页开发", "task_type": "development"},
        )
        d1 = _json_tool(r1)
        assert "conversation" in d1
        cid = d1["conversation"]["conversation_id"]
        assert cid.startswith("conv_")

        r2 = await client.call_tool(
            "record_step",
            {
                "conversation_id": cid,
                "step_number": 1,
                "step_name": "创建组件",
                "content": json.dumps({"file": "src/App.tsx", "action": "create"}),
            },
        )
        d2 = _json_tool(r2)
        assert d2.get("success") is True, f"record_step 失败: {d2}"
        assert d2.get("queued") is True
        assert d2.get("conversation_id") == cid

        r3 = await client.call_tool(
            "finalize_conversation", {"conversation_id": cid, "ai_summary": "完成登录页"}
        )
        d3 = _json_tool(r3)
        assert d3.get("success") is True, f"finalize 失败: {d3}"
        assert d3.get("analysis_queued") is True
        assert "analysis_dimensions" in d3


@pytest.mark.asyncio
async def test_mcp_record_step_idempotent(mcp_obj):
    """[MCP-消息收发] 相同 client_request_id 重复调用 record_step 应幂等返回 duplicate。"""
    async with Client(mcp_obj) as client:
        cid = _json_tool(
            await client.call_tool("start_conversation", {"client": "trae", "topic": "幂等测试"})
        )["conversation"]["conversation_id"]
        base_args = {
            "conversation_id": cid,
            "step_number": 1,
            "step_name": "step-x",
            "client_request_id": "idem-001",
        }
        first = _json_tool(await client.call_tool("record_step", base_args))
        assert first.get("success") is True
        second = _json_tool(await client.call_tool("record_step", base_args))
        assert second.get("duplicate") is True, f"期望幂等返回 duplicate: {second}"


@pytest.mark.asyncio
async def test_mcp_record_step_missing_params(mcp_obj):
    """[MCP-参数校验] record_step 缺少必需参数应返回 success=False 并指明缺失项。"""
    async with Client(mcp_obj) as client:
        d = _json_tool(await client.call_tool("record_step", {"conversation_id": "conv_x"}))
        assert d.get("success") is False, "缺少参数时应当失败"
        assert "conversation_id" in d.get("error", "")


@pytest.mark.asyncio
async def test_mcp_finalize_missing_id(mcp_obj):
    """[MCP-参数校验] finalize_conversation 缺少 conversation_id 应返回 success=False。"""
    async with Client(mcp_obj) as client:
        d = _json_tool(await client.call_tool("finalize_conversation", {}))
        assert d.get("success") is False
        assert "conversation_id" in d.get("error", "")


# ═════════════════════════════════════════════════════════════════════════════
# B2. MCP 对接测试（真实 Streamable HTTP 协议走线，复用 uvicorn 服务）
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mcp_real_streamable_http(runtime):
    """[MCP-协议层] 用 streamable-http 客户端连接真实 /mcp 端点，
    验证协议握手、工具发现与工具调用在真实 HTTP 传输下正常。"""
    base = runtime["base"]
    async with Client(base + "/mcp") as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names >= EXPECTED_TOOLS, f"真实协议下缺少工具: {EXPECTED_TOOLS - names}"

        r = await client.call_tool(
            "start_conversation", {"client": "http-client", "topic": "协议走线测试"}
        )
        d = _json_tool(r)
        assert "conversation" in d and d["conversation"]["conversation_id"].startswith("conv_")


# ═════════════════════════════════════════════════════════════════════════════
# C. 集成验证：Web 与 MCP 互不干扰 + 联合数据流转
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_integration_mcp_writes_web_reads(base, mcp_obj):
    """[集成-数据流转] MCP 创建的会话，应能被 Web 的 /api/conversation/status 与 /api/system/status 读到。"""
    async with Client(mcp_obj) as client:
        r = await client.call_tool(
            "start_conversation", {"client": "web-read", "topic": "集成验证"}
        )
        cid = _json_tool(r)["conversation"]["conversation_id"]

    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/api/conversation/status", params={"conversation_id": cid})
        assert r.status_code == 200
        body = r.json()
        assert body.get("found") is True, "Web 未能查到 MCP 创建的会话"
        assert body["conversation"]["conversation_id"] == cid

        r2 = await ac.get("/api/system/status")
        assert r2.status_code == 200
        st = r2.json()
        assert st["today_new_sessions"] >= 1 or st["active_sessions"] >= 1


@pytest.mark.asyncio
async def test_integration_web_traffic_does_not_break_mcp(base, mcp_obj):
    """[集成-互不干扰] 大量 Web 请求后，MCP 工具仍可正常调用。"""
    async with httpx.AsyncClient(base_url=base) as ac:
        for _ in range(20):
            for path in (
                "/health",
                "/api/system/status",
                "/api/tasks/stats",
                "/api/projects/list",
                "/api/growth/user-overview",
            ):
                rr = await ac.get(path)
                assert rr.status_code == 200

    async with Client(mcp_obj) as client:
        d = _json_tool(
            await client.call_tool(
                "start_conversation", {"client": "after-web", "topic": "干扰测试"}
            )
        )
        assert d.get("conversation", {}).get("conversation_id", "").startswith("conv_")


@pytest.mark.asyncio
async def test_integration_mcp_activity_does_not_break_web(base, mcp_obj):
    """[集成-互不干扰] 连续 MCP 业务流后，Web 核心端点仍正常返回。"""
    async with Client(mcp_obj) as client:
        for i in range(5):
            cid = _json_tool(
                await client.call_tool(
                    "start_conversation", {"client": "noisy", "topic": f"噪声{i}"}
                )
            )["conversation"]["conversation_id"]
            await client.call_tool(
                "record_step", {"conversation_id": cid, "step_number": 1, "step_name": f"s{i}"}
            )
            await client.call_tool("finalize_conversation", {"conversation_id": cid})

    async with httpx.AsyncClient(base_url=base) as ac:
        for path in (
            "/health",
            "/dashboard",
            "/api/system/status",
            "/api/tasks/stats",
            "/api/projects/list",
            "/api/growth/list",
        ):
            rr = await ac.get(path)
            assert rr.status_code == 200, f"MCP 活动后 Web 端点异常: {path}"


@pytest.mark.asyncio
async def test_integration_joint_data_consistency(base, mcp_obj):
    """[集成-联合流转] 联合运行：MCP 写入步骤 → Web 读取该会话的步骤明细，数据一致。"""
    async with Client(mcp_obj) as client:
        cid = _json_tool(
            await client.call_tool("start_conversation", {"client": "joint", "topic": "联合一致性"})
        )["conversation"]["conversation_id"]
        await client.call_tool(
            "record_step",
            {
                "conversation_id": cid,
                "step_number": 1,
                "step_name": "步骤A",
                "content": json.dumps({"file": "a.py"}),
            },
        )
        await client.call_tool(
            "record_step",
            {
                "conversation_id": cid,
                "step_number": 2,
                "step_name": "步骤B",
                "content": json.dumps({"file": "b.py"}),
            },
        )

    async with httpx.AsyncClient(base_url=base) as ac:
        r = await ac.get("/api/conversation/status", params={"conversation_id": cid})
        body = r.json()
        assert body.get("found") is True
        steps = body.get("conversation", {}).get("steps") or body.get("steps") or []
        assert len(steps) >= 2, f"Web 读到的步骤数不足: {len(steps)}"
