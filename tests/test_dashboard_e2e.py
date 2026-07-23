"""
DevPartner — Dashboard 真实浏览器端到端（E2E）测试
================================================

用 Playwright 真实加载 /dashboard 页面，验证“页面交互功能是否正常”：
  - 页面能正常加载（HTML/CSS/JS 无致命错误）
  - 前端 JS 能成功调用后端 /api/* 接口并把数据渲染进 DOM（核心交互闭环）
  - 关键指标（活跃会话数 / 知识库大小 / 最近更新时间）被正确填充

说明：
  - 通过 uvicorn 启动与生产一致的 HTTP 服务，Playwright 走真实浏览器访问。
  - 关闭 LLM、屏蔽后台调度器、隔离数据库，消除外部依赖不稳定。
  - 若环境无法启动 Chromium，本文件用例自动跳过（不影响其它套件）。
"""

import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright

    HAVE_PLAYWRIGHT = True
except Exception:  # pragma: no cover
    HAVE_PLAYWRIGHT = False

pytestmark = pytest.mark.skipif(not HAVE_PLAYWRIGHT, reason="Playwright/Chromium 不可用")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def dash_server():
    import foundation.config.app_settings as app_settings

    cfg = app_settings.get_config()
    cfg.data.root_dir = str(Path(tempfile.mkdtemp(prefix="devpartner_e2e_")))
    cfg.llm.enabled = False
    cfg.llm.preload = False

    import backend.business.data_cleanup.cleanup_service as clean_mod
    import backend.core.scheduler as sched_mod

    sched_mod.get_scheduler = lambda: mock.MagicMock()
    sched_mod.get_timeout_scheduler = lambda: mock.MagicMock()
    clean_mod.get_cleanup_scheduler = lambda: mock.MagicMock()
    clean_mod.get_cleanup_service = lambda: mock.MagicMock()

    import mcp_service.mcp_server as ms_mod

    ms_mod._register_rest_routes()
    ms_mod._register_prompts()
    ms_mod._register_task_handlers()
    from backend.core.bootstrap import ensure_ready

    ensure_ready()

    import uvicorn

    port = _free_port()
    app = ms_mod.mcp.http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            import httpx

            if httpx.Client().get(base + "/health").status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    yield base
    server.should_exit = True


def test_dashboard_page_loads_and_renders_data(dash_server):
    """[页面E2E] 加载 Dashboard 后，前端 JS 成功拉取 /api/* 并把关键指标渲染进 DOM。"""
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        page.goto(dash_server + "/dashboard", wait_until="domcontentloaded", timeout=30000)

        # 页面标题应含 DevPartner
        assert "DevPartner" in page.title()

        # 关键指标：活跃会话数（由 /api/system/status 渲染）
        page.wait_for_selector("#activeSessions", state="visible", timeout=15000)
        active = (page.inner_text("#activeSessions") or "").strip()
        assert active != "" and any(c.isdigit() for c in active), (
            f"activeSessions 未渲染: {active!r}"
        )

        # 知识库大小（由 /api/system/status 渲染）
        kb = (page.inner_text("#kbSize") or "").strip()
        assert kb != "" and any(c.isdigit() for c in kb), f"kbSize 未渲染: {kb!r}"

        # 注：重构后 #lastUpdate 已不存在；健康检查区(#healthContent)位于“系统运维”页
        # （默认隐藏），故在概览页仅验证活跃会话/知识库条目两类关键指标的渲染闭环。

        browser.close()

    assert page_errors == [], f"页面运行期 JS 错误: {page_errors}"


def test_dashboard_navigates_to_projects_tab(dash_server):
    """[页面E2E] 点击“项目”导航后，项目列表区域成功加载（验证前端路由/交互与 API 联动）。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(dash_server + "/dashboard", wait_until="domcontentloaded", timeout=30000)

        # 点击侧边栏“项目”导航（button[data-page=projects] → switchPage('projects')）
        page.click("button[data-page='projects']", timeout=8000)

        # 切换到项目页后，项目列表区应可见并由 /api/projects/list 渲染
        page.wait_for_selector("#page-projects.active", state="visible", timeout=15000)
        page.wait_for_selector("#projCount", state="visible", timeout=15000)
        proj_count = (page.inner_text("#projCount") or "").strip()
        assert proj_count != "", "项目数量未渲染（/api/projects/list 联动失败）"
        browser.close()
