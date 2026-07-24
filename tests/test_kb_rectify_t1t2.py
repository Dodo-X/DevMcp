"""
T1 + T2 持久化回归测试（KB 数据架构整改）
========================================

覆盖已落地的整改（设计依据 docs/kb_arch_rectify.md §2、§3、§4.1）：

T1（Schema 迁移）：
  - knowledge_points 新增 module 列 + 两个新索引
  - connected_systems 删除 project_path，新增 client_name /
    business_modules / system_type_confirmed
  - 既有库迁移：补列、删 project_path、旧多标签行收敛为单值

T2（写入路径重构）：
  - insert_knowledge_point 入库 module，强制单 tag（多值取首个）
  - KnowledgeExtractor.extract_step_knowledge 以 type='skill'、
    source_id=conversation_id、module='' 落库，跳过空 title/content
    （修复原 step_id 死链）

运行:
    cd D:/WorkSpace/Code/devPartner
    .venv/Scripts/python.exe -m pytest tests/test_kb_rectify_t1t2.py -v
"""

import json
import sqlite3

import backend.core.database.base_conn as base_conn
import pytest
from backend.business.knowledge_extractor.extract_service import KnowledgeExtractor
from backend.core.database.base_conn import Database

# ════════════════════════════════════════════════════════════════
# 测试夹具
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """提供一个全新的内存/临时库，并把 get_db() 单例指向它。

    KnowledgeExtractor / _save_knowledge 内部通过 get_db() 取库，
    必须让单例指向本测试实例，否则会用到未初始化的全局实例。
    """
    db = Database()
    db.init_local(str(tmp_path / "fresh_kb.db"))
    monkeypatch.setattr(base_conn, "_db_instance", db)
    yield db
    db.close()
    monkeypatch.setattr(base_conn, "_db_instance", None)


def _build_pre_v10_db(path: str):
    """手工构造一个 v10 之前的库（用于模拟既有库迁移）。

    特点：
      - knowledge_points 无 module 列，含多标签行 tags='["装饰器","闭包"]'
      - connected_systems 含 project_path，缺 client_name /
        business_modules / system_type_confirmed
    """
    conn = sqlite3.connect(path)
    cur = conn.cursor()

    # v10 之前的 knowledge_points（无 module 列）
    cur.execute(
        """
        CREATE TABLE knowledge_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            knowledge_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            domain TEXT NOT NULL,
            tags JSON DEFAULT '[]',
            source_id TEXT,
            confidence REAL DEFAULT 0.8,
            difficulty TEXT DEFAULT 'medium',
            usage_count INTEGER DEFAULT 0,
            related_knowledge_ids TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            type TEXT NOT NULL DEFAULT 'skill' CHECK(type IN ('skill','business')),
            aliases JSON DEFAULT '[]'
        )
        """
    )

    # v10 之前的 connected_systems（含 project_path，缺三个新列）
    cur.execute(
        """
        CREATE TABLE connected_systems (
            system_id TEXT PRIMARY KEY,
            system_type TEXT NOT NULL,
            display_name TEXT,
            project_path TEXT DEFAULT '',
            tech_stack JSON DEFAULT '[]',
            architecture JSON DEFAULT '{}',
            business_domains JSON DEFAULT '[]',
            maturity TEXT DEFAULT 'unknown',
            first_connected TEXT NOT NULL,
            last_active TEXT NOT NULL,
            last_seen_at TEXT DEFAULT '',
            conversation_count INTEGER DEFAULT 0,
            project_description TEXT DEFAULT ''
        )
        """
    )

    # 多标签行（tags 为 ["装饰器","闭包"]，迁移后应收敛为 ["装饰器"]）
    cur.execute(
        "INSERT INTO knowledge_points "
        "(knowledge_id, title, content, category, domain, tags, source_id, type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "kp_old_1",
            "装饰器模式",
            "装饰器用于包装函数",
            "step_extracted",
            "Python",
            json.dumps(["装饰器", "闭包"], ensure_ascii=False),
            "conv_old",
            "skill",
        ),
    )

    # 含 project_path 的对接系统行
    cur.execute(
        "INSERT INTO connected_systems "
        "(system_id, system_type, display_name, project_path, first_connected, last_active) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("trae_main", "trae", "Trae", "/old/abs/path", "2026-01-01", "2026-01-02"),
    )

    conn.commit()
    conn.close()


def _table_columns(db: Database, table: str) -> set:
    """返回某表的列名集合。"""
    rows = db._local_conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _index_names(db: Database) -> set:
    rows = db.query_local("SELECT name FROM sqlite_master WHERE type='index'")
    return {r["name"] for r in rows}


# ════════════════════════════════════════════════════════════════
# TC1 全新库 schema
# ════════════════════════════════════════════════════════════════


def test_tc1_fresh_db_schema(fresh_db):
    """全新库：knowledge_points 含 module；connected_systems 含三新列且无 project_path。"""
    kp_cols = _table_columns(fresh_db, "knowledge_points")
    cs_cols = _table_columns(fresh_db, "connected_systems")

    # knowledge_points 新增 module 列
    assert "module" in kp_cols, "knowledge_points 应含 module 列"

    # connected_systems 删除 project_path
    assert "project_path" not in cs_cols, "connected_systems 不应再含 project_path 列"

    # connected_systems 新增三个列
    assert "client_name" in cs_cols, "connected_systems 应含 client_name 列"
    assert "business_modules" in cs_cols, "connected_systems 应含 business_modules 列"
    assert (
        "system_type_confirmed" in cs_cols
    ), "connected_systems 应含 system_type_confirmed 列"


