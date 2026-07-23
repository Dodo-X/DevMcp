"""
指标计算层（Metrics Layer）
==========================
消费 registry.py 的维度定义，对真实数据库执行可复现的 SQL/计算，
产出"当期值 / 环比值 / 变化% / 状态 / 置信度"的结构化指标。

设计要点：
  - 口径明确：所有计算直接对应 registry 中声明的 formula
  - 清洗前置：task_type / system_id / domain 先经归一映射再聚合
  - 置信度：依据样本量与数据完整性给出 high/medium/low
  - 可复现：纯 stdlib（sqlite3），不依赖 devPartner 运行时
"""

import sqlite3
import statistics
from datetime import date, datetime, timedelta

from .profiling import compute_psychology
from .registry import (
    DIMENSION_BY_ID,
    DOMAIN_NORMALIZATION,
    SYSTEM_ID_NORMALIZATION,
    TASK_TYPE_NORMALIZATION,
)


# ── 归一化工具 ──────────────────────────────────────────────
def norm_task_type(v):
    if not v:
        return "unknown"
    return TASK_TYPE_NORMALIZATION.get(str(v).strip().lower(), str(v).strip().lower())


def norm_system_id(v):
    if not v:
        return "unknown"
    return SYSTEM_ID_NORMALIZATION.get(str(v).strip(), str(v).strip())


def norm_domain(v):
    if not v:
        return "unknown"
    return DOMAIN_NORMALIZATION.get(str(v).strip(), str(v).strip())


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _ts_col(cur, table, *candidates):
    """返回表中存在的时间戳列名（兼容 schema 漂移：如 task_queue created_at→queued_at）。"""
    cur.execute(f"PRAGMA table_info({table})")
    cols = {r[1] for r in cur.fetchall()}
    for c in candidates:
        if c in cols:
            return c
    return candidates[-1]


def _pct(cur, prev):
    if prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 1)


def _confidence(n, caveat=False):
    if caveat:
        return "low"
    if n is None:
        return "low"
    if n >= 30:
        return "high"
    if n >= 10:
        return "medium"
    return "low"


def _status(value, baseline, direction, delta_pct=None):
    """对照 baseline 给出 ok/warn，并感知环比方向（大幅改善不误报预警）。"""
    try:
        base = float(
            str(baseline)
            .replace("%", "")
            .replace("<", "")
            .replace(">", "")
            .replace("=", "")
            .strip()
        )
    except Exception:
        return "ok"  # 非数值基准（如"上期""历史""递减"）按健康处理
    if value is None:
        return "warn"
    improved = delta_pct is not None and delta_pct <= -20
    if direction == "up_good":
        if value >= base:
            return "ok"
        return "warn"  # 低于基准即关注
    if direction == "down_good":
        if value <= base:
            return "ok"
        if improved:
            return "ok"  # 虽略超阈值但环比大幅改善，不误报
        return "warn"
    return "ok"  # balanced / 其他由人工判断


# ── 维度计算函数 ────────────────────────────────────────────
def _d1_engagement(cur, prev, start, end, prev_start, prev_end):
    def agg(s, e):
        cur_ = cur.execute(
            "SELECT COUNT(*), COUNT(DISTINCT date(timestamp)) FROM conversations "
            "WHERE date(timestamp) BETWEEN ? AND ?",
            (s, e),
        ).fetchone()
        return (cur_[0] or 0, cur_[1] or 0)

    c_total, c_days = agg(start, end)
    p_total, p_days = agg(prev_start, prev_end)
    per_day = round(c_total / c_days, 2) if c_days else 0
    p_per_day = round(p_total / p_days, 2) if p_days else 0
    return [
        {
            "id": "conv_total",
            "current": c_total,
            "previous": p_total,
            "delta_pct": _pct(c_total, p_total),
            "unit": "次",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(c_total),
        },
        {
            "id": "active_days",
            "current": c_days,
            "previous": p_days,
            "delta_pct": _pct(c_days, p_days),
            "unit": "天",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(c_days),
        },
        {
            "id": "conv_per_active_day",
            "current": per_day,
            "previous": p_per_day,
            "delta_pct": _pct(per_day, p_per_day),
            "unit": "次/天",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(c_days),
        },
    ]


