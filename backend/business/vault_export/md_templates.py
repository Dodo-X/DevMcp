"""
MD 模板注册表 v1.0 — 所有 MD 文档类型的模板定义
===============================================

每种文档类型 = 一个 MdTemplate 实例，独立定义，互不干扰。
新增 MD 类型只需在这里添加一个模板定义 + 调用 register_all()。

当前注册的模板：
  daily_report, weekly_report, monthly_report, annual_report,
  user_profile, project_profile, skill_card, business_card,
  project_dashboard
"""

import logging
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from .md_engine import (
    MdAssembler,
    MdSection,
    MdTemplate,
    get_assembler,
    render_achievements,
    render_kv,
    render_list,
    render_metrics,
    render_project_dimension,
    render_psychology,
    render_text,
    render_user_profile,
)

# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


def _safe_path(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "-", name).strip()


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"^\d+[_\-\s]*", "", name)
    return name[:100].strip("_-")


def _week_label(period_start: str) -> str:
    return datetime.strptime(period_start, "%Y-%m-%d").strftime("%Y-W%W")


def _month_label(period_start: str) -> str:
    return datetime.strptime(period_start, "%Y-%m-%d").strftime("%Y-%m")


def _maturity_label(m: str) -> str:
    return {"unknown": "未知", "early": "初期", "growing": "成长期", "mature": "成熟期"}.get(m, m)


def _derive_project_name() -> str:
    return os.path.basename(os.getcwd())


