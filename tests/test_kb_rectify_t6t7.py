"""
T6 + T7 持久化回归测试（KB 数据架构整改）
========================================

覆盖已落地的整改（设计依据 docs/kb_arch_rectify.md §4.3、§5）：

T6（报告链路真实数据重构）：
  - TC1 空周期显式失败：历史无数据周期调用 generate_weekly_report 必须返回
        {"success": False, "method": "failed"} 且**不写出任何 MD 报告文件**，
        根绝旧「日报文件缺失却静默 success」的假数据流。
  - TC2 有数据周期成功：临时库插入 1 对话 + 2 知识点（created_at 落在目标周期），
        query_period_data 能查到真实计数；generate_weekly_report 在该周期
        method 不为 'failed'（mock 下走 pending 分支 success=True）。

T7（Vault 导出聚合重构）：
  - TC3 聚合分组装载：load_knowledge_grouped 按 domain+单 tag（skill）/
        project+module（business）聚合；business 空 module 归 '未分类模块'。
  - TC4 聚合导出写盘：export_all_knowledge 写出 Cards/{domain}/{tag}.md 与
        Efforts/{project}/{module}.md 聚合文件，**不**生成逐点 title 文件。

运行:
    cd D:/WorkSpace/Code/devPartner
    TEST_ENV=true LLM_TEST_MODE=mock TEST_DB=:memory: \
        .venv/Scripts/python.exe -m pytest tests/test_kb_rectify_t6t7.py -v
"""

import json

import backend.core.database.base_conn as base_conn
import pytest
from backend.business.task_handlers.reports import (
    generate_weekly_report,
    query_period_data,
)
from backend.business.vault_export.md_data_loader import load_knowledge_grouped
from backend.business.vault_export.vault_exporter import (
    VaultExporter,
    get_vault_exporter,
)
from backend.core.database.base_conn import Database

# 参考 t1t2/t3t4t5 的取库方式：Database() + init_local 临时库 + monkeypatch 单例
# （conftest 已 autouse 注入 TEST_ENV/LLM_TEST_MODE=TEST_DB 环境变量）。


# ════════════════════════════════════════════════════════════════
# 测试夹具
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """提供一个全新的临时库，并把 get_db() 单例指向它。

    generate_weekly_report / load_knowledge_grouped / export_all_knowledge
    内部均通过 get_db() 取库，必须让单例指向本测试实例。
    """
    db = Database()
    db.init_local(str(tmp_path / "fresh_kb.db"))
    monkeypatch.setattr(base_conn, "_db_instance", db)
    yield db
    db.close()
    monkeypatch.setattr(base_conn, "_db_instance", None)


@pytest.fixture
def temp_vault(monkeypatch, tmp_path):
    """用临时 Vault 根的 exporter 替换全局 get_vault_exporter，避免写真实库。

    generate_weekly_report 内部会调用 get_vault_exporter() 拿到 exporter，
    必须将其指向 tmp_path/vault，否则会触碰 data/Knowledge Library 真实目录。
    """
    exporter = VaultExporter(vault_root=str(tmp_path / "vault"))
    ve_module = __import__(
        "backend.business.vault_export.vault_exporter",
        fromlist=["get_vault_exporter"],
    )
    monkeypatch.setattr(ve_module, "get_vault_exporter", lambda: exporter)
    yield exporter
    monkeypatch.setattr(ve_module, "get_vault_exporter", get_vault_exporter)


# ════════════════════════════════════════════════════════════════
# T6: 报告链路真实数据重构
# ════════════════════════════════════════════════════════════════


def test_t6_tc1_empty_period_explicit_failure(fresh_db, temp_vault):
    """T6-TC1: 历史无数据周期，generate_weekly_report 必须显式失败，
    不静默 success，且不写出任何 MD 报告文件。

    关键点：证明「假数据流」已根绝——旧逻辑读 Calendar/*.md 缺失时静默
    success=True；新逻辑直接查 DB 真实数据，缺失即返回 failed。
    """
    # 2020-01-01 所在周（周一 2019-12-30 ~ 周日 2020-01-05）在临时库无任何数据
    result = generate_weekly_report(target_date="2020-01-01")

    # 1) 显式失败，不再假 success
    assert result["success"] is False, f"无数据周期应失败，实际: {result}"
    assert result["method"] == "failed", f"无数据周期 method 应为 failed，实际: {result}"
    assert "error" in result and result["error"], f"应含明确错误信息，实际: {result}"

    # 2) 不应写出任何 MD 报告文件（Reports/Weekly 目录应无 .md）
    weekly_dir = temp_vault._reports_dir / "Weekly"
    md_files = list(weekly_dir.glob("*.md")) if weekly_dir.exists() else []
    assert md_files == [], (
        f"无数据周期不应写出任何周报 MD，实际写出: {[str(f) for f in md_files]}"
    )


