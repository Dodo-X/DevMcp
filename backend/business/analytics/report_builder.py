"""
分析型报告生成器（Report Builder）
=================================
将 指标层（metrics）+ 数据质量门禁（dq）组合成"答案先行"的分析型报告。

结构（对标高管可读 + 技术可复核）：
  1. 执行摘要（Primary Insight / Key Evidence / Confidence / Recommended Action）
  2. 数据质量门禁结论（报告可信度前置）
  3. KPI 计分卡（全量指标：当期/环比/状态）
  4. 分维度诊断（每个维度：发生了什么 / 为什么 / 业务含义 / 下一步）
  5. 用户心理与画像（D9 定性层，含 [[用户画像]] wikilink）
  6. 行动建议与待解问题

Obsidian 友好：默认输出 YAML frontmatter（供 Dataview 查询）、#标签、[[wikilink]] 串图谱、
> callout 高亮。用 --plain 可切换为纯 markdown。
"""

from datetime import datetime


def _fmt(v, unit=""):
    if v is None:
        return "—"
    if isinstance(v, dict):
        return " / ".join(
            f"{k} {val}{'%' if unit == '%' else ''}" for k, val in list(v.items())[:6]
        )
    if isinstance(v, float):
        return f"{v:g}{unit}"
    return f"{v}{unit}"


def _delta_str(m):
    dp = m.get("delta_pct")
    if dp is None:
        return "—"
    arrow = "▲" if dp > 0 else "▼" if dp < 0 else "→"
    return f"{arrow}{abs(dp)}%"


def _status_icon(s):
    return {"ok": "✅", "warn": "⚠️", "balanced": "🔄"}.get(s, "•")


def _pick_top_insights(metrics):
    """挑出最值得写进执行摘要的 3-4 条：优先 status=warn，其次 |delta| 大。"""
    flat = []
    for did, block in metrics.items():
        for m in block["metrics"]:
            dp = m.get("delta_pct")
            score = 0
            if m.get("status") == "warn":
                score += 100
            if dp is not None:
                score += abs(dp)
            if m.get("confidence") == "low":
                score -= 20
            flat.append((score, did, block["name"], m))
    flat.sort(key=lambda x: -x[0])
    return [x for x in flat if x[0] > 0][:4]


def _reco_for(m, dname):
    direction = m.get("direction")
    status = m.get("status")
    name = m["id"]
    dp = m.get("delta_pct")
    trend = f"（环比 {('▲' if dp > 0 else '▼')}{abs(dp)}%）" if dp is not None else ""
    if status == "warn":
        if dp is not None and (
            (direction == "down_good" and dp < 0) or (direction == "up_good" and dp > 0)
        ):
            return f"{dname}的 {name} 趋势向好{trend}，仅微超阈值，可观察 1-2 个周期再决定是否干预"
        if direction == "up_good":
            return f"{dname}的 {name} 低于健康基准{trend}，建议定位拖累因子并设专项改进（例：若 debug 占比过高，优先治理不稳定模块）"
        if direction == "down_good":
            return (
                f"{dname}的 {name} 超出健康阈值{trend}，建议排查根因（错误/耗时升高先做失败聚类）"
            )
        return f"关注 {name} 偏离基准{trend}，建议补充细分下钻"
    return f"{name} 处于健康区间{trend}，维持当前节奏；可细化下钻以获取增长机会"


def _global_recos(metrics, dq):
    recos = []
    warns = [
        (did, m["id"]) for did, b in metrics.items() for m in b["metrics"] if m["status"] == "warn"
    ]
    if warns:
        recos.append(
            f"**高优先**：{len(warns)} 个指标触发健康预警（{', '.join(f'{d}.{m}' for d, m in warns)}），"
            f"建议本周内做根因下钻并定责任人。"
        )
    highs = [it for it in dq["issues"] if it["severity"] == "high"]
    if highs:
        recos.append(
            f"**数据治理**：{len(highs)} 项 high 级数据质量问题（如 {highs[0]['check']}）"
            f"正在污染指标，建议作为技术债排期修复（归一映射已就绪，改造量小）。"
        )
    recos.append(
        "**埋点补齐**：知识复用率/内存偏差/闭环时效三项指标因采集缺失暂不可信，"
        "建议优先补齐 usage_count、actual_memory_mb、applied_at 的写入。"
    )
    recos.append(
        "**节奏**：日报看异常、周报看趋势与构成、月报看成长与闭环；本报告可作为周/月报的"
        "结构化骨架，LLM 仅在其上做自然语言润色而非替代计算。"
    )
    recos.append(
        "**心理与画像**：受挫信号占比偏高多为调试型 vocabulary 所致，建议结合 [[devPartner/用户画像]] "
        "的 trend 判断是真实摩擦还是工作性质；成长势能上升时优先加码对应领域的学习计划。"
    )
    return recos


