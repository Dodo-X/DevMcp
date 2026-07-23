"""
DevPartner — 会话历史浏览 API 集成测试
========================================
验证 /api/conversations（列表）与 /api/conversations/{id}（详情）端点。
复用 test_web_mcp_integration 的运行时装配 + uvicorn 真实启动模式。
"""

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


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def runtime():
    import foundation.config.app_settings as app_settings

    cfg = app_settings.get_config()
    tmp = Path(tempfile.mkdtemp(prefix="conv_api_"))
    cfg.data.root_dir = str(tmp)
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

    mcp = ms_mod.mcp
    port = _free_port()
    app = mcp.http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    base = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(100):
        try:
            with httpx.Client() as c:
                if c.get(base + "/health").status_code == 200:
                    ready = True
                    break
        except Exception:
            pass
        import time

        time.sleep(0.1)
    assert ready, "uvicorn HTTP 服务未在预期时间内就绪"

    yield {"tmp": tmp, "base": base}

    server.should_exit = True


@pytest.fixture
def base(runtime):
    return runtime["base"]


def _seed():
    import uuid

    from backend.business.conversation_mgr.dao import ConversationDAO
    from backend.core.database.base_conn import get_db

    db = get_db()
    dao = ConversationDAO(db)
    suffix = uuid.uuid4().hex[:8]
    id1 = f"conv-it-{suffix}-1"
    id2 = f"conv-it-{suffix}-2"
    dao.create_conversation(
        id1, "2026-07-23T10:00:00", "codebuddy",
        "集成测试会话主题", "general", "用户意图A", "default", "原始输入", "AI分析",
    )
    dao.create_conversation(
        id2, "2026-07-23T11:00:00", "trae",
        "另一个会话", "code", "用户意图B", "default", "原始输入2", "AI分析2",
    )
    return id1, id2


def test_conversations_list_and_detail(base):
    id1, id2 = _seed()
    with httpx.Client() as c:
        r = c.get(base + "/api/conversations?limit=10")
        assert r.status_code == 200
        d = r.json()
        assert d["code"] == 0
        assert d["data"]["total"] >= 2
        ids = [i["conversation_id"] for i in d["data"]["items"]]
        assert id1 in ids and id2 in ids

        # 关键词筛选
        r2 = c.get(base + "/api/conversations?keyword=集成")
        assert r2.status_code == 200
        assert r2.json()["data"]["total"] == 1

        # 详情
        r3 = c.get(base + f"/api/conversations/{id1}")
        assert r3.status_code == 200
        dd = r3.json()
        assert dd["code"] == 0
        assert dd["data"]["conversation"]["conversation_id"] == id1

        # 不存在的会话 → 404
        r4 = c.get(base + "/api/conversations/does-not-exist")
        assert r4.status_code == 404


def test_conversations_pagination(base):
    _seed()
    with httpx.Client() as c:
        r = c.get(base + "/api/conversations?limit=1&offset=0")
        assert r.status_code == 200
        d = r.json()
        assert len(d["data"]["items"]) == 1
        assert d["data"]["total"] >= 2