def test_t6_tc2_with_data_period_success(fresh_db, temp_vault, monkeypatch):
    """T6-TC2: 有真实数据的周期，generate_weekly_report 不应失败。

    直接以目标周期插入 1 对话 + 2 知识点（created_at 显式落在周期内），
    先断言 query_period_data 能查到真实计数（证明报告数据来自 DB 而非幻觉），
    再断言 generate_weekly_report 在有数据时 method 不为 'failed'
    （mock 下 LLM 不可用 → pending 分支 success=True）。
    """
    # 目标周期：2026 年第 1 周（周一 2026-01-05 ~ 周日 2026-01-11）
    target_date = "2026-01-05"
    period_start = "2026-01-05"
    period_end = "2026-01-11"
    # 周期内一个确定时间点（ISO 含 T，落在 end_bound 之前）
    ts = "2026-01-06T10:00:00"

    # 1) 插入 1 条对话（created_at 在周期内）
    fresh_db.query_local(
        "INSERT INTO conversations "
        "(conversation_id, topic, task_type, created_at, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        ("conv_t6", "测试对话", "learn", ts, ts),
    )
    # 2) 插入 2 条 skill 知识点（created_at 在周期内，source_id=conv_t6）
    fresh_db.query_local(
        "INSERT INTO knowledge_points "
        "(knowledge_id, title, content, category, domain, tags, source_id, type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'skill', ?)",
        (
            "kp_t6_a",
            "知识点A",
            "内容A",
            "concept",
            "Python",
            json.dumps(["装饰器"], ensure_ascii=False),
            "conv_t6",
            ts,
        ),
    )
    fresh_db.query_local(
        "INSERT INTO knowledge_points "
        "(knowledge_id, title, content, category, domain, tags, source_id, type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'skill', ?)",
        (
            "kp_t6_b",
            "知识点B",
            "内容B",
            "concept",
            "Python",
            json.dumps(["闭包"], ensure_ascii=False),
            "conv_t6",
            ts,
        ),
    )

    # 先验证 query_period_data 能查到真实计数（核心 T6 断言：报告数据源自 DB）
    pd = query_period_data(period_start, period_end)
    assert pd["conversation_count"] == 1, f"应查到 1 条对话，实际: {pd}"
    assert pd["knowledge_count"] == 2, f"应查到 2 条知识点，实际: {pd}"

    # mock 模式：让 LLM 不可用，使有数据分支落入 pending（success=True），
    # 避免依赖真实 LLM 推断，专注验证「有数据即不失败」的 gates。
    from backend.business.task_handlers import daily_summary as ds_mod

    monkeypatch.setattr(ds_mod, "_check_llm_available", lambda flag: (False, "mock"))

    result = generate_weekly_report(target_date=target_date)
    assert result["success"] is True, f"有数据周期应成功，实际: {result}"
    assert result["method"] != "failed", (
        f"有数据周期 method 不应为 failed，实际: {result}"
    )


# ════════════════════════════════════════════════════════════════
# T7: Vault 导出聚合重构
# ════════════════════════════════════════════════════════════════


def _seed_knowledge(fresh_db):
    """向临时库写入 8 条知识点：4 skill（Python 两 tag 各 2）+ 4 business（devPartner 两 module 各 2）。"""
    # 4 条 skill：同 domain=Python，两个 tag 各 2 条
    fresh_db.insert_knowledge_point(
        title="S1", content="c1", category="concept",
        domain="Python", tags=["装饰器"], source_id="c1",
    )
    fresh_db.insert_knowledge_point(
        title="S2", content="c2", category="concept",
        domain="Python", tags=["装饰器"], source_id="c2",
    )
    fresh_db.insert_knowledge_point(
        title="S3", content="c3", category="concept",
        domain="Python", tags=["闭包"], source_id="c3",
    )
    fresh_db.insert_knowledge_point(
        title="S4", content="c4", category="concept",
        domain="Python", tags=["闭包"], source_id="c4",
    )
    # 4 条 business：同 project=devPartner，两个 module 各 2 条（其一留空 → 未分类模块）
    fresh_db.insert_knowledge_point(
        title="B1", content="b1", category="concept",
        domain="devPartner", tags=["报告生成"], source_id="c1",
        kp_type="business", module="报告生成",
    )
    fresh_db.insert_knowledge_point(
        title="B2", content="b2", category="concept",
        domain="devPartner", tags=["报告生成"], source_id="c2",
        kp_type="business", module="报告生成",
    )
    fresh_db.insert_knowledge_point(
        title="B3", content="b3", category="concept",
        domain="devPartner", tags=["task管理"], source_id="c3",
        kp_type="business", module="",
    )
    fresh_db.insert_knowledge_point(
        title="B4", content="b4", category="concept",
        domain="devPartner", tags=["task管理"], source_id="c4",
        kp_type="business", module="",
    )


