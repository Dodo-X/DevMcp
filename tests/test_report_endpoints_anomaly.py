"""
DevPartner — 报告生成类 Web 端点回归测试
=========================================

验证 /api/reports/generate 各周期报告端点返回正确（HTTP 200，含 success 字段）。

历史缺陷（均已修复）：
  - 缺陷 A（已修复）：整改时周/月/年报函数从 daily_summary.py 拆分到 reports.py，
    但 daily_summary.py 末尾"向后兼容重导出"段落为空，导致 rest_api / scheduler
    从 daily_summary 导入 generate_weekly/monthly/annual_report 失败（ImportError → 500）。
    修复：在 daily_summary.py 补上 `from backend.business.task_handlers.reports import (...)` 重导出。
  - 缺陷 C（已修复，连带）：scheduler.py 定时报告任务同一根因，已随重导出一并修复。
  - 缺陷 B（仍保留观察，非阻塞）：GET /mcp 健康检查路由被 Streamable HTTP 会话管理器遮蔽，
    直接 GET 返回 406；真实 MCP 客户端连接正常，仅便捷 GET 探测不可用，建议以 /health 为准。

这些端点与 Web/MCP 核心对接无关，但属于报告子模块的关键功能，需回归守护。
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

import httpx  # noqa: E402
import mcp_service.mcp_server as ms_mod  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def srv():
    import foundation.config.app_settings as app_settings

    cfg = app_settings.get_config()
    cfg.data.root_dir = str(Path(tempfile.mkdtemp(prefix="rpt_regr_")))
    cfg.llm.enabled = False
    cfg.llm.preload = False
    import backend.business.data_cleanup.cleanup_service as clean_mod
    import backend.core.scheduler as sched_mod

    sched_mod.get_scheduler = lambda: mock.MagicMock()
    sched_mod.get_timeout_scheduler = lambda: mock.MagicMock()
    clean_mod.get_cleanup_scheduler = lambda: mock.MagicMock()
    clean_mod.get_cleanup_service = lambda: mock.MagicMock()
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
            if httpx.Client().get(base + "/health").status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    yield base
    server.should_exit = True


def test_reports_generate_weekly_returns_200(srv):
    """[回归-缺陷A已修复] POST /api/reports/generate {type:weekly} 应返回 200。

    T6：空库（无对话/知识点）周期应显式失败 method='failed'，不再静默 success=True。
    端点仍返回 HTTP 200（结果由 JSON 体描述）。
    """
    r = httpx.Client().post(srv + "/api/reports/generate", json={"type": "weekly"})
    assert r.status_code == 200, f"实际 {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("success") is False
    assert body.get("method") == "failed"


def test_reports_generate_monthly_returns_200(srv):
    """[回归-缺陷A已修复] POST /api/reports/generate {type:monthly} 应返回 200。

    T6：空库周期显式失败 method='failed'。
    """
    r = httpx.Client().post(srv + "/api/reports/generate", json={"type": "monthly"})
    assert r.status_code == 200, f"实际 {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("success") is False
    assert body.get("method") == "failed"


def test_reports_generate_annual_returns_200(srv):
    """[回归-缺陷A已修复] POST /api/reports/generate {type:annual} 应返回 200。

    T6：空库周期显式失败 method='failed'。
    """
    r = httpx.Client().post(srv + "/api/reports/generate", json={"type": "annual"})
    assert r.status_code == 200, f"实际 {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("success") is False
    assert body.get("method") == "failed"


def test_reports_generate_daily_works(srv):
    """[对照] 日报生成端点正常：POST /api/reports/generate-daily 返回 200。"""
    r = httpx.Client().post(srv + "/api/reports/generate-daily", json={"date": "2026-07-23"})
    assert r.status_code == 200
    assert r.json().get("success") is True