def _frontmatter(metrics, dq, period_start, period_end, period_type, title):
    def grab(mid, key="current"):
        for block in metrics.values():
            for m in block["metrics"]:
                if m["id"] == mid:
                    v = m.get(key)
                    return v if v is not None else ""
        return ""

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    grade = dq.get("grade", "")
    fm = [
        "---",
        "type: devpartner-analytics-report",
        f"period_type: {period_type}",
        f"period_start: {period_start}",
        f"period_end: {period_end}",
        f"generated: {now}",
        f"dq_score: {dq['score']}",
        f"dq_grade: {grade}",
        f"conv_total: {grab('conv_total')}",
        f"step_success_rate: {grab('step_success_rate')}",
        f"real_error_rate: {grab('real_error_rate')}",
        f"reflection_rate: {grab('reflection_rate')}",
        f"portrait_confidence: {grab('portrait_confidence')}",
        "tags:",
        "  - analytics",
        "  - devpartner",
        "  - report",
        "---",
    ]
    return "\n".join(fm)


def build_report(
    metrics,
    dq,
    period_start,
    period_end,
    title="devPartner 分析型报告",
    obsidian=True,
    period_type="snapshot",
):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    if obsidian:
        L.append(_frontmatter(metrics, dq, period_start, period_end, period_type, title))
        L.append("")
    L.append(f"# {title}")
    L.append(f"**统计周期**：{period_start} ~ {period_end}　|　**生成时间**：{now}")
    if obsidian:
        L.append("")
        L.append("#devpartner/report/" + period_type + " #analytics/devpartner")
    L.append("")

    # ── 1. 执行摘要（答案先行）──
    L.append("## 一、执行摘要（答案先行）")
    top = _pick_top_insights(metrics)
    if top:
        L.append("")
        for i, (_score, _did, dname, m) in enumerate(top, 1):
            cur = _fmt(m["current"], m["unit"])
            dp = _delta_str(m)
            conf = m.get("confidence", "low")
            note = m.get("note", "")
            body = (
                f"**洞察 {i}｜{dname} — {m['id']}**：当前 **{cur}**（环比 {dp}），"
                f"状态 {_status_icon(m['status'])}{m['status']}，置信度 {conf}。"
            )
            if obsidian:
                L.append(f"> [!tip] 核心洞察 {i}")
                L.append(f"> {body}")
                if note:
                    L.append(f"> 备注：{note}")
                L.append(f"> 建议：{_reco_for(m, dname)}")
            else:
                L.append(body)
                if note:
                    L.append(f"  - 备注：{note}")
                L.append(f"  - 建议：{_reco_for(m, dname)}")
        L.append("")
    else:
        L.append("\n本期无显著波动指标。")
        L.append("")

    # ── 2. 数据质量门禁 ──
    L.append("## 二、数据质量门禁（报告可信度前置）")
    if obsidian:
        L.append(f"> [!warning] 数据质量 {dq['grade']} 级（{dq['score']}/100）")
        L.append(f"> {dq['summary']}")
    else:
        L.append(f"- **{dq['summary']}**")
    if dq["issues"]:
        L.append("")
        L.append("| 严重度 | 表 | 检查项 | 影响行 | 问题 | 修复建议 |")
        L.append("|---|---|---|---|---|---|")
        for it in sorted(
            dq["issues"], key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]
        ):
            L.append(
                f"| {it['severity']} | {it['table']} | {it['check']} | {it['affected_rows']} | "
                f"{it['detail']} | {it['fix']} |"
            )
    L.append("")

    # ── 3. KPI 计分卡 ──
    L.append("## 三、KPI 计分卡")
    L.append("")
    L.append("| 维度 | 指标 | 当期 | 环比 | 基准 | 状态 | 置信度 |")
    L.append("|---|---|---|---|---|---|---|")
    for _did, block in metrics.items():
        for m in block["metrics"]:
            L.append(
                f"| {block['name']} | {m['id']} | {_fmt(m['current'], m['unit'])} | "
                f"{_delta_str(m)} | {m.get('baseline', '')} | {_status_icon(m['status'])} | "
                f"{m.get('confidence', 'low')} |"
            )
    L.append("")

    # ── 4. 分维度诊断 ──
    L.append("## 四、分维度诊断")
    for did, block in metrics.items():
        L.append(f"\n### {block['name']}（{did}）")
        if did == "D9_user_psychology" and obsidian:
            L.append(
                "> [!note] 定性层：本维度从对话内容 + 用户画像读懂「思维方式 / 协作偏好 / 成长状态」，"
                "关联常青笔记 [[devPartner/用户画像]]。"
            )
        for m in block["metrics"]:
            cur = _fmt(m["current"], m["unit"])
            dp = _delta_str(m)
            L.append(
                f"- **{m['id']}**：{cur}（{dp}）　状态 {_status_icon(m['status'])}　置信度 {m.get('confidence', 'low')}"
            )
            if m.get("note"):
                L.append(f"  - ⚠️ {m['note']}")
    L.append("")

    # ── 5. 行动建议与待解问题 ──
    L.append("## 五、行动建议与待解问题")
    L.append("")
    for r in _global_recos(metrics, dq):
        L.append(f"- {r}")
    L.append("")
    L.append("**待解问题（提升置信度需补齐）**：")
    L.append("- `knowledge_points.usage_count` 埋点缺失 → 知识复用率不可信，需接引用计数")
    L.append("- `actual_memory_mb` 多为空 → 效率维度内存偏差指标暂不可算")
    L.append("- `improvement_log.applied_at` 多为空 → 闭环时效不可算")
    L.append("- `self_reflection` 仍 25/61 为空 → 受挫/心流信号置信度受限，建议强化复盘采集")
    L.append("")
    L.append("---")
    L.append(
        f"*本报表由 devPartner analytics 子系统生成：指标先行 + 数据质量门禁 + 答案先行。"
        f"DQ 评分 {dq['score']}/100。*"
    )
    return "\n".join(L)


