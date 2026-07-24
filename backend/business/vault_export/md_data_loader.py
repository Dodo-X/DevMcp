"""
MD 数据装载层 (Data Loading Layer) — 三层架构中的「数据装载」
============================================================

职责边界（清晰分层，降低耦合）：
  - 模板管理 (md_templates.py)：定义、注册、选择模板，不碰 DB / 文件。
  - 数据装载 (本模块)：从 DB / 文件系统读取原始数据，解析、填充、预处理，
    产出纯 dict 交由模板/导出层消费。不定义模板，不写文件。
  - 导出 (md_exporter.py / vault_exporter.py)：取已装载的数据 → 渲染 → 写文件。

接口契约：
  本层所有 load_* / normalize_* / scan_* 函数均返回 dict / list / 基础类型，
  供上游直接塞进 MdTemplate 的 data dict 或 VaultExporter 的渲染逻辑。
  任何异常都被捕获并降级为警告日志 + 安全默认值，不向上抛，保证导出链路非致命。
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 基础设施
# ══════════════════════════════════════════════════════════


def _get_db():
    """延迟获取线程安全 DB 单例（避免模块导入期触发 DB 初始化）。"""
    from backend.core.database.base_conn import get_db

    return get_db()


def normalize_json(raw: Any, default: Any) -> Any:
    """
    安全解析 JSON 字符串。

    - 已是 list/dict 直接返回（调用方可能传入已解析对象）
    - 空值返回 default
    - 解析失败返回 default（不抛异常，保证装载链路非致命）
    """
    if not raw:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def derive_project_name() -> str:
    """从当前工作目录推导项目名（仪表盘/卡片缺省归属用）。"""
    return os.path.basename(os.getcwd())


# ══════════════════════════════════════════════════════════
# 知识点 / 对话
# ══════════════════════════════════════════════════════════


def load_knowledge_summary_rows(conversation_id: str) -> list[dict]:
    """
    读取某对话的全部知识点行。

    v9.9.2 兼容：source_id 可能是 step_id（step_analysis 写入）或
    conversation_id（finalize 知识提取写入），用 IN 一次兼容两种来源。

    Returns: knowledge_points 行组成的 list（已 dict 化），异常时返回 []。
    """
    db = _get_db()
    try:
        step_rows = db.query_local(
            "SELECT step_id FROM conversation_steps WHERE conversation_id = ?",
            (conversation_id,),
        )
        step_ids = [s["step_id"] for s in (step_rows or []) if s.get("step_id")]
        source_ids = step_ids + [conversation_id]
        placeholders = ",".join("?" for _ in source_ids)
        kp_rows = db.query_local(
            f"SELECT knowledge_id, title, content, category, domain, tags, created_at "
            f"FROM knowledge_points WHERE source_id IN ({placeholders}) ORDER BY created_at",
            tuple(source_ids),
        )
        return [dict(r) for r in (kp_rows or [])]
    except Exception as e:
        logger.warning("读取对话知识点失败 [%s]: %s", conversation_id, e)
        return []


def normalize_knowledge_rows(kp_rows: list[dict]) -> dict:
    """
    将知识点行归一化为 {domain: [item, ...]} 结构，并解析 tags JSON。

    Returns: {"General": [{"title", "content", "category", "tags"}, ...], ...}
    """
    domains: dict[str, list[dict]] = {}
    for row in kp_rows or []:
        domain = row.get("domain", "General") or "General"
        domains.setdefault(domain, [])
        tags_raw = row.get("tags", "")
        if isinstance(tags_raw, str):
            tags = normalize_json(tags_raw, [])
            if not isinstance(tags, list):
                tags = [tags_raw] if tags_raw else []
        elif isinstance(tags_raw, list):
            tags = tags_raw
        else:
            tags = []
        domains[domain].append(
            {
                "title": row.get("title", "") or "未命名",
                "content": (row.get("content", "") or "")[:3000],
                "category": row.get("category", "skill") or "skill",
                "tags": tags,
            }
        )
    return domains


# ══════════════════════════════════════════════════════════
# 用户画像 / 项目画像
# ══════════════════════════════════════════════════════════


def load_user_profile() -> dict | None:
    """
    读取用户画像维度数据。

    Returns: {dimension: {value, confidence, trend, observation_count}}，
             无数据或异常时返回 None。
    """
    db = _get_db()
    try:
        rows = db.query_local(
            "SELECT dimension, value, confidence, trend, observation_count FROM user_profile"
        )
        if not rows:
            return None
        data: dict[str, dict] = {}
        for row in rows:
            data[row["dimension"]] = {
                "value": row["value"],
                "confidence": row["confidence"],
                "trend": row["trend"],
                "observation_count": row["observation_count"],
            }
        return data
    except Exception as e:
        logger.warning("读取用户画像失败: %s", e)
        return None


def load_project_profile_row(system_id: str) -> dict | None:
    """
    读取 connected_systems 中某系统的项目画像原始行。

    Returns: dict（已 dict 化）或 None。
    """
    db = _get_db()
    try:
        rows = db.query_local("SELECT * FROM connected_systems WHERE system_id = ?", (system_id,))
        return dict(rows[0]) if rows else None
    except Exception as e:
        logger.warning("读取项目画像失败 [%s]: %s", system_id, e)
        return None


# ══════════════════════════════════════════════════════════
# 知识卡片
# ══════════════════════════════════════════════════════════


def load_knowledge_card(knowledge_id: str) -> dict | None:
    """
    根据 knowledge_id 查询单张卡片原始行。

    Returns: dict 或 None（查不到 / 异常）。
    """
    db = _get_db()
    try:
        rows = db.query_local(
            "SELECT * FROM knowledge_points WHERE knowledge_id = ? LIMIT 1", (knowledge_id,)
        )
        return dict(rows[0]) if rows else None
    except Exception as e:
        logger.warning("读取知识卡片失败 [%s]: %s", knowledge_id, e)
        return None


def load_all_knowledge_rows() -> list[dict]:
    """全量读取知识点（id + type），供批量重导使用。异常时返回 []。"""
    db = _get_db()
    try:
        rows = db.query_local("SELECT knowledge_id, type FROM knowledge_points ORDER BY id")
        return [dict(r) for r in (rows or [])]
    except Exception as e:
        logger.warning("全量读取知识点失败: %s", e)
        return []


def normalize_card_data(kp_row: dict) -> dict:
    """
    预处理单张卡片数据：解析 tags / aliases / related JSON 字段，输出渲染所需结构。

    这是「数据装载」层的典型职责——把 DB 里的原始字符串字段
    解析、填充为渲染器可直接消费的规整 dict。

    Returns: {
        knowledge_id, title, content, domain,
        tags(list), created_at, source_id, aliases(list), related_knowledge_ids(str)
    }
    """
    return {
        "knowledge_id": kp_row.get("knowledge_id", ""),
        "title": kp_row.get("title", "未命名"),
        "content": kp_row.get("content", ""),
        "domain": kp_row.get("domain", "General"),
        "tags": normalize_json(kp_row.get("tags", "[]"), []),
        "created_at": kp_row.get("created_at", ""),
        "source_id": kp_row.get("source_id", ""),
        "aliases": normalize_json(kp_row.get("aliases", "[]"), []),
        "related_knowledge_ids": kp_row.get("related_knowledge_ids", ""),
    }


def load_knowledge_grouped() -> dict:
    """
    按 domain+单 tag（skill）与 project+module（business）聚合装载全部知识点。

    T7 聚合导出数据源：替代旧的逐点 _export_card。

    Returns:
        {
          'skill':    {domain: {tag: [point_dict, ...]}},
          'business': {project: {module: [point_dict, ...]}},   # project = domain（= system_id）
        }
        point_dict 已 dict 化；tags 已解析为 [tag]（取首个有效标签）。
        business 的 module 为空时归入 "未分类模块"。
    """
    db = _get_db()
    out: dict = {"skill": {}, "business": {}}
    try:
        rows = db.query_local(
            "SELECT knowledge_id,title,content,domain,tags,module,type,source_id,created_at "
            "FROM knowledge_points ORDER BY created_at"
        ) or []
        for row in rows:
            r = dict(row)
            tag = (normalize_json(r["tags"], []) or [""])[0] or ""
            if r["type"] == "skill":
                out["skill"].setdefault(r["domain"], {}).setdefault(tag, []).append(r)
            else:
                out["business"].setdefault(r["domain"], {}).setdefault(
                    r["module"] or "未分类模块", []
                ).append(r)
    except Exception as e:
        logger.warning("load_knowledge_grouped 查询失败（P-17 收口）: %s", e, exc_info=True)
    return out


# ══════════════════════════════════════════════════════════
# 项目仪表盘（文件系统扫描 + 预处理）
# ══════════════════════════════════════════════════════════


def scan_dashboard_data(vault_root: Path, project: str) -> dict:
    """
    扫描 Calendar/ 与 Cards/ 目录，汇总项目仪表盘所需的预处理数据。

    仪表盘 MD 完全自包含（不依赖 SQLite），因此数据来源是文件系统。
    本函数只做「读取 + 预处理」，MD 拼接仍由导出层完成。

    Returns: {
        safe_project, daily_reports(list[str]),
        business_count(int), skill_count(int), skill_links(list[str])
    }
    """
    safe_project = re.sub(r'[<>:"/\\|?*]', "-", project).strip()
    calendar_dir = vault_root / "Calendar"
    cards_dir = vault_root / "Cards"
    efforts_dir = vault_root / "Efforts" / safe_project

    daily_reports: list[str] = []
    if calendar_dir.exists():
        for md_file in sorted(calendar_dir.glob("*.md"), reverse=True):
            try:
                content = md_file.read_text(encoding="utf-8")
                match = re.search(r"projects:\s*\[(.*?)\]", content[:500])
                if match and safe_project in match.group(1):
                    daily_reports.append(md_file.stem)
            except Exception as e:
                logger.warning("扫描日报失败 [%s]: %s", md_file, e)

    # T7：新布局 Efforts/{project}/{module}.md，兼容旧 业务知识/ 子目录
    business_count = 0
    if efforts_dir.exists():
        for md_file in efforts_dir.glob("*.md"):
            if md_file.name not in ("项目仪表盘.md", "项目画像.md"):
                business_count += 1
        legacy = efforts_dir / "业务知识"
        if legacy.exists():
            business_count += len(list(legacy.glob("*.md")))

    skill_count = 0
    skill_links: list[str] = []
    if cards_dir.exists():
        for card_file in cards_dir.rglob("*.md"):
            try:
                content = card_file.read_text(encoding="utf-8")
                if safe_project in content[:1000]:
                    skill_count += 1
                    rel_path = card_file.relative_to(vault_root)
                    # 统一为正斜杠，保证跨平台 wikilink（[[Cards/...]]）有效
                    skill_links.append(str(rel_path.with_suffix("")).replace("\\", "/"))
            except Exception as e:
                logger.warning("扫描技能卡片失败 [%s]: %s", card_file, e)

    return {
        "safe_project": safe_project,
        "daily_reports": daily_reports,
        "business_count": business_count,
        "skill_count": skill_count,
        "skill_links": skill_links,
    }
