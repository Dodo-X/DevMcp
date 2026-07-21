"""
Obsidian Vault 导出器 v2.1
==========================

将知识卡片导出为 Obsidian Vault 兼容的 Markdown 文件。

v2.1 变更：
- ★ 移除对话 MD 导出 — 对话列表/统计/日报全部走 SQLite DB 插件直连查询
- ★ 只导出知识卡片：Cards/{domain}/ + Efforts/{project}/业务知识/
- ★ 项目仪表盘使用 SQLite DB 插件 SQL 查询，不再依赖 Dataview MD 文件扫描

目录结构：
  data/Knowledge Library/
  ├── Cards/{domain}/              # 技能知识卡片
  ├── Efforts/{project}/业务知识/   # 业务知识卡片
  ├── Efforts/{project}/项目仪表盘.md  # SQL 查询驱动的仪表盘
  └── Atlas/                       # 手动使用
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class VaultExporter:
    """Obsidian Vault Markdown 导出器（v2.1 — 仅导出知识卡片，对话/统计走 SQL）"""

    def __init__(self, vault_root: str = None):
        """
        Args:
            vault_root: Vault 根目录，默认 data/Knowledge Library/
        """
        if vault_root:
            self._vault_root = Path(vault_root)
        else:
            self._vault_root = Path(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "Knowledge Library"
            ))
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

    @property
    def db(self):
        if self._db is None:
            from devpartner_agent.core.database import get_db
            self._db = get_db()
        return self._db

    # ══════════════════════════════════════════════════════════
    # 公开方法
    # ══════════════════════════════════════════════════════════

    def export_skill_card(self, kp_id: str, kp_row: dict = None) -> Optional[str]:
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

    def export_business_card(self, kp_id: str, kp_row: dict = None) -> Optional[str]:
        """
        导出一张业务知识卡片到 Efforts/{project}/业务知识/{id}_{title}.md
        """
        if kp_row is None:
            kp_row = self._get_knowledge_by_id(kp_id)
        if not kp_row:
            return None

        return self._export_card(kp_row, card_type="business")

    def export_batch(self, conversation_id: str = "", project: str = "",
                     summary: str = "", key_decisions: list = None,
                     steps_summary: list = None,
                     knowledge_ids: list = None) -> Dict[str, Any]:
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
        for kid in (knowledge_ids or []):
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
                result["errors"].append(f"知识导出失败 [{kid}]: {e}")

        # 生成/更新项目仪表盘（SQL 驱动）
        try:
            self._write_project_dashboard(project)
            logger.info(f"📊 项目仪表盘已更新: {project}")
        except Exception as e:
            result["errors"].append(f"仪表盘生成失败: {e}")

        logger.info(
            f"📤 Vault 批量导出完成: "
            f"业务={result['business_exported']}, "
            f"技能={result['skills_exported']}, "
            f"错误={len(result['errors'])}"
        )
        return result

    def export_all_knowledge(self) -> Dict[str, Any]:
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
            for row in (rows or []):
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
                    result["errors"].append(f"导出失败 [{row['knowledge_id']}]: {e}")
        except Exception as e:
            result["errors"].append(f"全量导出失败: {e}")
        return result

    def export_profile_to_vault(self, profile_data: dict, date_str: str) -> Optional[str]:
        """
        导出用户画像到 Atlas/用户画像.md（v8.0）

        Args:
            profile_data: user_profile 表数据
            date_str: 日期字符串

        Returns:
            文件路径
        """
        file_path = self._atlas_dir / "用户画像.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        dimensions = profile_data.get("dimensions", [])
        lines = [
            "# 用户画像",
            "",
            f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 画像维度",
            "",
        ]

        for dim in dimensions:
            d = dim.get("dimension", "")
            v = dim.get("value", "")
            c = dim.get("confidence", 0)
            t = dim.get("trend", "stable")
            e = dim.get("evidence", "")
            trend_icon = {"rising": "📈", "declining": "📉", "stable": "➡️"}.get(t, "➡️")
            lines.append(f"### {d}")
            lines.append(f"- **值**: {v}")
            lines.append(f"- **置信度**: {c:.0%}")
            lines.append(f"- **趋势**: {trend_icon} {t}")
            if e:
                lines.append(f"- **证据**: {e}")
            lines.append("")

        frontmatter = (
            "---\n"
            "type: user_profile\n"
            f"date: \"{date_str}\"\n"
            f"updated: \"{datetime.now().isoformat()}\"\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"👤 用户画像已导出: {file_path}")
        return str(file_path)

    def export_project_to_vault(self, system_id: str, project_data: dict) -> Optional[str]:
        """
        导出项目画像到 Efforts/{system_id}/项目画像.md（v8.0）

        Args:
            system_id: 系统标识
            project_data: connected_systems 表数据

        Returns:
            文件路径
        """
        safe_id = self._sanitize_path(system_id)
        dir_path = self._vault_root / "Efforts" / safe_id
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / "项目画像.md"

        tech_stack = project_data.get("tech_stack", [])
        architecture = project_data.get("architecture", {})
        business_domains = project_data.get("business_domains", [])
        maturity = project_data.get("maturity", "unknown")

        maturity_label = {
            "unknown": "未知", "early": "初期", "growing": "成长期", "mature": "成熟期",
        }.get(maturity, maturity)

        lines = [
            f"# {system_id} 项目画像",
            "",
            f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"## 成熟度: {maturity_label}",
            "",
        ]

        if tech_stack:
            lines.append("## 技术栈")
            lines.append("")
            for tech in tech_stack:
                lines.append(f"- {tech}")
            lines.append("")

        if architecture:
            lines.append("## 架构")
            lines.append("")
            pattern = architecture.get("pattern", "unknown")
            lines.append(f"- **模式**: {pattern}")
            components = architecture.get("components", [])
            if components:
                lines.append("- **核心组件**:")
                for comp in components:
                    lines.append(f"  - {comp}")
            data_flow = architecture.get("data_flow", "")
            if data_flow:
                lines.append(f"- **数据流**: {data_flow}")
            lines.append("")

        if business_domains:
            lines.append("## 业务领域")
            lines.append("")
            for domain in business_domains:
                lines.append(f"- {domain}")
            lines.append("")

        frontmatter = (
            "---\n"
            "type: project_profile\n"
            f"system_id: \"{system_id}\"\n"
            f"maturity: \"{maturity}\"\n"
            f"updated: \"{datetime.now().isoformat()}\"\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"🏗️ 项目画像已导出: {file_path}")
        return str(file_path)

    def export_daily_report(self, date_str: str, report_data: dict) -> Optional[str]:
        """
        导出日报到 Calendar/{date}.md（v8.0 自包含版）

        日报包含完整的用户画像快照、项目画像快照和知识点，
        确保即使 SQLite 数据被清理，MD 文件仍能独立提供完整信息。

        Args:
            date_str: 日期 YYYY-MM-DD
            report_data: LLM 分析后的日报数据

        Returns:
            文件路径
        """
        file_path = self._calendar_dir / f"{date_str}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# 📅 {date_str} 日报",
            "",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 引擎: {report_data.get('inference_engine', 'ollama')}",
            "",
        ]

        summary = report_data.get("summary", "")
        if summary:
            lines.extend([f"## 📋 总结", "", summary, ""])

        exp = report_data.get("experience", {})
        if exp:
            lines.append("## 🔍 深度体验")
            lines.append("")
            if exp.get("deep_dive"):
                lines.extend([f"**深入探索**: {exp['deep_dive']}", ""])
            if exp.get("lesson"):
                lines.extend([f"**经验教训**: {exp['lesson']}", ""])

        skills = report_data.get("skills", {})
        if skills:
            lines.append("## 🛠️ 技能")
            lines.append("")
            for key, label in [("new_skills", "新技能"), ("patterns", "模式"), ("tools", "工具")]:
                items = skills.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items)}")
            lines.append("")

        knowledge = report_data.get("knowledge", {})
        if knowledge:
            lines.append("## 📚 知识")
            lines.append("")
            for key, label in [("must_remember", "必须记住"), ("insights", "洞察"), ("decisions", "技术决策"), ("solutions", "问题解决")]:
                items = knowledge.get(key, [])
                if items:
                    lines.append(f"**{label}**:")
                    for item in items:
                        lines.append(f"- {item}")
            lines.append("")

        danger = report_data.get("danger_signals", {})
        if danger:
            lines.append("## ⚠️ 危险信号")
            lines.append("")
            for key, label in [("repeated_mistakes", "重复错误"), ("tech_debt", "技术债务"), ("hot_files", "高风险文件")]:
                items = danger.get(key, [])
                if items:
                    lines.append(f"**{label}**:")
                    for item in items:
                        lines.append(f"- {item}")
            lines.append("")

        profile_update = report_data.get("user_profile_update", {})
        if profile_update:
            lines.append("## 👤 用户画像变化")
            lines.append("")
            for key, label in [("skill_changes", "技能变化"), ("behavior_signals", "行为信号")]:
                items = profile_update.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items)}")
            if profile_update.get("growth_direction"):
                lines.append(f"**成长方向**: {profile_update['growth_direction']}")
            lines.append("")

        project_update = report_data.get("project_profile_update", {})
        if project_update:
            lines.append("## 🏗️ 项目画像变化")
            lines.append("")
            for key, label in [("tech_changes", "技术栈"), ("architecture_changes", "架构"), ("business_changes", "业务")]:
                items = project_update.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items)}")
            lines.append("")

        metrics = report_data.get("metrics", {})
        if metrics:
            lines.append("## 📊 指标")
            lines.append("")
            for key, label in [("productivity_score", "生产力"), ("learning_score", "学习"), ("collaboration_score", "协作"), ("focus_score", "专注")]:
                val = metrics.get(key)
                if val is not None:
                    lines.append(f"- **{label}**: {val}/10")
            lines.append("")

        # v8.1: 项目维度归纳（简洁版 + 指向 Efforts 的 wiki-link + 文档间关联）
        project_analysis = report_data.get("project_analysis", {})
        projects = project_analysis.get("projects", [])
        related_projects = []
        knowledge_links = []

        if projects:
            lines.append("## 🏗️ 项目维度")
            lines.append("")
            lines.append("> 以下为今日各项目的简要归纳，完整分析见项目仪表盘。")
            lines.append("")

            for p in projects:
                pname = p.get("project_name", "未命名项目")
                safe_pname = re.sub(r'[\\/:*?"<>|]', '_', pname)
                related_projects.append(safe_pname)
                lines.append(f"### 📁 {pname}")
                lines.append("")

                work_summary = p.get("work_summary", "")
                if work_summary:
                    lines.append(f"**今日工作**: {work_summary}")
                    lines.append("")

                # Bug 归纳（简洁表格）
                bugs_found = p.get("bugs_found", [])
                bugs_fixed = p.get("bugs_fixed", [])
                if bugs_found or bugs_fixed:
                    lines.append("**Bug 情况**:")
                    lines.append("")
                    if bugs_found:
                        lines.append("| 分类 | 描述 | 状态 |")
                        lines.append("|------|------|------|")
                        for bug in bugs_found:
                            lines.append(f"| {bug.get('category', '')} | {bug.get('description', '')} | 发现 |")
                    if bugs_fixed:
                        if not bugs_found:
                            lines.append("| 分类 | 描述 | 状态 |")
                            lines.append("|------|------|------|")
                        for bf in bugs_fixed:
                            lines.append(f"| — | {bf.get('description', '')} | ✅ 已修复 |")
                    lines.append("")

                # 关键文件
                key_files = p.get("key_files", [])
                if key_files:
                    files_str = "、".join(f"`{f}`" for f in key_files[:6])
                    suffix = f" 等{len(key_files)}个文件" if len(key_files) > 6 else ""
                    lines.append(f"**文件变更**: {files_str}{suffix}")
                    lines.append("")

                # 知识库落地（带 wiki-link）
                knowledge_for_base = p.get("knowledge_for_base", [])
                if knowledge_for_base:
                    lines.append("**知识落地**:")
                    lines.append("")
                    for kb_item in knowledge_for_base:
                        title = kb_item.get("title", "")
                        tags = kb_item.get("tags", [])
                        tag_str = " ".join(f"`#{t}`" for t in tags)
                        # 生成知识卡片 wiki-link
                        domain = tags[0] if tags else "通用"
                        kb_link = f"[[Cards/{domain}/{title}]]"
                        knowledge_links.append(kb_link)
                        lines.append(f"- {kb_link} {tag_str}")
                        content = kb_item.get("content", "")
                        if content:
                            lines.append(f"  > {content[:120]}{'...' if len(content) > 120 else ''}")
                    lines.append("")

                # 决策
                decisions = p.get("decisions", [])
                if decisions:
                    lines.append("**技术决策**:")
                    lines.append("")
                    for d in decisions:
                        lines.append(f"- {d}")
                    lines.append("")

                # 指向 Efforts 项目仪表盘
                lines.append(f"→ 详见 [[Efforts/{safe_pname}/项目仪表盘]]")
                lines.append("")

        # v8.1: 关联文档（文档间交叉引用，Obsidian 双向链接）
        lines.append("## 🔗 关联文档")
        lines.append("")

        # 项目仪表盘
        if related_projects:
            proj_links = "、".join(f"[[Efforts/{p}/项目仪表盘]]" for p in related_projects)
            lines.append(f"- **项目分析**: {proj_links}")

        # 知识卡片
        if knowledge_links:
            kb_links = "、".join(knowledge_links[:8])
            if len(knowledge_links) > 8:
                kb_links += f" 等{len(knowledge_links)}张卡片"
            lines.append(f"- **知识卡片**: {kb_links}")

        # 昨天/明天的日报
        try:
            today = datetime.strptime(date_str, "%Y-%m-%d")
            yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
            lines.append(f"- **昨日**: [[Calendar/{yesterday}]]")
        except ValueError:
            pass

        # 本周周报
        try:
            today = datetime.strptime(date_str, "%Y-%m-%d")
            week_num = today.strftime("%Y-W%W")
            lines.append(f"- **本周**: [[Reports/Weekly/{week_num}]]")
        except ValueError:
            pass

        lines.append("")

        # 构建 frontmatter（v8.1: MD 完全自包含，不引用 SQLite）
        project_list = ", ".join(f'"{p}"' for p in related_projects) if related_projects else ""
        kb_list = ", ".join(knowledge_links[:5]) if knowledge_links else ""

        frontmatter = (
            "---\n"
            "type: daily_report\n"
            f"date: \"{date_str}\"\n"
            f"generated: \"{datetime.now().isoformat()}\"\n"
            f"productivity: {metrics.get('productivity_score', 0)}\n"
            f"learning: {metrics.get('learning_score', 0)}\n"
            + (f"projects: [{project_list}]\n" if project_list else "")
            + (f"kb_links: [{kb_list}]\n" if kb_list else "")
            + "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"📅 日报已导出: {file_path}")

        # v8.1: 日报告出后，自动更新关联项目的仪表盘
        for pname in related_projects:
            try:
                self._write_project_dashboard(pname)
            except Exception as e:
                logger.warning(f"⚠️ 项目仪表盘更新失败 [{pname}]: {e}")

        return str(file_path)

    def export_weekly_report(self, period_start: str, period_end: str,
                              report_data: dict) -> Optional[str]:
        """导出周报到 Reports/Weekly/{period}.md"""
        week_num = datetime.strptime(period_start, "%Y-%m-%d").strftime("%Y-W%W")
        file_path = self._reports_dir / "Weekly" / f"{week_num}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# 📆 {week_num} 周报",
            "",
            f"> 周期: {period_start} ~ {period_end}",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        summary = report_data.get("summary", "")
        if summary:
            lines.extend(["## 📋 总结", "", summary, ""])

        achievements = report_data.get("key_achievements", [])
        if achievements:
            lines.append("## 🏆 关键成果")
            lines.append("")
            for a in achievements:
                lines.append(f"- **{a.get('achievement', '')}** — {a.get('impact', '')}")
            lines.append("")

        skill_progress = report_data.get("skill_progress", {})
        if skill_progress:
            lines.append("## 🛠️ 技能进展")
            lines.append("")
            for key, label in [("new_skills_acquired", "新掌握"), ("skills_improved", "提升"), ("skills_to_learn", "待学习")]:
                items = skill_progress.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items)}")
            lines.append("")

        risk = report_data.get("risk_assessment", {})
        if risk:
            lines.append("## ⚠️ 风险评估")
            lines.append("")
            for key, label in [("technical_risks", "技术风险"), ("knowledge_gaps", "知识盲区"), ("process_issues", "流程问题")]:
                items = risk.get(key, [])
                if items:
                    lines.append(f"**{label}**:")
                    for item in items:
                        lines.append(f"- {item}")
            lines.append("")

        next_plan = report_data.get("next_week_plan", {})
        if next_plan:
            lines.append("## 📋 下周计划")
            lines.append("")
            for key, label in [("priorities", "优先事项"), ("learning_goals", "学习目标"), ("experiments", "实验")]:
                items = next_plan.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items)}")
            lines.append("")

        metrics = report_data.get("metrics", {})
        if metrics:
            lines.append("## 📊 指标")
            lines.append("")
            for key, label in [("productivity_trend", "生产力趋势"), ("learning_velocity", "学习速度"), ("code_quality_trend", "代码质量"), ("overall_score", "综合评分")]:
                val = metrics.get(key)
                if val is not None:
                    lines.append(f"- **{label}**: {val}")
            lines.append("")

        # v8.1: 关联文档（周报 ↔ 日报 双向链接）
        lines.append("## 🔗 关联文档")
        lines.append("")
        try:
            start = datetime.strptime(period_start, "%Y-%m-%d")
            end = datetime.strptime(period_end, "%Y-%m-%d")
            day_links = []
            current = start
            while current <= end:
                day_links.append(f"[[Calendar/{current.strftime('%Y-%m-%d')}]]")
                current += timedelta(days=1)
            lines.append(f"- **日报**: {', '.join(day_links)}")
            month_str = start.strftime("%Y-%m")
            lines.append(f"- **月报**: [[Reports/Monthly/{month_str}]]")
        except ValueError:
            pass
        lines.append("")

        frontmatter = (
            "---\n"
            "type: weekly_report\n"
            f"period_start: \"{period_start}\"\n"
            f"period_end: \"{period_end}\"\n"
            f"week: \"{week_num}\"\n"
            f"sources: [\"Calendar/{period_start}.md\", \"Calendar/{period_end}.md\"]\n"
            f"generated: \"{datetime.now().isoformat()}\"\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"📆 周报已导出: {file_path}")
        return str(file_path)

    def export_monthly_report(self, period_start: str, period_end: str,
                               report_data: dict) -> Optional[str]:
        """导出月报到 Reports/Monthly/{YYYY-MM}.md"""
        month_str = datetime.strptime(period_start, "%Y-%m-%d").strftime("%Y-%m")
        file_path = self._reports_dir / "Monthly" / f"{month_str}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# 🗓️ {month_str} 月报",
            "",
            f"> 周期: {period_start} ~ {period_end}",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        summary = report_data.get("summary", "")
        if summary:
            lines.extend(["## 📋 总结", "", summary, ""])

        achievements = report_data.get("major_achievements", [])
        if achievements:
            lines.append("## 🏆 重大成果")
            lines.append("")
            for a in achievements:
                lines.append(f"- **{a.get('achievement', '')}** — 影响: {a.get('impact', '')}")
            lines.append("")

        skill_evo = report_data.get("skill_evolution", {})
        if skill_evo:
            lines.append("## 🛠️ 技能演进")
            lines.append("")
            for key, label in [("skills_at_start", "月初"), ("skills_at_end", "月末"), ("growth_highlights", "成长亮点")]:
                items = skill_evo.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items) if isinstance(items, list) else items}")
            if skill_evo.get("learning_curve"):
                lines.append(f"**学习曲线**: {skill_evo['learning_curve']}")
            lines.append("")

        risk = report_data.get("risk_and_debt", {})
        if risk:
            lines.append("## ⚠️ 风险与债务")
            lines.append("")
            for key, label in [("critical_risks", "关键风险"), ("tech_debt_accumulated", "技术债务"), ("knowledge_debt", "知识欠债")]:
                items = risk.get(key, [])
                if items:
                    lines.append(f"**{label}**:")
                    for item in items:
                        lines.append(f"- {item}")
            lines.append("")

        next_plan = report_data.get("next_month_plan", {})
        if next_plan:
            lines.append("## 📋 下月计划")
            lines.append("")
            for key, label in [("strategic_goals", "战略目标"), ("tactical_actions", "行动项"), ("learning_roadmap", "学习路线")]:
                items = next_plan.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items) if isinstance(items, list) else items}")
            lines.append("")

        metrics = report_data.get("metrics", {})
        if metrics:
            lines.append("## 📊 指标")
            lines.append("")
            for key, label in [("overall_productivity", "综合生产力"), ("skill_growth_rate", "技能增长率"), ("project_health", "项目健康度"), ("work_life_balance", "工作生活平衡")]:
                val = metrics.get(key)
                if val is not None:
                    lines.append(f"- **{label}**: {val}")
            lines.append("")

        frontmatter = (
            "---\n"
            "type: monthly_report\n"
            f"period_start: \"{period_start}\"\n"
            f"period_end: \"{period_end}\"\n"
            f"month: \"{month_str}\"\n"
            f"sources: [\"Reports/Weekly/{period_start[:4]}-W*.md\"]\n"
            f"generated: \"{datetime.now().isoformat()}\"\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"🗓️ 月报已导出: {file_path}")
        return str(file_path)

    def export_annual_report(self, year: str, report_data: dict) -> Optional[str]:
        """导出年报到 Reports/Annual/{YYYY}.md"""
        file_path = self._reports_dir / "Annual" / f"{year}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# 📖 {year} 年报",
            "",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]

        summary = report_data.get("summary", "")
        if summary:
            lines.extend(["## 📋 年度总结", "", summary, ""])

        review = report_data.get("year_in_review", {})
        if review:
            lines.append("## 🔭 年度回顾")
            lines.append("")
            for key, label in [("defining_moments", "定义性时刻"), ("biggest_achievements", "最大成就"), ("hardest_challenges", "最困难挑战"), ("unexpected_discoveries", "意外发现")]:
                items = review.get(key, [])
                if items:
                    lines.append(f"**{label}**:")
                    for item in items:
                        lines.append(f"- {item}")
            lines.append("")

        skill_journey = report_data.get("skill_journey", {})
        if skill_journey:
            lines.append("## 🛠️ 技能旅程")
            lines.append("")
            for key, label in [("skills_at_year_start", "年初"), ("skills_at_year_end", "年末"), ("breakthrough_skills", "突破性提升"), ("abandoned_skills", "搁置方向")]:
                items = skill_journey.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items) if isinstance(items, list) else items}")
            if skill_journey.get("skill_map"):
                lines.append(f"**技能地图**: {skill_journey['skill_map']}")
            lines.append("")

        growth = report_data.get("growth_analysis", {})
        if growth:
            lines.append("## 📈 成长分析")
            lines.append("")
            for key, label in [("learning_curve", "学习曲线"), ("productivity_evolution", "生产力演变"), ("decision_making_maturity", "决策成熟度"), ("communication_style_evolution", "沟通风格演变")]:
                val = growth.get(key)
                if val:
                    lines.append(f"- **{label}**: {val}")
            lines.append("")

        vision = report_data.get("next_year_vision", {})
        if vision:
            lines.append("## 🎯 下年愿景")
            lines.append("")
            if vision.get("strategic_direction"):
                lines.append(f"**战略方向**: {vision['strategic_direction']}")
            for key, label in [("skill_goals", "技能目标"), ("project_ambitions", "项目愿景"), ("learning_commitments", "学习承诺")]:
                items = vision.get(key, [])
                if items:
                    lines.append(f"**{label}**: {', '.join(items)}")
            lines.append("")

        metrics = report_data.get("metrics", {})
        if metrics:
            lines.append("## 📊 指标")
            lines.append("")
            for key, label in [("overall_growth_score", "综合成长"), ("technical_depth", "技术深度"), ("breadth_of_knowledge", "知识广度"), ("impact_level", "影响力"), ("sustainability", "可持续性")]:
                val = metrics.get(key)
                if val is not None:
                    lines.append(f"- **{label}**: {val}")
            lines.append("")

        frontmatter = (
            "---\n"
            "type: annual_report\n"
            f"year: \"{year}\"\n"
            f"sources: [\"Reports/Monthly/{year}-*.md\"]\n"
            f"generated: \"{datetime.now().isoformat()}\"\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"📖 年报已导出: {file_path}")
        return str(file_path)

    def get_latest_report_date(self, report_type: str) -> Optional[str]:
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

    def _export_card(self, kp_row: dict, card_type: str) -> Optional[str]:
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
        aliases = self._safe_json(kp_row.get("aliases", "[]"), [])
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

    def _build_related_links(self, related_ids_raw: str) -> List[str]:
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
                    match = _re.search(r'projects:\s*\[(.*?)\]', content[:500])
                    if match and safe_project in match.group(1):
                        daily_reports.append(md_file.stem)
                except Exception:
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
                        skill_links.append(str(rel_path.with_suffix("")))
                except Exception:
                    continue

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"# {project} 项目仪表盘",
            "",
            f"> 最后更新: {now}",
            f"> 本页面为自包含 MD，数据来源于 Calendar/ 日报和 Cards/ 知识卡片，不依赖 SQLite。",
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

        lines.extend([
            "",
            "---",
            "",
            "## 📚 知识卡片",
            "",
            "### 业务知识",
            f"→ [[Efforts/{safe_project}/业务知识/|业务知识目录]] ({business_count} 张)",
            "",
            "### 技能卡片",
        ])

        if skill_links:
            for link in sorted(skill_links)[:20]:
                lines.append(f"- [[{link}]]")
            if len(skill_links) > 20:
                lines.append(f"- ... 还有 {len(skill_links) - 20} 张")
        else:
            lines.append("（暂无关联技能卡片）")

        lines.extend([
            "",
            "---",
            "",
            "## 🏗️ 项目画像",
            f"→ [[Efforts/{safe_project}/项目画像]]",
            "",
            "---",
            "",
            "## 🔗 关联",
            f"- 日报目录: [[Calendar/]]",
            f"- 知识卡片目录: [[Cards/]]",
            "",
        ])

        frontmatter = (
            "---\n"
            "type: dashboard\n"
            f"project: \"{safe_project}\"\n"
            f"updated: \"{datetime.now().isoformat()}\"\n"
            f"daily_reports: {len(daily_reports)}\n"
            f"business_cards: {business_count}\n"
            f"skill_cards: {skill_count}\n"
            "---"
        )
        self._write_markdown(file_path, frontmatter, "\n".join(lines))
        logger.info(f"📊 项目仪表盘已更新: {project} ({len(daily_reports)} 日报, {business_count + skill_count} 知识卡片)")

    def _get_knowledge_by_id(self, knowledge_id: str) -> Optional[dict]:
        """根据 knowledge_id 查询知识行"""
        try:
            rows = self.db.query_local(
                "SELECT * FROM knowledge_points WHERE knowledge_id = ? LIMIT 1",
                (knowledge_id,)
            )
            return dict(rows[0]) if rows else None
        except Exception:
            return None

    def _build_frontmatter(self, card_type: str, domain: str, title: str,
                           tags: list, created: str, knowledge_id: str = "",
                           source: str = "", extra: dict = None) -> str:
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
            lines.append(f"source: \"{self._escape_yaml(source)}\"")
        if knowledge_id:
            lines.append(f"knowledge_id: \"{knowledge_id}\"")
        if extra:
            for k, v in extra.items():
                if isinstance(v, str):
                    lines.append(f"{k}: \"{self._escape_yaml(v)}\"")
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
        return re.sub(r'[<>:"/\\|?*]', '-', name).strip()

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """净化文件名（v8.0: 移除数字前缀，直接使用描述性名称）"""
        name = re.sub(r'[<>:"/\\|?*]', '-', name)
        name = re.sub(r'\s+', '_', name)
        name = re.sub(r'^\d+[_\-\s]*', '', name)
        return name[:100].strip("_-")

    @staticmethod
    def _escape_yaml(s: str) -> str:
        """转义 YAML 特殊字符"""
        return s.replace('"', '\\"').replace('\n', '\\n')

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
    from devpartner_agent.services.task_queue import get_task_queue
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