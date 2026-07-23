"""
用户心理与画像（User Psychology & Capability Portrait）
======================================================
D9 维度：定性内容分析层。devPartner 不只要"数行为"，还要从对话内容里
读懂"用户在想什么、怎么想、在成长还是受挫"。

数据来源：
  - conversations.topic / user_intent / self_reflection / complexity  → 内容信号
  - user_profile    → 已结构化的心理/能力维度（带 trend / confidence / evidence）
  - user_skills     → 技能树（growth_trend / confidence / hours_spent）
  - user_skill_plan → 学习计划（goal / current_progress / status）
  - knowledge_points.domain → 知识领域覆盖（能力雷达）

方法论（定量结构 + 定性信号 的混合，非黑箱）：
  - 复盘率 / 意图清晰度：内容完整度（越高越利于后续分析）
  - 心理信号：中文词典法（risk / progress lexicon）对 self_reflection 做透明扫描，
    给出"受挫/风险信号占比"与"进展/心流信号占比"。词典可审计、可迭代；
    深度心理编码建议叠加 LLM 定性摘要（在指标之上叙述，不替代计算）。
  - 画像置信度 / 成长势能：聚合 user_profile 的 confidence 与 trend
  - 技能树 / 计划完成率：user_skills / user_skill_plan 聚合

置信度随文本填充率给定；累积型指标（画像/技能/计划）仅给当期快照，无环比。
"""

# ── 心理信号词典（透明、可审计、可迭代）──
RISK_LEXICON = [
    "暴露",
    "问题",
    "失败",
    "崩溃",
    "炸弹",
    "报错",
    "异常",
    "卡",
    "丢失",
    "损坏",
    "缺失",
    "不一致",
    "缺陷",
    "错误",
    "困难",
    "坑",
    "隐患",
]
PROGRESS_LEXICON = [
    "高效",
    "顺利",
    "解决",
    "成功",
    "清晰",
    "优化",
    "提升",
    "流畅",
    "完成",
    "达成",
    "突破",
    "顺畅",
    "稳定",
]


def _pct(cur, prev):
    if prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 1)


def _conf(n, caveat=False):
    if caveat:
        return "low"
    if n is None:
        return "low"
    if n >= 30:
        return "high"
    if n >= 10:
        return "medium"
    return "low"


def _scan_signals(texts):
    """返回 (risk_n, progress_n, total)。一条复盘可同时含风险与进展信号。"""
    risk = progress = 0
    for t in texts:
        if not t:
            continue
        if any(k in t for k in RISK_LEXICON):
            risk += 1
        if any(k in t for k in PROGRESS_LEXICON):
            progress += 1
    return risk, progress, len(texts)


def compute_portrait(cur):
    """聚合用户画像结构（供 D9 指标 + Obsidian 常青笔记复用）。"""
    profile = []
    for r in cur.execute(
        "SELECT dimension,value,trend,confidence,observation_count,evidence "
        "FROM user_profile ORDER BY confidence DESC"
    ):
        profile.append(dict(r))
    skills = []
    for r in cur.execute(
        "SELECT skill_domain,skill_name,skill_level,growth_trend,confidence,hours_spent "
        "FROM user_skills ORDER BY confidence DESC"
    ):
        skills.append(dict(r))
    plans = []
    for r in cur.execute(
        "SELECT skill_domain,goal,target_level,current_progress,status "
        "FROM user_skill_plan ORDER BY status, skill_domain"
    ):
        plans.append(dict(r))
    dims = [p["trend"] for p in profile]
    momentum = round(sum(1 for t in dims if t == "rising") / len(dims) * 100, 1) if dims else 0
    portrait_conf = (
        round(sum(p["confidence"] for p in profile) / len(profile), 2) if profile else None
    )
    return {
        "profile": profile,
        "skills": skills,
        "plans": plans,
        "momentum": momentum,
        "portrait_conf": portrait_conf,
    }