def _d2_task_mix(cur, start, end, prev_start, prev_end):
    def dist(s, e):
        rows = cur.execute(
            "SELECT task_type, COUNT(*) FROM conversations WHERE date(timestamp) BETWEEN ? AND ? GROUP BY task_type",
            (s, e),
        ).fetchall()
        tot = sum(r[1] for r in rows) or 1
        norm = {}
        for t, n in rows:
            k = norm_task_type(t)
            norm[k] = norm.get(k, 0) + n
        return norm, tot

    c_norm, c_tot = dist(start, end)
    p_norm, p_tot = dist(prev_start, prev_end)
    debug_share = round(c_norm.get("debug", 0) / c_tot * 100, 1) if c_tot else 0
    p_debug = round(p_norm.get("debug", 0) / p_tot * 100, 1) if p_tot else 0
    # 高复杂度（complex 标记）
    c_hi = cur.execute(
        "SELECT COUNT(*) FROM conversations WHERE date(timestamp) BETWEEN ? AND ? AND complexity='complex'",
        (start, end),
    ).fetchone()[0]
    c_all = cur.execute(
        "SELECT COUNT(*) FROM conversations WHERE date(timestamp) BETWEEN ? AND ? AND complexity IS NOT NULL",
        (start, end),
    ).fetchone()[0]
    hi_share = round(c_hi / c_all * 100, 1) if c_all else 0
    # sub-mix detail for report
    mix_detail = {
        k: round(v / c_tot * 100, 1) for k, v in sorted(c_norm.items(), key=lambda x: -x[1])
    }
    return [
        {
            "id": "task_mix",
            "current": mix_detail,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "上期构成",
            "direction": "balanced",
            "confidence": _confidence(c_tot),
            "note": "归一后构成（见 detail）",
        },
        {
            "id": "debug_share",
            "current": debug_share,
            "previous": p_debug,
            "delta_pct": _pct(debug_share, p_debug),
            "unit": "%",
            "baseline": "<30%",
            "direction": "down_good",
            "confidence": _confidence(c_tot),
        },
        {
            "id": "complexity_high_share",
            "current": hi_share,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(c_all),
        },
    ]


def _d3_reliability(cur, start, end, prev_start, prev_end):
    def step_stats(s, e):
        rows = cur.execute(
            "SELECT status, COUNT(*) FROM conversation_steps "
            "WHERE date(created_at) BETWEEN ? AND ? GROUP BY status",
            (s, e),
        ).fetchall()
        d = dict(rows)
        completed = d.get("completed", 0)
        total = sum(d.values()) or 1
        dur = [
            r[0]
            for r in cur.execute(
                "SELECT duration_ms FROM conversation_steps WHERE date(created_at) BETWEEN ? AND ? AND duration_ms>0",
                (s, e),
            ).fetchall()
        ]
        retry = cur.execute(
            "SELECT COUNT(*) FROM conversation_steps WHERE date(created_at) BETWEEN ? AND ? AND retry_count>0",
            (s, e),
        ).fetchone()[0]
        return completed, total, _median(dur), round(retry / total * 100, 1) if total else 0, retry

    c_comp, c_tot, c_dur, c_retry, c_retry_n = step_stats(start, end)
    p_comp, p_tot, p_dur, p_retry, _ = step_stats(prev_start, prev_end)

    # task_queue：排除 duplicate_discarded（时间戳列兼容 created_at/queued_at）
    tq_ts = _ts_col(cur, "task_queue", "created_at", "queued_at")

    def task_stats(s, e):
        rows = cur.execute(
            f"SELECT status, COUNT(*) FROM task_queue WHERE date({tq_ts}) BETWEEN ? AND ? GROUP BY status",
            (s, e),
        ).fetchall()
        d = dict(rows)
        completed = d.get("completed", 0)
        effective = sum(v for k, v in d.items() if k != "duplicate_discarded") or 1
        # 真实错误：error_message 非空且不含 'duplicate'
        err = cur.execute(
            f"SELECT COUNT(*) FROM task_queue WHERE date({tq_ts}) BETWEEN ? AND ? "
            "AND error_message IS NOT NULL AND error_message!='' AND error_message NOT LIKE '%duplicate%'",
            (s, e),
        ).fetchone()[0]
        dead = d.get("dead", 0) + d.get("failed", 0)
        return completed, effective, round(err / effective * 100, 1) if effective else 0, dead

    tc_comp, tc_eff, tc_err, tc_dead = task_stats(start, end)
    ptc_comp, ptc_eff, ptc_err, _ = task_stats(prev_start, prev_end)

    return [
        {
            "id": "step_success_rate",
            "current": round(c_comp / c_tot * 100, 1) if c_tot else None,
            "previous": round(p_comp / p_tot * 100, 1) if p_tot else None,
            "delta_pct": _pct(
                c_comp / c_tot * 100 if c_tot else None, p_comp / p_tot * 100 if p_tot else None
            ),
            "unit": "%",
            "baseline": ">95%",
            "direction": "up_good",
            "confidence": _confidence(c_tot),
        },
        {
            "id": "task_success_rate",
            "current": round(tc_comp / tc_eff * 100, 1) if tc_eff else None,
            "previous": round(ptc_comp / ptc_eff * 100, 1) if ptc_eff else None,
            "delta_pct": _pct(
                tc_comp / tc_eff * 100 if tc_eff else None,
                ptc_comp / ptc_eff * 100 if ptc_eff else None,
            ),
            "unit": "%",
            "baseline": ">90%",
            "direction": "up_good",
            "confidence": _confidence(tc_eff),
            "note": "已排除 duplicate_discarded（197条去重，非失败）",
        },
        {
            "id": "real_error_rate",
            "current": tc_err,
            "previous": ptc_err,
            "delta_pct": _pct(tc_err, ptc_err),
            "unit": "%",
            "baseline": "<5%",
            "direction": "down_good",
            "confidence": _confidence(tc_eff),
        },
        {
            "id": "median_step_duration",
            "current": c_dur,
            "previous": p_dur,
            "delta_pct": _pct(c_dur, p_dur),
            "unit": "ms",
            "baseline": "上期",
            "direction": "down_good",
            "confidence": _confidence(len([1]) and c_tot),
        },
        {
            "id": "retry_rate",
            "current": c_retry,
            "previous": p_retry,
            "delta_pct": _pct(c_retry, p_retry),
            "unit": "%",
            "baseline": "<10%",
            "direction": "down_good",
            "confidence": _confidence(c_tot),
        },
    ]


