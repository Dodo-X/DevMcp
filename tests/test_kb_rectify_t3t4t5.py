"""
T3 + T4 + T5 持久化回归测试（KB 数据架构整改）
============================================

覆盖已落地的整改（设计依据 docs/kb_arch_rectify.md §3、§4.2、§6）：

T4（connected_systems 修订落地）：
  - TC1 注册写新列：ensure_system_registered 新注册写入 client_name（承接原 client/IDE 名）、
        system_type 启发式默认 'backend_service'、system_type_confirmed=0；business_modules 取默认 '[]'；
        project_path 列已删除（PRAGMA 确认）。
  - TC2 update_connected_system：写入 business_modules，且不互相覆盖其它扩展字段。
  - TC3 get_system_context 不引用已删除的 project_path 列（不抛 "no such column: project_path"）。
  - TC4 全仓静态检查：除 base_conn.py 的迁移 DROP 代码与注释外，无 project_path 运行期读取。

T3（finalize 知识抽取拆分）：
  - TC5 抽取拆分 facade 行为：LLM 不可用时 extract_all 安全返回结构且 llm_used=False；
        业务抽取 0 条 + 有 key_decisions 时，降级写入至少 1 条 business 知识点
        （type='business'、domain=项目名、module=''）。

T5（project_description 生成整改）：
  - TC6 业务知识透传：_gather_business_knowledge 聚合本次对话的 business 知识点 content，
        作为 business_knowledge 透传给 review_project_description。

运行:
    cd D:/WorkSpace/Code/devPartner
    TEST_ENV=true LLM_TEST_MODE=mock TEST_DB=:memory: \
        .venv/Scripts/python.exe -m pytest tests/test_kb_rectify_t3t4t5.py -v
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import backend.core.database.base_conn as base_conn
import pytest
from backend.business.conversation_mgr.dao import ConversationDAO
from backend.business.knowledge_extractor.extract_service import KnowledgeExtractor
from backend.core.database.base_conn import Database

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"


# 运行期读取 project_path 的禁用模式（迁移 DROP 代码与注释除外）
_FORBIDDEN_PROJECT_PATH = [
    re.compile(r"""\.get\(\s*["']project_path["']\s*\)"""),
    re.compile(r"""\[\s*["']project_path["']\s*\]"""),
    re.compile(r"select\b[^;\n]*project_path", re.IGNORECASE),
]


class _UnavailableLLM:
    """模拟 LLM 不可用（is_available 恒 False），验证拆分后 facade 在 mock 下安全。"""

    def is_available(self):
        return False


# ══════════════════════════════════════════════════════════════
# 测试夹具
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """提供一个全新的临时库，并把 get_db() 单例指向它。"""
    db = Database()
    db.init_local(str(tmp_path / "fresh_kb.db"))
    monkeypatch.setattr(base_conn, "_db_instance", db)
    yield db
    db.close()
    monkeypatch.setattr(base_conn, "_db_instance", None)


def _cs_columns(db: Database) -> set:
    """返回 connected_systems 当前列名集合。"""
    rows = db._local_conn.execute("PRAGMA table_info(connected_systems)").fetchall()
    return {row[1] for row in rows}


# ══════════════════════════════════════════════════════════════
# T4: connected_systems 修订落地
# ══════════════════════════════════════════════════════════════


def test_t4_tc1_register_writes_new_columns(fresh_db):
    """T4-TC1: 新注册写入 client_name / system_type 启发式默认 / system_type_confirmed=0；
    business_modules 默认 '[]'；project_path 列已删除。"""
    dao = ConversationDAO(fresh_db)
    now = datetime.now().isoformat()
    # system_type='trae' 在任务描述中模拟 client 名 → 实际入参为 client
    dao.ensure_system_registered(system_id="devPartner", client="trae", timestamp=now)

    row = dao.get_system_row("devPartner")
    assert row is not None, "devPartner 应已注册到 connected_systems"

    # client_name 承接原 client/IDE 名
    assert row["client_name"] == "trae", "client_name 应为传入的 client 名"
    # system_type 启发式默认 backend_service
    assert row["system_type"] == "backend_service", (
        "system_type 应为启发式默认 'backend_service'"
    )
    # 未确认
    assert row["system_type_confirmed"] == 0, "system_type_confirmed 应为 0"
    # business_modules 未写入（注册阶段不写），取默认 '[]'
    assert row["business_modules"] == "[]", "business_modules 应默认 '[]'"

    # project_path 列已删除（PRAGMA 确认）
    cols = _cs_columns(fresh_db)
    assert "project_path" not in cols, "connected_systems 不应再含 project_path 列"
    assert "project_path" not in row, "注册行不应包含 project_path 字段"


def test_t4_tc2_update_connected_system_business_modules(fresh_db):
    """T4-TC2: update_connected_system 写入 business_modules，且不覆盖其它扩展字段。"""
    dao = ConversationDAO(fresh_db)
    now = datetime.now().isoformat()
    dao.ensure_system_registered(system_id="devPartner", client="trae", timestamp=now)

    dao.update_connected_system(
        system_id="devPartner",
        business_modules=["报告生成", "task管理"],
        now=now,
    )

    row = dao.get_system_row("devPartner")
    expected_bm = json.dumps(["报告生成", "task管理"], ensure_ascii=False)
    assert row["business_modules"] == expected_bm, "business_modules 应正确写入 JSON"

    # 其它扩展字段不应被覆盖
    assert row["client_name"] == "trae", "client_name 不应被 update_connected_system 覆盖"
    assert row["system_type"] == "backend_service", "system_type 不应被覆盖"


def test_t4_tc3_get_system_context_no_project_path(fresh_db):
    """T4-TC3: get_system_context 不引用已删除的 project_path 列（不抛 'no such column'）。"""
    dao = ConversationDAO(fresh_db)
    now = datetime.now().isoformat()
    dao.ensure_system_registered(system_id="devPartner", client="trae", timestamp=now)
    # 写入 project_description / display_name 以验证返回结构可用
    fresh_db.query_local(
        "UPDATE connected_systems SET project_description=?, display_name=? WHERE system_id=?",
        ("devPartner 是用于知识沉淀的 MCP 服务", "devPartner", "devPartner"),
    )

    # 关键断言：不抛 "no such column: project_path"
    try:
        ctx = dao.get_system_context("devPartner")
    except Exception as e:  # noqa: BLE001
        assert "no such column: project_path" not in str(e), (
            f"get_system_context 不应引用已删除的 project_path 列: {e}"
        )
        raise

    assert isinstance(ctx, str), "get_system_context 应返回字符串"
    assert "devPartner" in ctx, "返回的项目上下文应包含项目名/描述信息"

    # DEFAULT_SYSTEM_ID 守卫分支返回空串，不应抛错
    assert dao.get_system_context("default") == "", "DEFAULT_SYSTEM_ID 应返回空串"


def test_t4_tc4_no_runtime_project_path_reference():
    """T4-TC4: 全仓除 base_conn.py 迁移 DROP 代码与注释外，无 project_path 运行期读取。"""
    assert BACKEND_ROOT.exists(), f"backend 目录不存在: {BACKEND_ROOT}"

    violations = []
    for py_file in BACKEND_ROOT.rglob("*.py"):
        rel = py_file.relative_to(REPO_ROOT)
        try:
            lines = py_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, 1):
            if "project_path" not in line:
                continue
            stripped = line.lstrip()
            # 整行注释允许
            if stripped.startswith("#"):
                continue
            # base_conn.py 的迁移 DROP COLUMN 代码与注释允许
            if "DROP COLUMN project_path" in line:
                continue
            if any(p.search(line) for p in _FORBIDDEN_PROJECT_PATH):
                violations.append(f"{rel}:{idx}: {line.strip()}")

    assert not violations, (
        "发现 project_path 运行期引用（应已删除/迁移）:\n" + "\n".join(violations)
    )


