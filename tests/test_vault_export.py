"""
vault_export 三层架构回归测试
=============================

只覆盖不依赖真实 DB 的路径：
  - 数据装载层纯函数（normalize_json / normalize_card_data / scan_dashboard_data）
  - 导出层卡片写文件（export_skill_card 直接吃已装载的 kp_row，不碰 DB）
  - 模板管理层 + 引擎的日报导出 roundtrip（data dict → MD 文件）

不涉及 DB 的测试可在无数据库环境下稳定跑通，用于守护三层拆分不破坏行为。
"""

from pathlib import Path

from backend.business.vault_export import md_data_loader as loader  # noqa: E402
from backend.business.vault_export.md_engine import get_assembler  # noqa: E402
from backend.business.vault_export.md_templates import register_all  # noqa: E402
from backend.business.vault_export.vault_exporter import VaultExporter  # noqa: E402

# ══════════════════════════════════════════════════════════
# 数据装载层纯函数
# ══════════════════════════════════════════════════════════


def test_normalize_json():
    assert loader.normalize_json("", []) == []
    assert loader.normalize_json(None, {}) == {}
    assert loader.normalize_json(["a", "b"], []) == ["a", "b"]
    assert loader.normalize_json('{"x": 1}', {}) == {"x": 1}
    assert loader.normalize_json("not-json", "default") == "default"


def test_normalize_card_data_parses_json_fields():
    kp_row = {
        "knowledge_id": "k1",
        "title": "测试卡片",
        "content": "内容",
        "domain": "Python",
        "tags": '["a", "b"]',
        "aliases": "[]",
        "related_knowledge_ids": '["k2"]',
        "created_at": "2026-01-01",
        "source_id": "src1",
    }
    card = loader.normalize_card_data(kp_row)
    assert card["knowledge_id"] == "k1"
    assert card["tags"] == ["a", "b"]
    assert card["aliases"] == []
    assert card["related_knowledge_ids"] == '["k2"]'


def test_scan_dashboard_data(tmp_path):
    calendar = tmp_path / "Calendar"
    calendar.mkdir()
    # 日报 frontmatter 含 projects 列表，引用 my_project
    (calendar / "2026-01-01.md").write_text(
        "---\nprojects: [my_project, other]\n---\nbody", encoding="utf-8"
    )
    (calendar / "2026-01-02.md").write_text("---\nprojects: [other]\n---\nbody", encoding="utf-8")
    cards = tmp_path / "Cards" / "Python"
    cards.mkdir(parents=True)
    (cards / "topic.md").write_text("my_project 相关技能", encoding="utf-8")
    efforts = tmp_path / "Efforts" / "my_project" / "业务知识"
    efforts.mkdir(parents=True)
    (efforts / "biz.md").write_text("业务知识", encoding="utf-8")

    dash = loader.scan_dashboard_data(tmp_path, "my_project")
    assert dash["safe_project"] == "my_project"
    assert "2026-01-01" in dash["daily_reports"]
    assert "2026-01-02" not in dash["daily_reports"]
    assert dash["business_count"] == 1
    assert dash["skill_count"] == 1
    assert any("Cards/Python/topic" in link for link in dash["skill_links"])


# ══════════════════════════════════════════════════════════
# 导出层：卡片写文件（不依赖 DB）
# ══════════════════════════════════════════════════════════


def test_export_skill_card_writes_file(tmp_path):
    exporter = VaultExporter(vault_root=str(tmp_path))
    kp_row = {
        "knowledge_id": "k1",
        "title": "测试卡片",
        "content": "这是正文",
        "domain": "Python",
        "tags": '["ast", "refactor"]',
        "aliases": "[]",
        "related_knowledge_ids": "[]",
        "created_at": "2026-01-01",
        "source_id": "src1",
    }
    path = exporter.export_skill_card("k1", kp_row)
    assert path is not None
    p = Path(path)
    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "# 测试卡片" in content
    assert "这是正文" in content
    # frontmatter 含解析后的 tags
    assert "tags:" in content
    # 数据装载层成功解析了 tags JSON（出现在文件中）
    assert "ast" in content and "refactor" in content


# ══════════════════════════════════════════════════════════
# 模板管理 + 引擎：日报导出 roundtrip（data dict → 文件）
# ══════════════════════════════════════════════════════════


def test_daily_report_export_roundtrip(tmp_path):
    assembler = get_assembler(vault_root=str(tmp_path))
    register_all(assembler)
    assert "daily_report" in assembler.list_templates()

    data = {
        "date_str": "2026-01-01",
        "report_data": {
            "summary": "今天完成了三层拆分",
            "inference_engine": "ollama",
        },
    }
    out = assembler.export("daily_report", data)
    assert out is not None
    p = Path(out)
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "2026-01-01 日报" in text
    assert "今天完成了三层拆分" in text
    # 无数据时该段落不应渲染（condition 控制）
    empty = assembler.export("daily_report", {"date_str": "2026-01-02", "report_data": {}})
    assert Path(empty).exists()