def _d4_knowledge(cur, start, end, prev_start, prev_end):
    c_new = cur.execute(
        "SELECT COUNT(*) FROM knowledge_points WHERE date(created_at) BETWEEN ? AND ?", (start, end)
    ).fetchone()[0]
    p_new = cur.execute(
        "SELECT COUNT(*) FROM knowledge_points WHERE date(created_at) BETWEEN ? AND ?",
        (prev_start, prev_end),
    ).fetchone()[0]
    c_total = cur.execute(
        "SELECT COUNT(*) FROM knowledge_points WHERE date(created_at) <= ?", (end,)
    ).fetchone()[0]
    # 归一后领域覆盖
    rows = cur.execute(
        "SELECT domain FROM knowledge_points WHERE date(created_at) <= ?", (end,)
    ).fetchall()
    domains = {norm_domain(r[0]) for r in rows}
    avg_conf = cur.execute("SELECT AVG(confidence) FROM knowledge_points").fetchone()[0]
    reused = cur.execute("SELECT COUNT(*) FROM knowledge_points WHERE usage_count>0").fetchone()[0]
    total_kp = cur.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
    reuse_rate = round(reused / total_kp * 100, 1) if total_kp else 0
    return [
        {
            "id": "kp_new",
            "current": c_new,
            "previous": p_new,
            "delta_pct": _pct(c_new, p_new),
            "unit": "个",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(c_new),
        },
        {
            "id": "kp_total",
            "current": c_total,
            "previous": None,
            "delta_pct": None,
            "unit": "个",
            "baseline": "历史",
            "direction": "up_good",
            "confidence": _confidence(c_total),
        },
        {
            "id": "domain_coverage",
            "current": len(domains),
            "previous": None,
            "delta_pct": None,
            "unit": "个领域",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": "high",
            "note": "已按 DOMAIN_NORMALIZATION 合并同义词",
        },
        {
            "id": "avg_confidence",
            "current": round(avg_conf, 2) if avg_conf else None,
            "previous": None,
            "delta_pct": None,
            "unit": "",
            "baseline": ">0.8",
            "direction": "up_good",
            "confidence": "high",
        },
        {
            "id": "reuse_rate",
            "current": reuse_rate,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": ">10%",
            "direction": "up_good",
            "confidence": "low",
            "note": "埋点缺失：usage_count 全为 0，指标暂不可信，需补齐采集",
        },
    ]