def _safe_json(val, default):
    if not val:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        import json

        return json.loads(val)
    except Exception:
        logger.warning("_safe_json: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return default


def _escape_yaml(s: str) -> str:
    return s.replace('"', '\\"').replace("\n", "\\n")


# ══════════════════════════════════════════════════════════
# Frontmatter 构建器
# ══════════════════════════════════════════════════════════


def _daily_fm(data: dict) -> dict:
    rd = data.get("report_data", {})
    proj = rd.get("project_analysis", {}).get("projects", [])
    proj_names = [p.get("project_name", "") for p in proj if p.get("project_name")]
    metrics = rd.get("metrics", {}) or {}

    def _score(k: str):
        v = metrics.get(k)
        if isinstance(v, dict):
            return v.get("score")
        return v

    psy = rd.get("psychology") or {}
    tags = ["daily-report", "devpartner"]
    tags += [f"proj-{p}" for p in proj_names if p]

    date_str = data.get("date_str", "")
    week = ""
    month = ""
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            week = d.strftime("%Y-W%W")
            month = d.strftime("%Y-%m")
        except ValueError:
            pass

    fm = {
        "type": "daily_report",
        "date": date_str,
        "engine": rd.get("inference_engine", "ollama"),
        "projects": proj_names,
        "tags": tags,
        "generated": datetime.now().isoformat(),
    }

    # 可选字段：仅在有值时输出，避免 YAML 中出现 "None" 字符串
    for key, val in [
        ("week", week),
        ("month", month),
        ("productivity_score", _score("productivity_score")),
        ("learning_score", _score("learning_score")),
        ("collaboration_score", _score("collaboration_score")),
        ("focus_score", _score("focus_score")),
        ("frustration_level", psy.get("frustration_level")),
    ]:
        if val is not None and val != "":
            fm[key] = val

    return fm


def _weekly_fm(data: dict) -> dict:
    ps = data.get("period_start", "")
    pe = data.get("period_end", "")
    rd = data.get("report_data", {}) or {}

    fm = {
        "type": "weekly_report",
        "period_start": ps,
        "period_end": pe,
        "week": _week_label(ps),
        "sources": [f"Calendar/{ps}.md", f"Calendar/{pe}.md"],
        "generated": datetime.now().isoformat(),
    }
    # 可选字段
    for key, val in [
        ("overall_score", (rd.get("metrics", {}) or {}).get("overall_score")),
        ("emotional_state_trend", (rd.get("psychology", {}) or {}).get("emotional_state_trend")),
    ]:
        if val is not None and val != "":
            fm[key] = val
    return fm


def _monthly_fm(data: dict) -> dict:
    ps = data.get("period_start", "")
    rd = data.get("report_data", {}) or {}

    fm = {
        "type": "monthly_report",
        "period_start": ps,
        "period_end": data.get("period_end", ""),
        "month": _month_label(ps),
        "sources": [f"Reports/Weekly/{ps[:4]}-W*.md"],
        "generated": datetime.now().isoformat(),
    }
    for key, val in [
        ("overall_productivity", (rd.get("metrics", {}) or {}).get("overall_productivity")),
        ("emotional_state_trend", (rd.get("psychology", {}) or {}).get("emotional_state_trend")),
    ]:
        if val is not None and val != "":
            fm[key] = val
    return fm


def _annual_fm(data: dict) -> dict:
    y = data.get("year", "")
    rd = data.get("report_data", {}) or {}

    fm = {
        "type": "annual_report",
        "year": y,
        "sources": [f"Reports/Monthly/{y}-*.md"],
        "generated": datetime.now().isoformat(),
    }
    for key, val in [
        ("overall_growth_score", (rd.get("metrics", {}) or {}).get("overall_growth_score")),
        ("emotional_state_trend", (rd.get("psychology", {}) or {}).get("emotional_state_trend")),
    ]:
        if val is not None and val != "":
            fm[key] = val
    return fm


def _card_fm(
    card_type: str,
    domain: str,
    title: str,
    tags: list,
    created: str,
    knowledge_id: str = "",
    source: str = "",
    project: str = "",
) -> str:
    """构建知识卡片 YAML frontmatter（返回字符串以保留格式）"""
    lines = ["---"]
    lines.append(f"type: {card_type}_card")
    lines.append(f'domain: "{_escape_yaml(domain)}"')
    if project:
        lines.append(f'project: "{_escape_yaml(project)}"')
    lines.append(f'title: "{_escape_yaml(title)}"')
    tag_list = (tags or []) + ["review"]
    tag_str = ", ".join(tag_list)
    lines.append(f"tags: [{tag_str}]")
    lines.append(f'created: "{created or datetime.now().isoformat()}"')
    if knowledge_id:
        lines.append(f'knowledge_id: "{knowledge_id}"')
    if source:
        lines.append(f'source: "{_escape_yaml(source)}"')
    lines.append("---")
    return "\n".join(lines)


def _profile_fm(data: dict) -> dict:
    return {
        "type": "user_profile",
        "date": data.get("date_str", ""),
        "updated": datetime.now().isoformat(),
    }


def _project_fm(data: dict) -> dict:
    return {
        "type": "project_profile",
        "system_id": data.get("system_id", ""),
        "updated": datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════
# 模板注册
# ══════════════════════════════════════════════════════════


def register_all(assembler: MdAssembler = None):
    """
    注册所有 9 种 MD 文档模板到装配器。

    每种文档类型 = 一个 MdTemplate，独立定义，互不干扰。
    """
    if assembler is None:
        assembler = get_assembler()

    # ──── 1. 日报 ────
    assembler.register(
        MdTemplate(
            template_id="daily_report",
            title_builder=lambda d: f"# 📅 {d['date_str']} 日报",
            output_path_rule=lambda v, d: v / "Calendar" / f"{d['date_str']}.md",
            header_lines=lambda d: [
                f"> 生成时间: {datetime.now():%Y-%m-%d %H:%M}",
                f"> 引擎: {(d.get('report_data') or {}).get('inference_engine', 'ollama')}",
                "",
            ],
            sections=[
                MdSection(
                    "report_data",
                    "## 📋 总结",
                    render_text,
                    kv_map=[("summary", "")],
                    condition=lambda d: bool((d.get("report_data") or {}).get("summary")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 事实锚点",
                    render_kv,
                    kv_map=[("facts", "事实锚点")],
                    condition=lambda d: bool((d.get("report_data") or {}).get("facts")),
                ),
                MdSection(
                    "report_data",
                    "## 🔍 深度体验",
                    render_kv,
                    kv_map=[("deep_dive", "深入探索"), ("lesson", "经验教训")],
                    condition=lambda d: bool((d.get("report_data") or {}).get("experience")),
                ),
                MdSection(
                    "report_data",
                    "## 🛠️ 技能",
                    render_kv,
                    kv_map=[("patterns", "模式")],
                    condition=lambda d: bool((d.get("report_data") or {}).get("skills")),
                ),
                MdSection(
                    "report_data",
                    "## 📚 知识",
                    render_kv,
                    kv_map=[
                        ("insights", "洞察"),
                        ("decisions", "技术决策"),
                        ("solutions", "问题解决"),
                        ("bugs", "Bug 修复"),
                    ],
                    condition=lambda d: bool((d.get("report_data") or {}).get("knowledge")),
                ),
                MdSection(
                    "report_data",
                    "## ⚠️ 危险信号",
                    render_kv,
                    kv_map=[("repeated_mistakes", "重复错误"), ("tech_debt", "技术债务")],
                    condition=lambda d: bool((d.get("report_data") or {}).get("danger_signals")),
                ),
                MdSection(
                    "report_data",
                    "## 🌱 成长规划",
                    render_kv,
                    kv_map=[("growth_plan", "成长建议")],
                    condition=lambda d: bool((d.get("report_data") or {}).get("growth_plan")),
                ),
                MdSection(
                    "report_data",
                    "## 👤 用户画像变化",
                    render_kv,
                    kv_map=[("behavior_signals", "行为信号")],
                    condition=lambda d: bool(
                        (d.get("report_data") or {}).get("user_profile_update")
                    ),
                ),
                MdSection(
                    "report_data",
                    "## 🏗️ 项目画像变化",
                    render_kv,
                    kv_map=[("architecture_changes", "架构"), ("business_changes", "业务")],
                    condition=lambda d: bool(
                        (d.get("report_data") or {}).get("project_profile_update")
                    ),
                ),
                MdSection(
                    "report_data",
                    "## 📊 指标",
                    render_metrics,
                    kv_map=[
                        ("productivity_score", "生产力"),
                        ("learning_score", "学习"),
                        ("collaboration_score", "协作"),
                        ("focus_score", "专注"),
                    ],
                    condition=lambda d: bool((d.get("report_data") or {}).get("metrics")),
                ),
                MdSection(
                    "report_data",
                    "## 🧠 心理与协作信号",
                    render_psychology,
                    kv_map=[
                        ("frustration_level", "挫败水平(1-5)"),
                        ("flow_signals", "心流信号"),
                        ("decision_style", "决策风格"),
                        ("recurring_blockers", "反复阻塞"),
                    ],
                    condition=lambda d: bool((d.get("report_data") or {}).get("psychology")),
                ),
                MdSection(
                    "report_data",
                    "## 🔍 自我反思",
                    render_kv,
                    kv_map=[
                        ("strengths", "优势"),
                        ("weaknesses", "待改进"),
                        ("growthSuggestions", "成长建议"),
                    ],
                    condition=lambda d: bool((d.get("report_data") or {}).get("self_analysis")),
                ),
                MdSection(
                    "report_data",
                    "## 🏗️ 项目维度",
                    render_project_dimension,
                    condition=lambda d: bool(
                        ((d.get("report_data") or {}).get("project_analysis") or {}).get("projects")
                    ),
                ),
                # ── v9.12: 分析数据渲染段 ──
                MdSection(
                    "report_data",
                    "## 📈 指标趋势",
                    _render_metrics_trend_table,
                    condition=lambda d: bool(
                        (d.get("report_data") or {}).get("analytics", {}).get("metrics_trends")
                    ),
                ),
                MdSection(
                    "report_data",
                    "## 📚 知识库增长",
                    _render_knowledge_stats,
                    condition=lambda d: bool(
                        (d.get("report_data") or {}).get("analytics", {}).get("knowledge_stats")
                    ),
                ),
                MdSection(
                    "report_data",
                    "## 🛠️ 技能与学习进度",
                    _render_skill_progress,
                    condition=lambda d: bool(
                        (d.get("report_data") or {}).get("analytics", {}).get("skill_summary")
                    ),
                ),
            ],
            frontmatter_builder=_daily_fm,
            footer_lines=_build_daily_footer,
        )
    )

    # ──── 2. 周报 ────
    assembler.register(
        MdTemplate(
            template_id="weekly_report",
            title_builder=lambda d: f"# 📆 {_week_label(d['period_start'])} 周报",
            output_path_rule=lambda v, d: (
                v / "Reports" / "Weekly" / f"{_week_label(d['period_start'])}.md"
            ),
            header_lines=lambda d: [
                f"> 周期: {d['period_start']} ~ {d['period_end']}",
                f"> 生成时间: {datetime.now():%Y-%m-%d %H:%M}",
                "",
            ],
            sections=[
                MdSection(
                    "report_data",
                    "## 📋 总结",
                    render_text,
                    kv_map=[("summary", "")],
                    condition=lambda d: bool(d.get("report_data", {}).get("summary")),
                ),
                MdSection(
                    "report_data",
                    "## 🏆 关键成果",
                    render_achievements,
                    condition=lambda d: bool(d.get("report_data", {}).get("key_achievements")),
                ),
                MdSection(
                    "report_data",
                    "## 🛠️ 技能进展",
                    render_kv,
                    kv_map=[
                        ("new_skills_acquired", "新掌握"),
                        ("skills_improved", "提升"),
                        ("skills_to_learn", "待学习"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("skill_progress")),
                ),
                MdSection(
                    "report_data",
                    "## ⚠️ 风险评估",
                    render_kv,
                    kv_map=[
                        ("technical_risks", "技术风险"),
                        ("knowledge_gaps", "知识盲区"),
                        ("process_issues", "流程问题"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("risk_assessment")),
                ),
                MdSection(
                    "report_data",
                    "## 📋 下周计划",
                    render_kv,
                    kv_map=[
                        ("priorities", "优先事项"),
                        ("learning_goals", "学习目标"),
                        ("experiments", "实验"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("next_week_plan")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 指标",
                    render_kv,
                    kv_map=[
                        ("productivity_trend", "生产力趋势"),
                        ("learning_velocity", "学习速度"),
                        ("code_quality_trend", "代码质量"),
                        ("overall_score", "综合评分"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("metrics")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 事实锚点",
                    render_kv,
                    kv_map=[("facts", "事实锚点")],
                    condition=lambda d: bool(d.get("report_data", {}).get("facts")),
                ),
                MdSection(
                    "report_data",
                    "## 🧠 心理与协作信号",
                    render_psychology,
                    kv_map=[
                        ("emotional_state_trend", "情绪走向"),
                        ("recurring_friction", "反复卡点"),
                        ("growth_mindset", "成长思维"),
                        ("communication_pattern", "沟通风格"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("psychology")),
                ),
            ],
            frontmatter_builder=_weekly_fm,
            footer_lines=_build_weekly_footer,
        )
    )

    # ──── 3. 月报 ────
    assembler.register(
        MdTemplate(
            template_id="monthly_report",
            title_builder=lambda d: f"# 🗓️ {_month_label(d['period_start'])} 月报",
            output_path_rule=lambda v, d: (
                v / "Reports" / "Monthly" / f"{_month_label(d['period_start'])}.md"
            ),
            header_lines=lambda d: [
                f"> 周期: {d['period_start']} ~ {d['period_end']}",
                f"> 生成时间: {datetime.now():%Y-%m-%d %H:%M}",
                "",
            ],
            sections=[
                MdSection(
                    "report_data",
                    "## 📋 总结",
                    render_text,
                    kv_map=[("summary", "")],
                    condition=lambda d: bool(d.get("report_data", {}).get("summary")),
                ),
                MdSection(
                    "report_data",
                    "## 🏆 重大成果",
                    render_achievements,
                    condition=lambda d: bool(d.get("report_data", {}).get("major_achievements")),
                ),
                MdSection(
                    "report_data",
                    "## 🛠️ 技能演进",
                    render_kv,
                    kv_map=[
                        ("skills_at_start", "月初"),
                        ("skills_at_end", "月末"),
                        ("growth_highlights", "成长亮点"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("skill_evolution")),
                ),
                MdSection(
                    "report_data",
                    "## ⚠️ 风险与债务",
                    render_kv,
                    kv_map=[
                        ("critical_risks", "关键风险"),
                        ("tech_debt_accumulated", "技术债务"),
                        ("knowledge_debt", "知识欠债"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("risk_and_debt")),
                ),
                MdSection(
                    "report_data",
                    "## 📋 下月计划",
                    render_kv,
                    kv_map=[
                        ("strategic_goals", "战略目标"),
                        ("tactical_actions", "行动项"),
                        ("learning_roadmap", "学习路线"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("next_month_plan")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 指标",
                    render_kv,
                    kv_map=[
                        ("overall_productivity", "综合生产力"),
                        ("skill_growth_rate", "技能增长率"),
                        ("project_health", "项目健康度"),
                        ("work_life_balance", "工作生活平衡"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("metrics")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 事实锚点",
                    render_kv,
                    kv_map=[("facts", "事实锚点")],
                    condition=lambda d: bool(d.get("report_data", {}).get("facts")),
                ),
                MdSection(
                    "report_data",
                    "## 🧠 心理与协作信号",
                    render_psychology,
                    kv_map=[
                        ("emotional_state_trend", "情绪走向"),
                        ("recurring_friction", "反复卡点"),
                        ("growth_mindset", "成长思维"),
                        ("communication_pattern", "沟通风格"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("psychology")),
                ),
            ],
            frontmatter_builder=_monthly_fm,
        )
    )

    # ──── 4. 年报 ────
    assembler.register(
        MdTemplate(
            template_id="annual_report",
            title_builder=lambda d: f"# 📖 {d['year']} 年报",
            output_path_rule=lambda v, d: v / "Reports" / "Annual" / f"{d['year']}.md",
            header_lines=lambda d: [f"> 生成时间: {datetime.now():%Y-%m-%d %H:%M}", ""],
            sections=[
                MdSection(
                    "report_data",
                    "## 📋 年度总结",
                    render_text,
                    kv_map=[("summary", "")],
                    condition=lambda d: bool(d.get("report_data", {}).get("summary")),
                ),
                MdSection(
                    "report_data",
                    "## 🔭 年度回顾",
                    render_kv,
                    kv_map=[
                        ("defining_moments", "定义性时刻"),
                        ("biggest_achievements", "最大成就"),
                        ("hardest_challenges", "最困难挑战"),
                        ("unexpected_discoveries", "意外发现"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("year_in_review")),
                ),
                MdSection(
                    "report_data",
                    "## 🛠️ 技能旅程",
                    render_kv,
                    kv_map=[
                        ("skills_at_year_start", "年初"),
                        ("skills_at_year_end", "年末"),
                        ("breakthrough_skills", "突破性提升"),
                        ("abandoned_skills", "搁置方向"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("skill_journey")),
                ),
                MdSection(
                    "report_data",
                    "## 📈 成长分析",
                    render_kv,
                    kv_map=[
                        ("learning_curve", "学习曲线"),
                        ("productivity_evolution", "生产力演变"),
                        ("decision_making_maturity", "决策成熟度"),
                        ("communication_style_evolution", "沟通风格演变"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("growth_analysis")),
                ),
                MdSection(
                    "report_data",
                    "## 🎯 下年愿景",
                    render_kv,
                    kv_map=[
                        ("strategic_direction", "战略方向"),
                        ("skill_goals", "技能目标"),
                        ("project_ambitions", "项目愿景"),
                        ("learning_commitments", "学习承诺"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("next_year_vision")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 指标",
                    render_kv,
                    kv_map=[
                        ("overall_growth_score", "综合成长"),
                        ("technical_depth", "技术深度"),
                        ("breadth_of_knowledge", "知识广度"),
                        ("impact_level", "影响力"),
                        ("sustainability", "可持续性"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("metrics")),
                ),
                MdSection(
                    "report_data",
                    "## 📊 事实锚点",
                    render_kv,
                    kv_map=[("facts", "事实锚点")],
                    condition=lambda d: bool(d.get("report_data", {}).get("facts")),
                ),
                MdSection(
                    "report_data",
                    "## 🧠 心理与协作信号",
                    render_psychology,
                    kv_map=[
                        ("emotional_state_trend", "情绪走向"),
                        ("recurring_friction", "反复卡点"),
                        ("growth_mindset", "成长思维"),
                        ("communication_pattern", "沟通风格"),
                    ],
                    condition=lambda d: bool(d.get("report_data", {}).get("psychology")),
                ),
            ],
            frontmatter_builder=_annual_fm,
        )
    )

    # ──── 5. 用户画像 ────
    assembler.register(
        MdTemplate(
            template_id="user_profile",
            title_builder=lambda d: "# 用户画像",
            output_path_rule=lambda v, d: v / "Atlas" / "用户画像.md",
            header_lines=lambda d: [
                f"> 最后更新: {datetime.now():%Y-%m-%d %H:%M}",
                "",
                "## 画像维度",
                "",
            ],
            sections=[
                MdSection("profile_data", "", render_user_profile, kv_map=[("dimensions", "")]),
            ],
            frontmatter_builder=_profile_fm,
        )
    )

    # ──── 6. 项目画像 ────
    assembler.register(
        MdTemplate(
            template_id="project_profile",
            title_builder=lambda d: f"# {d['system_id']} 项目画像",
            output_path_rule=lambda v, d: (
                v / "Efforts" / _safe_path(d["system_id"]) / "项目画像.md"
            ),
            header_lines=lambda d: [
                f"> 最后更新: {datetime.now():%Y-%m-%d %H:%M}",
                "",
                f"## 成熟度: {_maturity_label((d.get('project_data') or {}).get('maturity', 'unknown'))}",
                "",
            ],
            sections=[
                MdSection(
                    "project_data",
                    "## 技术栈",
                    render_list,
                    condition=lambda d: bool((d.get("project_data") or {}).get("tech_stack")),
                ),
                MdSection(
                    "project_data",
                    "## 架构",
                    render_kv,
                    kv_map=[("pattern", "模式"), ("components", "核心组件")],
                    condition=lambda d: bool((d.get("project_data") or {}).get("architecture")),
                ),
                MdSection(
                    "project_data",
                    "## 业务领域",
                    render_list,
                    condition=lambda d: bool((d.get("project_data") or {}).get("business_domains")),
                ),
            ],
            frontmatter_builder=_project_fm,
        )
    )

    # ──── 7. 技能卡片 ────
    # 注意：卡片使用直接渲染而非模板引擎，因为 frontmatter 格式复杂（需要 _card_fm 字符串返回）
    # skill_card 模板只作为注册存在，实际渲染仍走 VaultExporter._export_card

    # ──── 8. 业务卡片 ────
    # 同上

    # ──── 9. 项目仪表盘 ────
    # 仪表盘逻辑特殊（需要扫描 Calendar 目录 + Cards 目录），
    # 保留在 VaultExporter._write_project_dashboard 中

    logger.info(f"📝 所有 MD 模板已注册 ({len(assembler.list_templates())} 个)")


# ══════════════════════════════════════════════════════════
# v9.12: 分析数据渲染函数
# ══════════════════════════════════════════════════════════


def _render_metrics_trend_table(data: dict) -> str:
    """渲染近7日指标趋势表格"""
    trends = data.get("metrics_trends", [])
    if not trends:
        return "*暂无趋势数据*"

    lines = [
        "| 日期 | 生产力 | 学习 | 协作 | 专注 | 挫败 |",
        "|------|--------|------|------|------|------|",
    ]
    for t in trends:
        p = t.get("productivity", "-") or "-"
        l = t.get("learning", "-") or "-"
        c = t.get("collaboration", "-") or "-"
        f = t.get("focus", "-") or "-"
        fr = t.get("frustration", "-") or "-"
        lines.append(f"| {t['date']} | {p} | {l} | {c} | {f} | {fr} |")

    vs = data.get("metrics_today_vs_yesterday")
    if vs:
        lines.append("")
        lines.append("**与昨日对比:**")
        direction_map = {"up": "\u2191", "down": "\u2193", "flat": "\u2192", "new": "\uD83C\uDD95"}
        for dim, comp in vs.items():
            dirc = direction_map.get(comp.get("direction", "flat"), "\u2192")
            lines.append(
                f"- {dim}: {comp['current']}/10 {dirc} "
                f"(昨日 {comp['previous']}/10, 变化 {comp['change']:+d})"
            )

    return "\n".join(lines)


def _render_knowledge_stats(data: dict) -> str:
    """渲染知识库增长统计"""
    ks = data.get("knowledge_stats", {})
    if not ks:
        return "*暂无知识库数据*"

    lines = [
        f"- **知识库总量**: {ks.get('total', 0)} 条知识点",
        f"- **今日新增**: {ks.get('new_today', 0)} 条",
        f"- **已被使用**: {ks.get('used', 0)} 条",
        f"- **覆盖领域**: {len(ks.get('domains', []))} 个",
        "",
        "**领域分布:**",
    ]
    for domain, cnt in ks.get("by_domain", {}).items():
        lines.append(f"- {domain}: {cnt} 条")

    return "\n".join(lines)


def _render_skill_progress(data: dict) -> str:
    """渲染技能与学习进度"""
    ss = data.get("skill_summary", {})
    lp = data.get("learning_plan", {})
    lines = []

    if ss:
        lines.append(f"**技能树**: {ss.get('total_skills', 0)} 项技能, 覆盖 {len(ss.get('domains', []))} 个领域")
        lines.append("")
        for domain, items in ss.get("detail", {}).items():
            skills_str = ", ".join(f"{s['name']}({s['level']})" for s in items[:5])
            lines.append(f"- **{domain}**: {skills_str}")
            if len(items) > 5:
                lines[-1] += f" ... +{len(items) - 5}"

    if lp:
        lines.append("")
        lines.append(
            f"**学习计划**: {lp.get('total', 0)} 项, "
            f"进行中 {lp.get('active', 0)}, 已完成 {lp.get('completed', 0)}"
        )
        for item in lp.get("active_items", [])[:3]:
            lines.append(f"- [{item['domain']}] {item['goal']} -> {item['target']}")

    return "\n".join(lines) if lines else "*暂无技能数据*"


# ══════════════════════════════════════════════════════════
# 特殊 footer 构建器
# ══════════════════════════════════════════════════════════


def _build_daily_footer(data: dict) -> list[str]:
    """日报关联文档 footer — 构建双向链接网络"""
    lines = ["## 🔗 关联文档", ""]
    rd = data.get("report_data", {})
    pa = rd.get("project_analysis", {})
    projects = pa.get("projects", [])

    # 项目仪表盘链接
    if projects:
        links = []
        for p in projects:
            pname = p.get("project_name", "")
            if pname:
                safe = _safe_path(pname)
                links.append(f"[[Efforts/{safe}/项目仪表盘|{pname} 仪表盘]]")
        if links:
            lines.append(f"- **项目分析**: {'、'.join(links)}")

    # 知识卡片链接
    kb_links = []
    for p in projects:
        for kb in p.get("knowledge_for_base", []):
            title = kb.get("title", "")
            tags = kb.get("tags", [])
            domain = tags[0] if tags else "通用"
            if title:
                kb_links.append(f"[[Cards/{domain}/{title}]]")
    if kb_links:
        lines.append(f"- **知识卡片**: {'、'.join(kb_links[:10])}")
        if len(kb_links) > 10:
            lines.append(f"  （共 {len(kb_links)} 张卡片）")

    # 导航链接（始终存在，保证知识图谱最低连通性）
    lines.extend(
        [
            "",
            "## 🧭 导航",
            "",
            "- 📅 [[日历索引|所有日报]]",
            "- 📊 [[../Reports/报告索引|所有报告]]",
            "- 🗺️ [[../Atlas/图谱总览|知识图谱]]",
            "- 🏠 [[../Home|首页]]",
            "",
        ]
    )

    # 连接同周期报告
    date_str = data.get("date_str", "")
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            week_label = d.strftime("%Y-W%W")
            month_label = d.strftime("%Y-%m")
            lines.append("## 📆 同期报告")
            lines.append("")
            lines.append(f"- 周报: [[../Reports/Weekly/{week_label}]]")
            lines.append(f"- 月报: [[../Reports/Monthly/{month_label}]]")
            lines.append(f"- 年报: [[../Reports/Annual/{d.year}]]")
            lines.append("")
        except ValueError:
            pass

    lines.extend(["---", "", "*本日报由 DevPartner AI 自动生成*", ""])
    return lines


def _build_weekly_footer(data: dict) -> list[str]:
    """周报关联文档 footer"""
    lines = ["## 🔗 关联文档", ""]
    try:
        ps = data.get("period_start", "")
        pe = data.get("period_end", "")
        if ps and pe:
            start = datetime.strptime(ps, "%Y-%m-%d")
            end = datetime.strptime(pe, "%Y-%m-%d")
            day_links = []
            current = start
            while current <= end:
                day_links.append(f"[[Calendar/{current.strftime('%Y-%m-%d')}]]")
                current += timedelta(days=1)
            lines.append(f"- **日报**: {', '.join(day_links)}")
            lines.append(f"- **月报**: [[Reports/Monthly/{start.strftime('%Y-%m')}]]")
    except ValueError:
        pass
    lines.append("")
    return lines