def compute_psychology(cur, start, end, prev_start, prev_end):
    """返回 D9 维度指标列表（与 metrics.py 各维度同构）。"""

    # ── 内容完整度（受周期约束）──
    def completeness(s, e):
        tot = cur.execute(
            "SELECT COUNT(*) FROM conversations WHERE date(timestamp) BETWEEN ? AND ?", (s, e)
        ).fetchone()[0]
        refl = cur.execute(
            "SELECT COUNT(*) FROM conversations WHERE date(timestamp) BETWEEN ? AND ? "
            "AND self_reflection IS NOT NULL AND self_reflection!=''",
            (s, e),
        ).fetchone()[0]
        intent = cur.execute(
            "SELECT COUNT(*) FROM conversations WHERE date(timestamp) BETWEEN ? AND ? "
            "AND user_intent IS NOT NULL AND user_intent!=''",
            (s, e),
        ).fetchone()[0]
        return tot, refl, intent

    c_tot, c_refl, c_intent = completeness(start, end)
    p_tot, p_refl, p_intent = completeness(prev_start, prev_end)
    refl_rate = round(c_refl / c_tot * 100, 1) if c_tot else 0
    p_refl_rate = round(p_refl / p_tot * 100, 1) if p_tot else 0
    intent_rate = round(c_intent / c_tot * 100, 1) if c_tot else 0
    p_intent_rate = round(p_intent / p_tot * 100, 1) if p_tot else 0

    # ── 心理信号扫描（仅本期有复盘的对话）──
    texts = [
        r[0]
        for r in cur.execute(
            "SELECT self_reflection FROM conversations WHERE date(timestamp) BETWEEN ? AND ? "
            "AND self_reflection IS NOT NULL AND self_reflection!=''",
            (start, end),
        )
    ]
    risk_n, prog_n, refl_with_text = _scan_signals(texts)
    risk_share = round(risk_n / refl_with_text * 100, 1) if refl_with_text else 0
    prog_share = round(prog_n / refl_with_text * 100, 1) if refl_with_text else 0

    # ── 画像聚合（累积快照）──
    por = compute_portrait(cur)
    skill_n = len(por["skills"])
    done = sum(1 for p in por["plans"] if p["status"] == "done")
    total_plan = len(por["plans"])
    plan_adh = round(done / total_plan * 100, 1) if total_plan else 0

    return [
        {
            "id": "reflection_rate",
            "current": refl_rate,
            "previous": p_refl_rate,
            "delta_pct": _pct(refl_rate, p_refl_rate),
            "unit": "%",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _conf(c_refl),
            "note": "self_reflection 填充率，越高越利于内容分析",
        },
        {
            "id": "intent_clarity",
            "current": intent_rate,
            "previous": p_intent_rate,
            "delta_pct": _pct(intent_rate, p_intent_rate),
            "unit": "%",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _conf(c_intent),
        },
        {
            "id": "psych_risk_signal",
            "current": risk_share,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "<30%",
            "direction": "down_good",
            "confidence": _conf(refl_with_text),
            "note": "含风险/受挫关键词的复盘占比（中文词典法，可审计）",
        },
        {
            "id": "psych_progress_signal",
            "current": prog_share,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _conf(refl_with_text),
            "note": "含进展/心流关键词的复盘占比（中文词典法）",
        },
        {
            "id": "portrait_confidence",
            "current": por["portrait_conf"],
            "previous": None,
            "delta_pct": None,
            "unit": "",
            "baseline": ">0.7",
            "direction": "up_good",
            "confidence": "high",
            "note": "user_profile 平均置信度（累积快照）",
        },
        {
            "id": "growth_momentum",
            "current": por["momentum"],
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": "high",
            "note": "trend='rising' 的画像维度占比（累积快照）",
        },
        {
            "id": "skill_tree_size",
            "current": skill_n,
            "previous": None,
            "delta_pct": None,
            "unit": "个",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _conf(skill_n),
        },
        {
            "id": "plan_adherence",
            "current": plan_adh,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": ">60%",
            "direction": "up_good",
            "confidence": _conf(total_plan),
        },
    ]