def test_t7_tc3_grouped_loading(fresh_db):
    """T7-TC3: load_knowledge_grouped 按 domain+单 tag（skill）/
    project+module（business）聚合；business 空 module 归 '未分类模块'。"""
    _seed_knowledge(fresh_db)

    grouped = load_knowledge_grouped()

    # skill[Python] 含两个 tag 键，各 2 条
    py = grouped["skill"].get("Python")
    assert py is not None, (
        f"skill 应含 Python 域，实际 keys: {list(grouped['skill'].keys())}"
    )
    assert set(py.keys()) == {"装饰器", "闭包"}, (
        f"skill[Python] tag 键应为 装饰器/闭包，实际: {set(py.keys())}"
    )
    assert len(py["装饰器"]) == 2, (
        f"skill[Python][装饰器] 应 2 条，实际: {len(py['装饰器'])}"
    )
    assert len(py["闭包"]) == 2, (
        f"skill[Python][闭包] 应 2 条，实际: {len(py['闭包'])}"
    )

    # business[devPartner] 含两个 module 键（含 未分类模块），各 2 条
    dp = grouped["business"].get("devPartner")
    assert dp is not None, (
        f"business 应含 devPartner 项目，实际 keys: {list(grouped['business'].keys())}"
    )
    assert set(dp.keys()) == {"报告生成", "未分类模块"}, (
        f"business[devPartner] module 键应含 未分类模块，实际: {set(dp.keys())}"
    )
    assert len(dp["报告生成"]) == 2, (
        f"business[devPartner][报告生成] 应 2 条，实际: {len(dp['报告生成'])}"
    )
    assert len(dp["未分类模块"]) == 2, (
        f"business[devPartner][未分类模块] 应 2 条，实际: {len(dp['未分类模块'])}"
    )


def test_t7_tc4_grouped_export_writes_aggregate_files(fresh_db, tmp_path):
    """T7-TC4: export_all_knowledge 按聚合写出 Cards/{domain}/{tag}.md 与
    Efforts/{project}/{module}.md，且不生成逐点 title 文件。"""
    _seed_knowledge(fresh_db)

    vault_root = tmp_path / "vault"
    exporter = VaultExporter(vault_root=str(vault_root))
    result = exporter.export_all_knowledge()

    assert result["errors"] == [], f"导出不应有错误: {result['errors']}"
    # 4 个聚合文件（2 skill + 2 business）聚合写出全部 8 条知识点
    assert result["total"] == 8, f"total 应为 8，实际: {result['total']}"
    assert result["exported"] == 4, (
        f"exported 应为 4（2 Cards + 2 Efforts），实际: {result['exported']}"
    )

    # Cards/Python/{tag1}.md, {tag2}.md
    cards_py = vault_root / "Cards" / "Python"
    card_files = {p.name for p in cards_py.glob("*.md")}
    assert card_files == {"装饰器.md", "闭包.md"}, (
        f"Cards/Python 应仅含聚合 tag 文件，实际: {card_files}"
    )

    # Efforts/devPartner/{module1}.md, {module2/未分类模块}.md
    efforts_dp = vault_root / "Efforts" / "devPartner"
    effort_files = {p.name for p in efforts_dp.glob("*.md")}
    assert effort_files == {"报告生成.md", "未分类模块.md"}, (
        f"Efforts/devPartner 应仅含聚合 module 文件，实际: {effort_files}"
    )

    # 关键：不应以 title 命名逐点文件（如 S1.md / B1.md）
    assert not any(
        p.name in {"S1.md", "S2.md", "S3.md", "S4.md", "B1.md", "B2.md", "B3.md", "B4.md"}
        for p in cards_py.glob("*.md")
    ), "不应生成逐点 title 命名的碎片文件"
    assert not any(
        p.name in {"S1.md", "S2.md", "B3.md", "B4.md"}
        for p in efforts_dp.glob("*.md")
    ), "Efforts 不应生成逐点 title 命名的碎片文件"

    # 读取一个聚合文件，确认内含多条知识点清单（而非单点文件）
    agg = (cards_py / "装饰器.md").read_text(encoding="utf-8")
    assert "## 📇 知识点清单" in agg, "聚合文件应含知识点清单段落"
    bullets = [line for line in agg.splitlines() if line.strip().startswith("- **")]
    assert len(bullets) == 2, (
        f"装饰器聚合文件应含 2 条知识点清单，实际: {len(bullets)}"
    )