# ══════════════════════════════════════════════════════════════
# T3: finalize 知识抽取拆分（facade 行为）
# ══════════════════════════════════════════════════════════════


def test_t3_tc5_extract_all_facade_safe_without_llm(fresh_db, monkeypatch):
    """T3-TC5: 拆分后 facade extract_all 在 LLM 不可用时安全返回结构，llm_used=False，不抛。"""
    from backend.core.llm_kernel import base_client as llm_base_client

    monkeypatch.setattr(llm_base_client, "get_llm_engine", lambda: _UnavailableLLM())

    extractor = KnowledgeExtractor()
    result = extractor.extract_all("conv_t3a", "一些对话文本用于抽取")

    # 返回结构包含四个关键字段
    for key in ("skill_extracted", "business_extracted", "knowledge_ids", "llm_used"):
        assert key in result, f"extract_all 返回结构应含字段 {key}"

    assert result["llm_used"] is False, "LLM 不可用时 llm_used 应为 False"
    assert result["skill_extracted"] == 0
    assert result["business_extracted"] == 0
    assert result["knowledge_ids"] == []


def test_t3_tc5_key_decisions_degrade_writes_business(fresh_db, monkeypatch):
    """T3-TC5: 业务抽取 0 条 + 有 key_decisions 时，降级写入至少 1 条 business 知识点。"""
    from backend.core.llm_kernel import base_client as llm_base_client

    monkeypatch.setattr(llm_base_client, "get_llm_engine", lambda: _UnavailableLLM())

    project_name = os.path.basename(os.getcwd())

    extractor = KnowledgeExtractor()
    key_decisions = [
        {
            "decision": "报告生成模块采用模板化输出",
            "reason": "统一格式",
            "tradeoff": "灵活性下降",
        },
        {"decision": "", "reason": "无效决策应跳过"},
    ]
    result = extractor.extract_all("conv_t3b", "对话文本", key_decisions=key_decisions)

    assert result["llm_used"] is False
    assert result["business_extracted"] >= 1, "应至少降级写入 1 条 business 知识点"

    rows = fresh_db.query_local(
        "SELECT * FROM knowledge_points WHERE source_id='conv_t3b' AND type='business'"
    )
    assert len(rows) >= 1, "knowledge_points 应至少 1 条 type='business' 降级写入"

    r = rows[0]
    assert r["type"] == "business", "降级知识点 type 应为 'business'"
    assert r["domain"] == project_name, f"降级知识点 domain 应为项目名 {project_name}"
    assert r["module"] == "", "降级知识点 module 应为空字符串"
    assert r["source_id"] == "conv_t3b"


