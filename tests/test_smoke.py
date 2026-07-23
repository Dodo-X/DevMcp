"""DevPartner 冒烟测试套件（技术审查补齐）。

目标：在 CI 中提供「可运行」的最小护栏，覆盖不依赖外部服务（Ollama / fastmcp 运行时）
的核心契约，避免测试套件为空导致回归无感知。

运行:
    pytest tests/test_smoke.py -v
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_project_version_is_single_source_of_truth():
    """版本号必须来自 pyproject.toml，且符合语义化版本。"""
    from foundation.config.app_settings import get_project_version

    version = get_project_version()
    assert version == "9.5.5", f"版本号应与 pyproject.toml 一致，实际: {version}"
    parts = version.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), "版本号应满足 x.y.z 格式"


def test_database_schema_creates_core_tables(tmp_path):
    """Database.init_local 必须幂等创建全部核心表，并保证关键字段存在。"""
    from backend.core.database.base_conn import Database

    db = Database()
    db_path = str(tmp_path / "test_devpartner.db")
    db.init_local(db_path)
    try:
        rows = db.query_local("SELECT name FROM sqlite_master WHERE type='table'")
        names = {r["name"] for r in rows}
        for expected in (
            "conversations",
            "conversation_steps",
            "knowledge_points",
            "task_queue",
            "user_skills",
            "improvement_log",
            "growth_analysis",
        ):
            assert expected in names, f"缺少核心表: {expected}"

        cols = {r[1] for r in db._local_conn.execute("PRAGMA table_info(conversations)").fetchall()}
        assert "conversation_id" in cols
        assert "ai_analysis" in cols
    finally:
        db.close()


def test_database_is_thread_safe_wrapper_present():
    """应暴露读写锁以保证 SQLite 并发安全（WAL + 锁）。"""
    import inspect

    from backend.core.database.base_conn import Database

    assert hasattr(Database, "_write_lock")
    assert hasattr(Database, "_local_lock")
    sig = inspect.signature(Database.query_local)
    assert "sql" in sig.parameters


def test_unified_response_factory_shape():
    """统一返回体工厂应产出 code/message/data 标准结构（见 base_resp.StandardResponse）。

    注: MCP 工具侧目前使用 {success, error} 形态，二者尚未统一，已记入技术审查报告。
    """
    from foundation.api_response.resp_factory import fail, ok
    from foundation.config.error_code import ErrorCode

    ok_resp = ok(data={"x": 1})
    assert ok_resp["code"] == ErrorCode.SUCCESS
    assert ok_resp["data"] == {"x": 1}
    assert "message" in ok_resp

    fail_resp = fail(message="boom")
    assert fail_resp["code"] != ErrorCode.SUCCESS
    assert fail_resp["message"] == "boom"


def test_biz_exception_carries_error_code():
    """业务异常应携带统一错误码，便于渲染为标准返回。"""
    from foundation.config.error_code import ErrorCode
    from foundation.exception_framework.base_exc import BizException

    exc = BizException("示例业务异常", code=ErrorCode.INTERNAL_ERROR)
    assert exc.code == ErrorCode.INTERNAL_ERROR
    assert str(exc) == "示例业务异常"