def test_tc1_fresh_db_new_indexes(fresh_db):
    """全新库：应建立两个新索引 idx_kp_type_domain_module / idx_kp_source_created。"""
    indexes = _index_names(fresh_db)
    assert "idx_kp_type_domain_module" in indexes, "缺少索引 idx_kp_type_domain_module"
    assert "idx_kp_source_created" in indexes, "缺少索引 idx_kp_source_created"


# ════════════════════════════════════════════════════════════════
# TC2 既有库迁移（模拟 pre-v10）
# ════════════════════════════════════════════════════════════════


def test_tc2_migrate_pre_v10_db(tmp_path, monkeypatch):
    """既有库迁移：删 project_path、补 3 新列、补 module、旧多标签行收敛为首个。"""
    path = str(tmp_path / "pre_v10.db")
    _build_pre_v10_db(path)

    # 重新走初始化流程（触发 v10 迁移块）
    db = Database()
    db.init_local(path)
    monkeypatch.setattr(base_conn, "_db_instance", db)
    try:
        kp_cols = _table_columns(db, "knowledge_points")
        cs_cols = _table_columns(db, "connected_systems")

        # 既有数据应保留
        assert db.query_local("SELECT COUNT(*) AS c FROM knowledge_points")[0]["c"] == 1
        assert db.query_local("SELECT COUNT(*) AS c FROM connected_systems")[0]["c"] == 1

        # knowledge_points 补了 module 列
        assert "module" in kp_cols, "迁移后 knowledge_points 应含 module 列"

        # connected_systems 删 project_path
        assert "project_path" not in cs_cols, "迁移后 connected_systems 不应含 project_path"

        # connected_systems 补 3 个新列
        assert "client_name" in cs_cols
        assert "business_modules" in cs_cols
        assert "system_type_confirmed" in cs_cols

        # 旧多标签行收敛为首个有效标签 ["装饰器"]
        row = db.query_local(
            "SELECT tags FROM knowledge_points WHERE knowledge_id='kp_old_1'"
        )[0]
        assert json.loads(row["tags"]) == ["装饰器"], f"多标签应收敛为单值，实际: {row['tags']}"

        # 新索引应已建立
        indexes = _index_names(db)
        assert "idx_kp_type_domain_module" in indexes
        assert "idx_kp_source_created" in indexes
    finally:
        db.close()
        monkeypatch.setattr(base_conn, "_db_instance", None)


# ════════════════════════════════════════════════════════════════
# TC3 单 tag 不变式（insert_knowledge_point）
# ════════════════════════════════════════════════════════════════


def test_tc3_insert_knowledge_point_single_tag_and_module(fresh_db):
    """insert_knowledge_point 强制单 tag，并正确入库 module / source_id。"""
    kp_id = fresh_db.insert_knowledge_point(
        title="标题A",
        content="内容A",
        category="concept",
        domain="Python",
        tags=["a", "b"],
        source_id="conv_x",
        module="报告生成",
    )
    assert kp_id is not None, "知识点应成功入库并返回 knowledge_id"

    row = fresh_db.query_local(
        "SELECT tags, source_id, module, type FROM knowledge_points WHERE knowledge_id=?",
        (kp_id,),
    )[0]

    # 多值 tags 收敛为首个 ["a"]
    assert json.loads(row["tags"]) == ["a"], f"tags 应收敛为单值 ['a']，实际: {row['tags']}"
    # module 正确入库
    assert row["module"] == "报告生成", "module 应正确入库"
    # source_id 正确入库
    assert row["source_id"] == "conv_x", "source_id 应正确入库"


# ════════════════════════════════════════════════════════════════
# TC4 步骤知识点落库修复（extract_step_knowledge）
# ════════════════════════════════════════════════════════════════


def test_tc4_extract_step_knowledge_uses_conversation_id(fresh_db):
    """extract_step_knowledge 以 type='skill'、source_id=conversation_id、module='' 落库，跳过空 title。"""
    extractor = KnowledgeExtractor()
    ids = extractor.extract_step_knowledge(
        [
            {"title": "X", "content": "Y", "domain": "Python", "tags": ["z"]},
            # 空 title 条目应被跳过
            {"title": "", "content": "无标题应跳过", "domain": "Python", "tags": ["zz"]},
        ],
        "conv_2",
    )

    # 仅有效条目落库（空 title 被跳过）
    assert len(ids) == 1, f"应仅 1 条有效知识点，实际: {len(ids)}"

    rows = fresh_db.query_local(
        "SELECT * FROM knowledge_points WHERE source_id='conv_2'"
    )
    assert len(rows) == 1, "source_id=conv_2 应恰好 1 行（证明 step_id 死链已修复）"
    r = rows[0]

    # 修复点：type=skill、source_id=conversation_id、module=''
    assert r["type"] == "skill", "步骤知识点 type 应为 skill"
    assert r["source_id"] == "conv_2", "步骤知识点 source_id 应为 conversation_id（非 step_id）"
    assert r["module"] == "", "步骤知识点 module 应为空字符串"

    # 单 tag 不变式 + 内容正确
    assert json.loads(r["tags"]) == ["z"], f"tags 应为单值 ['z']，实际: {r['tags']}"
    assert r["title"] == "X"
    assert r["domain"] == "Python"