def _d5_capability(cur):
    skill_n = cur.execute("SELECT COUNT(*) FROM user_skills").fetchone()[0]
    dom = cur.execute("SELECT COUNT(DISTINCT skill_domain) FROM user_skills").fetchone()[0]
    done = cur.execute("SELECT COUNT(*) FROM user_skill_plan WHERE status='done'").fetchone()[0]
    total_plan = cur.execute("SELECT COUNT(*) FROM user_skill_plan").fetchone()[0]
    up = cur.execute("SELECT COUNT(*) FROM user_skills WHERE growth_trend='up'").fetchone()[0]
    return [
        {
            "id": "skill_count",
            "current": skill_n,
            "previous": None,
            "delta_pct": None,
            "unit": "个",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(skill_n),
        },
        {
            "id": "domain_breadth",
            "current": dom,
            "previous": None,
            "delta_pct": None,
            "unit": "个领域",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": "high",
        },
        {
            "id": "plan_adherence",
            "current": round(done / total_plan * 100, 1) if total_plan else 0,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": ">60%",
            "direction": "up_good",
            "confidence": _confidence(total_plan),
        },
        {
            "id": "level_up_rate",
            "current": round(up / skill_n * 100, 1) if skill_n else 0,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(skill_n),
        },
    ]


def _d6_coverage(cur, start, end, prev_start, prev_end, now):
    conn_n = cur.execute("SELECT COUNT(*) FROM connected_systems").fetchone()[0]
    # 头部系统对话占比（按归一 system_id）
    rows = cur.execute(
        "SELECT system_id, COUNT(*) FROM conversations GROUP BY system_id"
    ).fetchall()
    norm = {}
    for s, n in rows:
        k = norm_system_id(s)
        norm[k] = norm.get(k, 0) + n
    top_share = round(max(norm.values()) / sum(norm.values()) * 100, 1) if norm else 0
    new_disc = cur.execute(
        "SELECT COUNT(*) FROM system_context_fragments WHERE date(observed_at) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]
    p_disc = cur.execute(
        "SELECT COUNT(*) FROM system_context_fragments WHERE date(observed_at) BETWEEN ? AND ?",
        (prev_start, prev_end),
    ).fetchone()[0]
    stale = cur.execute(
        "SELECT COUNT(*) FROM connected_systems WHERE last_active < ?",
        ((now - timedelta(days=30)).strftime("%Y-%m-%d"),),
    ).fetchone()[0]
    return [
        {
            "id": "connected_systems",
            "current": conn_n,
            "previous": None,
            "delta_pct": None,
            "unit": "个",
            "baseline": "历史",
            "direction": "up_good",
            "confidence": "high",
        },
        {
            "id": "conv_share_top",
            "current": top_share,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "均衡<60%",
            "direction": "balanced",
            "confidence": "high",
            "note": "已按 SYSTEM_ID_NORMALIZATION 合并大小写",
        },
        {
            "id": "new_discoveries",
            "current": new_disc,
            "previous": p_disc,
            "delta_pct": _pct(new_disc, p_disc),
            "unit": "条",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(new_disc),
        },
        {
            "id": "stale_systems",
            "current": stale,
            "previous": None,
            "delta_pct": None,
            "unit": "个",
            "baseline": "0",
            "direction": "down_good",
            "confidence": "high",
        },
    ]


def _d7_improvement(cur):
    il_applied = cur.execute(
        "SELECT COUNT(*) FROM improvement_log WHERE status='applied'"
    ).fetchone()[0]
    il_total = cur.execute("SELECT COUNT(*) FROM improvement_log").fetchone()[0]
    fb_applied = cur.execute(
        "SELECT COUNT(*) FROM optimization_feedback WHERE status='applied'"
    ).fetchone()[0]
    fb_total = cur.execute("SELECT COUNT(*) FROM optimization_feedback").fetchone()[0]
    backlog = cur.execute(
        "SELECT COUNT(*) FROM improvement_log WHERE status IN ('open','pending')"
    ).fetchone()[0]
    return [
        {
            "id": "il_applied_rate",
            "current": round(il_applied / il_total * 100, 1) if il_total else 0,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": ">40%",
            "direction": "up_good",
            "confidence": _confidence(il_total),
        },
        {
            "id": "fb_applied_rate",
            "current": round(fb_applied / fb_total * 100, 1) if fb_total else 0,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": ">40%",
            "direction": "up_good",
            "confidence": _confidence(fb_total),
        },
        {
            "id": "open_backlog",
            "current": backlog,
            "previous": None,
            "delta_pct": None,
            "unit": "条",
            "baseline": "递减",
            "direction": "down_good",
            "confidence": "high",
        },
        {
            "id": "avg_close_days",
            "current": None,
            "previous": None,
            "delta_pct": None,
            "unit": "天",
            "baseline": "<14天",
            "direction": "down_good",
            "confidence": "low",
            "note": "applied_at 多为空，闭环时效暂不可算",
        },
    ]


def _d8_efficiency(cur, start, end, prev_start, prev_end):
    def med(s, e):
        xs = [
            r[0]
            for r in cur.execute(
                "SELECT duration_ms FROM conversation_steps WHERE date(created_at) BETWEEN ? AND ? AND duration_ms>0",
                (s, e),
            ).fetchall()
        ]
        return _median(xs), len(xs)

    c_dur, c_n = med(start, end)
    p_dur, _ = med(prev_start, prev_end)
    tq_ts = _ts_col(cur, "task_queue", "created_at", "queued_at")
    completed = cur.execute(
        f"SELECT COUNT(*) FROM task_queue WHERE status='completed' AND date({tq_ts}) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]
    days = cur.execute(
        f"SELECT COUNT(DISTINCT date({tq_ts})) FROM task_queue WHERE date({tq_ts}) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]
    tp = round(completed / days, 1) if days else 0
    return [
        {
            "id": "median_duration",
            "current": c_dur,
            "previous": p_dur,
            "delta_pct": _pct(c_dur, p_dur),
            "unit": "ms",
            "baseline": "上期",
            "direction": "down_good",
            "confidence": _confidence(c_n),
        },
        {
            "id": "throughput_day",
            "current": tp,
            "previous": None,
            "delta_pct": None,
            "unit": "个/天",
            "baseline": "上期",
            "direction": "up_good",
            "confidence": _confidence(days),
        },
        {
            "id": "mem_accuracy",
            "current": None,
            "previous": None,
            "delta_pct": None,
            "unit": "%",
            "baseline": "<20%",
            "direction": "down_good",
            "confidence": "low",
            "note": "actual_memory_mb 多为空，需补齐采集",
        },
    ]


# ── 主入口 ──────────────────────────────────────────────────
def compute_metrics(db_path, start, end, prev_start, prev_end):
    """返回：{ dimension_id: {name, metrics:[...]} }，并附 period 信息。"""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    now = date.today()

    results = {}
    results["D1_engagement"] = {
        "name": "参与度与体量",
        "metrics": _d1_engagement(cur, prev_start, start, end, prev_start, prev_end),
    }
    results["D2_task_mix"] = {
        "name": "任务类型分布",
        "metrics": _d2_task_mix(cur, start, end, prev_start, prev_end),
    }
    results["D3_reliability"] = {
        "name": "执行与可靠性",
        "metrics": _d3_reliability(cur, start, end, prev_start, prev_end),
    }
    results["D4_knowledge"] = {
        "name": "知识沉淀",
        "metrics": _d4_knowledge(cur, start, end, prev_start, prev_end),
    }
    results["D5_capability"] = {"name": "用户能力成长", "metrics": _d5_capability(cur)}
    results["D6_coverage"] = {
        "name": "系统/项目覆盖",
        "metrics": _d6_coverage(cur, start, end, prev_start, prev_end, now),
    }
    results["D7_improvement_loop"] = {"name": "改进闭环", "metrics": _d7_improvement(cur)}
    results["D8_efficiency"] = {
        "name": "效率与成本",
        "metrics": _d8_efficiency(cur, start, end, prev_start, prev_end),
    }
    results["D9_user_psychology"] = {
        "name": "用户心理与画像",
        "metrics": compute_psychology(cur, start, end, prev_start, prev_end),
    }
    con.close()

    # 补 status
    for did, block in results.items():
        dim = DIMENSION_BY_ID.get(did, {})
        metric_meta = {m["id"]: m for m in dim.get("metrics", [])}
        for m in block["metrics"]:
            meta = metric_meta.get(m["id"], {})
            m["status"] = _status(
                m["current"],
                meta.get("baseline", ""),
                meta.get("direction", "up_good"),
                m.get("delta_pct"),
            )
    return results


def last_period_range(end_date: str, days: int):
    """给定结束日，返回 [start,end] 与 [prev_start,prev_end]（等长区间）。"""
    e = datetime.strptime(end_date, "%Y-%m-%d").date()
    s = e - timedelta(days=days - 1)
    pe = s - timedelta(days=1)
    ps = pe - timedelta(days=days - 1)
    return (
        s.strftime("%Y-%m-%d"),
        e.strftime("%Y-%m-%d"),
        ps.strftime("%Y-%m-%d"),
        pe.strftime("%Y-%m-%d"),
    )