def build_portrait_note(portrait, generated=None, source_report=None):
    """生成 Obsidian 常青笔记：用户画像（累积快照，跨报告复用为图谱枢纽）。"""
    now = generated or datetime.now().strftime("%Y-%m-%dT%H:%M")
    L = []
    L.append("---")
    L.append("type: devpartner-user-portrait")
    L.append(f"updated: {now}")
    L.append("tags:")
    L.append("  - analytics")
    L.append("  - devpartner")
    L.append("  - user-portrait")
    L.append("---")
    L.append("")
    L.append("# devPartner 用户画像")
    L.append("")
    L.append("> [!info] 说明")
    L.append(
        "> 本笔记由分析报告自动汇总更新，是 devPartner 对用户**思维方式、协作偏好、能力成长**的结构化画像。"
    )
    if source_report:
        L.append(f"> 最近一期来源报告：[[{source_report}]]")
    L.append("")
    L.append(
        f"> **成长势能**：`{portrait['momentum']}%` 的画像维度呈上升趋势　"
        f"**画像置信度**：`{portrait['portrait_conf']}`（0-1）"
    )
    L.append("")

    L.append("## 心理与能力维度（user_profile）")
    L.append("")
    L.append("| 维度 | 取值 | 趋势 | 置信度 | 观测次数 | 证据 |")
    L.append("|---|---|---|---|---|---|")
    for p in portrait["profile"]:
        ev = (p.get("evidence") or "")[:40].replace("\n", " ")
        L.append(
            f"| {p['dimension']} | {p['value']} | {p.get('trend', '')} | "
            f"{p.get('confidence', '')} | {p.get('observation_count', '')} | {ev} |"
        )
    L.append("")

    L.append("## 技能树（user_skills）")
    L.append("")
    L.append("| 领域 | 技能 | 等级 | 成长趋势 | 置信度 | 投入(h) |")
    L.append("|---|---|---|---|---|---|")
    for s in portrait["skills"]:
        L.append(
            f"| {s.get('skill_domain', '')} | {s.get('skill_name', '')} | {s.get('skill_level', '')} | "
            f"{s.get('growth_trend', '')} | {s.get('confidence', '')} | "
            f"{(round(s['hours_spent'], 1) if s.get('hours_spent') is not None else '—')} |"
        )
    L.append("")

    L.append("## 学习计划（user_skill_plan）")
    L.append("")
    L.append("| 领域 | 目标 | 目标等级 | 进度 | 状态 |")
    L.append("|---|---|---|---|---|")
    for p in portrait["plans"]:
        L.append(
            f"| {p.get('skill_domain', '')} | {p.get('goal', '')} | {p.get('target_level', '')} | "
            f"{(p.get('current_progress') or '—')} | {p.get('status', '')} |"
        )
    L.append("")
    L.append("---")
    L.append("*由 devPartner analytics 子系统自动维护；本笔记是报告图谱的常青枢纽节点。*")
    return "\n".join(L)