# ══════════════════════════════════════════════════════════════
# T5: project_description 生成整改（业务知识透传）
# ══════════════════════════════════════════════════════════════


def test_t5_tc6_gather_business_knowledge_passthrough(fresh_db, monkeypatch):
    """T5-TC6: _gather_business_knowledge 聚合本次对话的 business 知识点 content 作为透传。"""
    from backend.business.conversation_mgr.handlers import conv_finalize

    # 说明：review_project_description 是 LLM client 的实例方法（非模块级函数），
    # 且 _gather_business_knowledge 仅从 DB 读取、不调用它；本用例只需验证聚合透传结果，
    # 不依赖真实 LLM，故无需 mock（T5 透传的确定性由 DB 落库保证）。
    dao = ConversationDAO(fresh_db)
    # 构造 2 条 type='business' & source_id='conv_t5' 的知识点落库
    fresh_db.insert_knowledge_point(
        title="报告生成约定",
        content="报告生成内容alpha",
        category="concept",
        domain="devPartner",
        tags=["报告生成"],
        source_id="conv_t5",
        kp_type="business",
        module="报告生成",
    )
    fresh_db.insert_knowledge_point(
        title="task管理约定",
        content="task管理内容beta",
        category="concept",
        domain="devPartner",
        tags=["task管理"],
        source_id="conv_t5",
        kp_type="business",
        module="报告生成",
    )

    gathered = conv_finalize._gather_business_knowledge(dao, "conv_t5")

    assert "报告生成内容alpha" in gathered, "T5 应透传 conv_t5 的 business 知识点内容"
    assert "task管理内容beta" in gathered, "T5 应透传 conv_t5 的另一条 business 知识点内容"
