"""
Obsidian Vault 导出器 v2.3
==========================

将知识卡片和报告导出为 Obsidian Vault 兼容的 Markdown 文件。

v2.3 变更（模板引擎重构）：
- ★ VaultExporter 作为 facade，内部委托给 MdAssembler 统一装配
- ★ 模板定义独立于 md_templates.py，每种文档类型 = 一个 MdTemplate 实例
- ★ 低耦合：新增 MD 类型只需在 md_templates.py 注册新模板，不改引擎代码
- ★ 渲染器函数可复用（render_text / render_kv / render_list 等通用零件）

v2.2 变更：
- ★ 统一 MD 生成流水线：模板定义 + 数据装载 → MD 文档
- ★ 所有导出链路自动触发（finalize 阶段知识提取后 → export_batch，日报生成后 → export_all）

目录结构：
  data/Knowledge Library/
  ├── Cards/{domain}/              # 技能知识卡片
  ├── Efforts/{project}/业务知识/   # 业务知识卡片
  ├── Efforts/{project}/项目仪表盘.md
  ├── Efforts/{project}/项目画像.md
  ├── Atlas/用户画像.md
  ├── Calendar/{YYYY-MM-DD}.md     # 日报
  └── Reports/{Weekly,Montly,Annual}/  # 周/月/年报
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .md_engine import get_assembler

logger = logging.getLogger(__name__)


class VaultExporter:
    """Obsidian Vault Markdown 导出器（v2.3 — facade，委托 MdAssembler）"""

    def __init__(self, vault_root: str = None):
        """
        Args:
            vault_root: Vault 根目录，默认 data/Knowledge Library/
        """
        if vault_root:
            self._vault_root = Path(vault_root)
        else:
            self._vault_root = Path(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                    "data",
                    "Knowledge Library",
                )
            )
        self._vault_root.mkdir(parents=True, exist_ok=True)
        self._db = None
        self._atlas_dir = self._vault_root / "Atlas"
        self._atlas_dir.mkdir(parents=True, exist_ok=True)
        self._calendar_dir = self._vault_root / "Calendar"
        self._calendar_dir.mkdir(parents=True, exist_ok=True)
        self._reports_dir = self._vault_root / "Reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        (self._reports_dir / "Weekly").mkdir(parents=True, exist_ok=True)
        (self._reports_dir / "Monthly").mkdir(parents=True, exist_ok=True)
        (self._reports_dir / "Annual").mkdir(parents=True, exist_ok=True)

        # v2.3: 初始化 MD 装配器 + 注册所有模板
        self._assembler = get_assembler(vault_root=str(self._vault_root) if vault_root else None)
        from .md_templates import register_all

        register_all(self._assembler)

    @property
    def db(self):
        if self._db is None:
            from backend.core.database.base_conn import get_db

            self._db = get_db()
        return self._db

    # ══════════════════════════════════════════════════════════
    # 公开方法
    # ══════════════════════════════════════════════════════════

    def export_skill_card(self, kp_id: str, kp_row: dict = None) -> str | None:
        """
        导出一张技能卡片到 Cards/{domain}/{id}_{title}.md

        Args:
            kp_id: knowledge_id
            kp_row: 如果已查好行数据可传入避免重复查询

        Returns:
            文件路径，如果跳过则返回 None
        """
        if kp_row is None:
            kp_row = self._get_knowledge_by_id(kp_id)
        if not kp_row:
            return None

        return self._export_card(kp_row, card_type="skill")

    def export_business_card(self, kp_id: str, kp_row: dict = None) -> str | None:
        """
        导出一张业务知识卡片到 Efforts/{project}/业务知识/{id}_{title}.md
        """
        if kp_row is None:
            kp_row = self._get_knowledge_by_id(kp_id)
        if not kp_row:
            return None

        return self._export_card(kp_row, card_type="business")

    def export_batch(
        self,
        conversation_id: str = "",
        project: str = "",
        summary: str = "",
        key_decisions: list = None,
        steps_summary: list = None,
        knowledge_ids: list = None,
    ) -> dict[str, Any]:
        """
        批量导出知识卡片（仅导出知识卡片，对话/统计走 SQLite DB 插件）。

        v2.1：不再导出对话 MD 文件，对话列表和统计由 Obsidian SQLite DB 插件直连查询。
        """
        result = {
            "skills_exported": 0,
            "business_exported": 0,
            "errors": [],
        }
        project = project or self._derive_project_name()

        # 按 knowledge_ids 逐一导出知识卡片
        for kid in knowledge_ids or []:
            try:
                kp_row = self._get_knowledge_by_id(kid)
                if not kp_row:
                    continue

                kp_type = kp_row.get("type", "skill")
                if kp_type == "business":
                    path = self.export_business_card(kid, kp_row)
                    if path:
                        result["business_exported"] += 1
                else:
                    path = self.export_skill_card(kid, kp_row)
                    if path:
                        result["skills_exported"] += 1
            except Exception as e:
                logger.warning(
                    "VaultExporter.export_batch: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                result["errors"].append(f"知识导出失败 [{kid}]: {e}")

        # 生成/更新项目仪表盘（SQL 驱动）
        try:
            self._write_project_dashboard(project)
            logger.info(f"📊 项目仪表盘已更新: {project}")
        except Exception as e:
            logger.warning(
                "VaultExporter.export_batch: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["errors"].append(f"仪表盘生成失败: {e}")

        logger.info(
            f"📤 Vault 批量导出完成: "
            f"业务={result['business_exported']}, "
            f"技能={result['skills_exported']}, "
            f"错误={len(result['errors'])}"
        )
        return result

    def export_all_knowledge(self) -> dict[str, Any]:
        """
        全量重导所有知识点到 MD 文件（v8.0：移除 auto_synced_to_md 过滤，始终全量导出）

        Returns:
            {"total": N, "exported": N, "skipped": N, "errors": [...]}
        """
        result = {"total": 0, "exported": 0, "skipped": 0, "errors": []}
        try:
            rows = self.db.query_local(
                "SELECT knowledge_id, type FROM knowledge_points ORDER BY id"
            )
            result["total"] = len(rows or [])
            for row in rows or []:
                try:
                    kp_row = self._get_knowledge_by_id(row["knowledge_id"])
                    if not kp_row:
                        result["skipped"] += 1
                        continue
                    kp_type = row.get("type", "skill")
                    if kp_type == "business":
                        path = self.export_business_card(row["knowledge_id"], kp_row)
                    else:
                        path = self.export_skill_card(row["knowledge_id"], kp_row)
                    if path:
                        result["exported"] += 1
                    else:
                        result["skipped"] += 1
                except Exception as e:
                    logger.warning(
                        "VaultExporter.export_all_knowledge: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    result["errors"].append(f"导出失败 [{row['knowledge_id']}]: {e}")
        except Exception as e:
            logger.warning(
                "VaultExporter.export_all_knowledge: 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            result["errors"].append(f"全量导出失败: {e}")
        return result

    def export_profile_to_vault(self, profile_data: dict, date_str: str) -> str | None:
        """导出用户画像到 Atlas/用户画像.md（v2.3: 委托 MdAssembler）"""
        return self._assembler.export(
            "user_profile",
            {
                "profile_data": profile_data,
                "date_str": date_str,
            },
        )

    def export_project_to_vault(self, system_id: str, project_data: dict) -> str | None:
        """导出项目画像到 Efforts/{system_id}/项目画像.md（v2.3: 委托 MdAssembler）"""
        return self._assembler.export(
            "project_profile",
            {
                "system_id": system_id,
                "project_data": project_data,
            },
        )

    def export_daily_report(self, date_str: str, report_data: dict) -> str | None:
        """
        导出日报到 Calendar/{date}.md（v2.3: 委托 MdAssembler）
        """
        path = self._assembler.export(
            "daily_report",
            {
                "date_str": date_str,
                "report_data": report_data,
            },
        )

        # 日报导出后自动更新关联项目的仪表盘
        if path:
            projects = (report_data.get("project_analysis") or {}).get("projects", [])
            for p in projects:
                pname = p.get("project_name", "")
                if pname:
                    try:
                        self._write_project_dashboard(pname)
                    except Exception as e:
                        logger.warning(f"⚠️ 项目仪表盘更新失败 [{pname}]: {e}")

        return path

    def export_weekly_report(
        self, period_start: str, period_end: str, report_data: dict
    ) -> str | None:
        """导出周报到 Reports/Weekly/{period}.md（v2.3: 委托 MdAssembler）"""
        return self._assembler.export(
            "weekly_report",
            {
                "period_start": period_start,
                "period_end": period_end,
                "report_data": report_data,
            },
        )

    def export_monthly_report(
        self, period_start: str, period_end: str, report_data: dict
    ) -> str | None:
        """导出月报到 Reports/Monthly/{YYYY-MM}.md（v2.3: 委托 MdAssembler）"""
        return self._assembler.export(
            "monthly_report",
            {
                "period_start": period_start,
                "period_end": period_end,
                "report_data": report_data,
            },
        )

    def export_annual_report(self, year: str, report_data: dict) -> str | None:
        """导出年报到 Reports/Annual/{YYYY}.md（v2.3: 委托 MdAssembler）"""
        return self._assembler.export(
            "annual_report",
            {
                "year": year,
                "report_data": report_data,
            },
        )

    def get_latest_report_date(self, report_type: str) -> str | None:
        """
        获取最新报告的日期标识（v8.0 — 文件名即计算节点）

        通过扫描文件名即可确定下次报告的触发时间，无需时刻扫描数据库。

        Args:
            report_type: 'weekly' / 'monthly' / 'annual'

        Returns:
            最新报告的日期标识，如 '2026-W28' / '2026-07' / '2026'
        """
        type_dir_map = {
            "weekly": self._reports_dir / "Weekly",
            "monthly": self._reports_dir / "Monthly",
            "annual": self._reports_dir / "Annual",
        }
        target_dir = type_dir_map.get(report_type)
        if not target_dir or not target_dir.exists():
            return None

        md_files = sorted(target_dir.glob("*.md"), reverse=True)
        if not md_files:
            return None

        return md_files[0].stem

    # ══════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════

    def _export_card(self, kp_row: dict, card_type: str) -> str | None:
        """
        统一导出卡片（技能或业务知识）。

        Args:
            kp_row: knowledge_points 行数据
            card_type: 'skill' 或 'business'

        Returns:
            文件路径，如果跳过则返回 None
        """
        kp_id = kp_row.get("knowledge_id", "")
        title = kp_row.get("title", "未命名")
        content = kp_row.get("content", "")
        domain = kp_row.get("domain", "General")
        tags = self._safe_json(kp_row.get("tags", "[]"), [])
        created_at = kp_row.get("created_at", "")
        source_id = kp_row.get("source_id", "")
        self._safe_json(kp_row.get("aliases", "[]"), [])
        related_ids_raw = kp_row.get("related_knowledge_ids", "")

        if card_type == "skill":
            dir_path = self._vault_root / "Cards" / self._sanitize_path(domain)
        else:
            project = domain or self._derive_project_name()
            dir_path = self._vault_root / "Efforts" / self._sanitize_path(project) / "业务知识"

        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{self._sanitize_filename(title)}.md"

        # ── 关联链接 ──
        related_links = self._build_related_links(related_ids_raw)

        # ── 来源引用（v2.1：不再链接到对话 MD，仅记录 source_id 文本）──
        source_ref = ""
        if source_id:
            source_ref = f"`{source_id}`"

        # ── 构建 Frontmatter ──
        final_tags = (tags or []) + ["review"]
        extra = {}
        if source_ref:
            extra["source"] = source_ref

        frontmatter = self._build_frontmatter(
            card_type=card_type,
            domain=domain,
            title=title,
            tags=final_tags,
            created=created_at or datetime.now().isoformat(),
            knowledge_id=kp_id,
            extra=extra,
        )

        # ── 正文 ──
        parts = [f"# {title}", "", content]
        if related_links:
            parts.append("\n## 关联")
            for link in related_links:
                parts.append(f"- {link}")
        if card_type == "skill":
            parts.append("\n## 复习记录")
            parts.append("```dataviewjs")
            parts.append("// 使用 Spaced Repetition 插件管理复习")
            parts.append("```")

        body = "\n".join(parts)
        self._write_markdown(file_path, frontmatter, body)

        action = "更新" if file_path.exists() else "导出"
        logger.info(f"📝 {card_type}知识{action}: {file_path}")
        return str(file_path)

    def _build_related_links(self, related_ids_raw: str) -> list[str]:
        """构建 [[id_title|title]] 格式的关联链接列表"""
        if not related_ids_raw:
            return []
        related_ids = self._safe_json(related_ids_raw, [])
        if not related_ids:
            return []

        links = []
        for rid in related_ids:
            row = self._get_knowledge_by_id(rid)
            if row:
                links.append(self._make_wikilink(row))
        return links

    def _make_wikilink(self, row: dict) -> str:
        """生成 [[title|title]] 格式的 Wikilink（v8.0: 移除数字前缀）"""
        title = row.get("title", "未命名")
        filename = self._sanitize_filename(title)
        return f"[[{filename}|{title}]]"

    def _write_project_dashboard(self, project: str):
        """
        生成/更新项目仪表盘 MD（v8.1: 自包含版，不依赖 SQLite）

        设计原则：
        - MD 完全自包含，不引用 SQLite（SQLite 数据会被定时清理）
        - 日报通过 Calendar/*.md 持久化，仪表盘通过扫描 frontmatter 索引日报
        - 知识卡片通过 Cards/ 和 Efforts/ 目录持久化
        """
        safe_project = self._sanitize_path(project)
        file_path = self._vault_root / "Efforts" / safe_project / "项目仪表盘.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 扫描 Calendar 目录，找到包含该项目的日报
        daily_reports = []
        if self._calendar_dir.exists():
            import re as _re

            for md_file in sorted(self._calendar_dir.glob("*.md"), reverse=True):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    match = _re.search(r"projects:\s*\[(.*?)\]", content[:500])
                    if match and safe_project in match.group(1):
                        daily_reports.append(md_file.stem)
                except Exception:
                    logger.warning(
                        "VaultExporter._write_project_dashboard: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    continue

        # 统计知识卡片
        business_dir = self._vault_root / "Efforts" / safe_project / "业务知识"
        business_count = len(list(business_dir.glob("*.md"))) if business_dir.exists() else 0

        skill_count = 0
        skill_links = []
        if (self._vault_root / "Cards").exists():
            for card_file in (self._vault_root / "Cards").rglob("*.md"):
                try:
                    content = card_file.read_text(encoding="utf-8")
                    if safe_project in content[:1000]:
                        skill_count += 1
                        rel_path = card_file.relative_to(self._vault_root)
                        skill_links.append(str(rel_path.with_suffix("")).replace("\\", "/"))
                except Exception:
                    logger.warning(
                        "VaultExporter._write_project_dashboard: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"# {project} 项目仪表盘",
            "",
            f"> 最后更新: {now}",
            "> 本页面为自包含 MD，数据来源于 Calendar/ 日报和 Cards/ 知识卡片，不依赖 SQLite。",
            "",
            "---",
            "",
            "## 📊 概览",
            "",
            f"- 📅 日报: {len(daily_reports)} 篇",
            f"- 📚 业务知识卡片: {business_count} 张",
            f"- 🛠️ 技能卡片: {skill_count} 张",
            "",
            "---",
            "",
            "## 📅 日报索引",
            "",
        ]

        if daily_reports:
            lines.append("> 以下日报包含该项目的变更记录：")
            lines.append("")
            for date_str in daily_reports[:30]:
                lines.append(f"- [[Calendar/{date_str}]]")
            if len(daily_reports) > 30:
                lines.append(f"- ... 还有 {len(daily_reports) - 30} 篇日报")
        else:
            lines.append("（暂无日报记录）")

        lines.extend(
            [
                "",
                "---",
                "",
                "## 📚 知识卡片",
                "",
                "### 业务知识",
                f"→ [[Efforts/{safe_project}/业务知识/|业务知识目录]] ({business_count} 张)",
                "",
                "### 技能卡片",
            ]
        )

        if skill_links:
            for link in sorted(skill_links)[:20]:
                lines.append(f"- [[{link}]]")
            if len(skill_links) > 20:
                lines.append(f"- ... 还有 {len(skill_links) - 20} 张")
        else:
            lines.append("（暂无关联技能卡片）")

        lines.extend(
            [
                "",
                "---",
                "",
                "## 🏗️ 项目画像",
                f"→ [[Efforts/{safe_project}/项目画像]]",
                "",
                "---",
                "",
                "## 🔗 关联",
                "- 日报目录: [[Calendar/]]",
                "- 知识卡片目录: [[Cards/]]",
                "",
            ]
        )

        frontmatter = (
            "---\n"
            "type: dashboard\n"
            f'project: "{safe_project}"\n'
            f'updated: "{datetime.now().isoformat()}"\n'
            f"daily_reports: {len(daily_reports)}\n"
            f"business_cards: {business_count}\n"
            f"skill_cards: {skill_count}\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(
            f"📊 项目仪表盘已更新: {project} ({len(daily_reports)} 日报, {business_count + skill_count} 知识卡片)"
        )

    def _get_knowledge_by_id(self, knowledge_id: str) -> dict | None:
        """根据 knowledge_id 查询知识行"""
        try:
            rows = self.db.query_local(
                "SELECT * FROM knowledge_points WHERE knowledge_id = ? LIMIT 1", (knowledge_id,)
            )
            return dict(rows[0]) if rows else None
        except Exception:
            logger.warning(
                "VaultExporter._get_knowledge_by_id: 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            return None

    def _build_frontmatter(
        self,
        card_type: str,
        domain: str,
        title: str,
        tags: list,
        created: str,
        knowledge_id: str = "",
        source: str = "",
        extra: dict = None,
    ) -> str:
        """构建 YAML Frontmatter"""
        lines = [
            "---",
            f"type: {card_type}",
            f"domain: {domain}",
        ]
        if tags:
            lines.append("tags: [" + ", ".join(tags) + "]")
        lines.append(f"created: {created}")
        if source:
            lines.append(f'source: "{self._escape_yaml(source)}"')
        if knowledge_id:
            lines.append(f'knowledge_id: "{knowledge_id}"')
        if extra:
            for k, v in extra.items():
                if isinstance(v, str):
                    lines.append(f'{k}: "{self._escape_yaml(v)}"')
                elif isinstance(v, (int, float)):
                    lines.append(f"{k}: {v}")
                elif isinstance(v, list):
                    lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        lines.append("---")
        return "\n".join(lines)

    @staticmethod
    def _write_markdown(file_path: Path, frontmatter: str, body: str):
        """写入 Markdown 文件"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + "\n\n" + body)

    @staticmethod
    def _sanitize_path(name: str) -> str:
        """净化目录名"""
        return re.sub(r'[<>:"/\\|?*]', "-", name).strip()

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """净化文件名（v8.0: 移除数字前缀，直接使用描述性名称）"""
        name = re.sub(r'[<>:"/\\|?*]', "-", name)
        name = re.sub(r"\s+", "_", name)
        name = re.sub(r"^\d+[_\-\s]*", "", name)
        return name[:100].strip("_-")

    @staticmethod
    def _escape_yaml(s: str) -> str:
        """转义 YAML 特殊字符"""
        return s.replace('"', '\\"').replace("\n", "\\n")

    @staticmethod
    def _safe_json(val, default):
        """安全解析 JSON"""
        if not val:
            return default
        if isinstance(val, (list, dict)):
            return val
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default

    @staticmethod
    def _derive_project_name() -> str:
        return os.path.basename(os.getcwd())


def get_vault_exporter(vault_root: str = None) -> VaultExporter:
    """获取 Vault 导出器单例"""
    return VaultExporter(vault_root=vault_root)


# ══════════════════════════════════════════════════════════
# Task Handler 注册（v8.1 — 支持异步并行导出）
# ══════════════════════════════════════════════════════════


def handle_vault_export_batch(payload: dict) -> dict:
    """异步批量导出知识卡片"""
    exporter = get_vault_exporter()
    return exporter.export_batch(
        conversation_id=payload.get("conversation_id", ""),
        project=payload.get("project", ""),
        summary=payload.get("summary", ""),
        key_decisions=payload.get("key_decisions", []),
        steps_summary=payload.get("steps_summary", []),
        knowledge_ids=payload.get("knowledge_ids", []),
    )


def handle_vault_export_all(payload: dict) -> dict:
    """异步全量重导所有知识点"""
    exporter = get_vault_exporter()
    return exporter.export_all_knowledge()


def handle_vault_export_profile(payload: dict) -> dict:
    """异步导出用户画像到 Vault"""
    exporter = get_vault_exporter()
    path = exporter.export_profile_to_vault(
        profile_data=payload.get("profile_data", {}),
        date_str=payload.get("date_str", ""),
    )
    return {"path": path, "success": path is not None}


def handle_vault_export_project(payload: dict) -> dict:
    """异步导出项目画像到 Vault"""
    exporter = get_vault_exporter()
    path = exporter.export_project_to_vault(
        system_id=payload.get("system_id", ""),
        project_data=payload.get("project_data", {}),
    )
    return {"path": path, "success": path is not None}


def handle_vault_export_weekly(payload: dict) -> dict:
    """异步导出周报"""
    exporter = get_vault_exporter()
    path = exporter.export_weekly_report(
        period_start=payload.get("period_start", ""),
        period_end=payload.get("period_end", ""),
        report_data=payload.get("report_data", {}),
    )
    return {"path": path, "success": path is not None}


def handle_vault_export_monthly(payload: dict) -> dict:
    """异步导出月报"""
    exporter = get_vault_exporter()
    path = exporter.export_monthly_report(
        period_start=payload.get("period_start", ""),
        period_end=payload.get("period_end", ""),
        report_data=payload.get("report_data", {}),
    )
    return {"path": path, "success": path is not None}


def handle_vault_export_annual(payload: dict) -> dict:
    """异步导出年报"""
    exporter = get_vault_exporter()
    path = exporter.export_annual_report(
        year=payload.get("year", ""),
        report_data=payload.get("report_data", {}),
    )
    return {"path": path, "success": path is not None}


def handle_vault_export_daily(payload: dict) -> dict:
    """异步导出日报"""
    exporter = get_vault_exporter()
    path = exporter.export_daily_report(
        date_str=payload.get("date_str", ""),
        report_data=payload.get("report_data", {}),
    )
    return {"path": path, "success": path is not None}


def register_task_handlers():
    """注册 Vault 导出任务处理器到 task_queue"""
    from backend.core.task_queue_kernel.queue_client import get_task_queue

    queue = get_task_queue()
    queue.register_handler("vault_export_batch", handle_vault_export_batch)
    queue.register_handler("vault_export_all", handle_vault_export_all)
    queue.register_handler("vault_export_profile", handle_vault_export_profile)
    queue.register_handler("vault_export_project", handle_vault_export_project)
    queue.register_handler("vault_export_weekly", handle_vault_export_weekly)
    queue.register_handler("vault_export_monthly", handle_vault_export_monthly)
    queue.register_handler("vault_export_annual", handle_vault_export_annual)
    queue.register_handler("vault_export_daily", handle_vault_export_daily)
    logger.info("📝 Vault 导出任务处理器已注册 (8 个 handler)")
