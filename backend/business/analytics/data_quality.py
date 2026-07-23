"""
数据质量门禁（Data Quality Gate）
================================
报告生成前的强制校验。未过门禁的指标必须降级标注，不可直接下结论。

校验维度：
  1. 枚举一致性 / 同义词归一（task_type、system_id、domain）
  2. 空值率（关键字段）
  3. 孤儿记录（步骤无归属对话）
  4. 埋点完整性（usage_count、actual_memory_mb 缺失）
  5. 新鲜度（数据是否停滞）
  6. 枚举合法性（status 字段取值）

输出：DQ 评分（0-100）+ 问题清单（severity / 影响行数 / 建议）
"""

import sqlite3
from datetime import date, datetime

from .metrics import norm_domain, norm_system_id, norm_task_type


def _count(cur, sql, *args):
    return cur.execute(sql, args).fetchone()[0]


def run_dq(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    issues = []
    penalties = 0  # 累计扣分（满分 100）

    def add(severity, table, check, affected, detail, fix):
        weight = {"high": 12, "medium": 6, "low": 2}[severity]
        nonlocal penalties
        penalties += min(weight, max(0, weight)) if affected > 0 else 0
        issues.append(
            {
                "severity": severity,
                "table": table,
                "check": check,
                "affected_rows": affected,
                "detail": detail,
                "fix": fix,
            }
        )

    # ── 1. task_type 未归一 ──
    rows = cur.execute(
        "SELECT task_type, COUNT(*) FROM conversations GROUP BY task_type"
    ).fetchall()
    unnorm = sum(n for t, n in rows if norm_task_type(t) != t)
    total = sum(n for _, n in rows) or 1
    add(
        "medium",
        "conversations",
        "task_type 同义词未归一",
        unnorm,
        f"{unnorm}/{total} 行使用非规范值（如 debugging/refactoring/code_change），导致任务类型分布指标失真",
        "写入时经 TASK_TYPE_NORMALIZATION 归一；历史数据跑一次性 UPDATE",
    )

    # ── 2. system_id 大小写 ──
    rows = cur.execute(
        "SELECT system_id, COUNT(*) FROM conversations GROUP BY system_id"
    ).fetchall()
    unnorm = sum(n for t, n in rows if norm_system_id(t) != t)
    add(
        "medium",
        "conversations",
        "system_id 大小写不一致",
        unnorm,
        f"{unnorm} 行 system_id 大小写不一致（devpartner vs devPartner），系统级指标会碎片化",
        "统一为 devPartner；写入层强制小写映射",
    )

    # ── 3. domain 同义词 ──
    rows = cur.execute("SELECT domain, COUNT(*) FROM knowledge_points GROUP BY domain").fetchall()
    unnorm = sum(n for t, n in rows if norm_domain(t) != t)
    total = sum(n for _, n in rows) or 1
    add(
        "medium",
        "knowledge_points",
        "domain 同义词未合并",
        unnorm,
        f"{unnorm}/{total} 行领域标签存在同义词（Python/Python编程/数据库/数据库管理…），领域覆盖指标不可信",
        "写入时经 DOMAIN_NORMALIZATION 合并；历史数据跑一次性 UPDATE",
    )

    # ── 4. 空值率 ──
    for col, tbl, max_null in [
        ("complexity", "conversations", 0.2),
        ("user_intent", "conversations", 0.2),
        ("self_reflection", "conversations", 0.3),
    ]:
        n = _count(cur, f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NULL OR {col}=''")
        tot = _count(cur, f"SELECT COUNT(*) FROM {tbl}")
        rate = n / tot if tot else 0
        sev = "medium" if rate > max_null else "low"
        add(
            sev,
            tbl,
            f"{col} 空值率",
            n,
            f"空值率 {rate:.0%}（阈值 {max_null:.0%}）",
            f"标注层对缺失 {col} 做 'unknown' 兜底，不影响计数但降低细分精度",
        )

    # ── 5. 孤儿步骤 ──
    orphan = _count(
        cur,
        "SELECT COUNT(*) FROM conversation_steps s "
        "LEFT JOIN conversations c ON s.conversation_id=c.conversation_id "
        "WHERE c.conversation_id IS NULL",
    )
    add(
        "high" if orphan > 0 else "low",
        "conversation_steps",
        "孤儿步骤（无归属对话）",
        orphan,
        f"{orphan} 个步骤的 conversation_id 在 conversations 中不存在，成功率分母失真",
        "步骤写入校验 conversation_id 存在；孤儿步骤标记隔离不参与成功率计算",
    )

    # ── 6. 埋点完整性：usage_count 全 0 ──
    zero = _count(cur, "SELECT COUNT(*) FROM knowledge_points WHERE usage_count=0")
    tot = _count(cur, "SELECT COUNT(*) FROM knowledge_points")
    if tot and zero == tot:
        add(
            "high",
            "knowledge_points",
            "知识复用埋点缺失",
            zero,
            "usage_count 全部为 0，'知识复用率'指标不可计算（关键闭环指标失明）",
            "在知识被检索/引用时 +1 usage_count；补齐前该指标置信度=low",
        )
    else:
        add(
            "low",
            "knowledge_points",
            "usage_count 部分缺失",
            zero,
            f"{zero}/{tot} 知识点复用计数为 0",
            "逐步补齐引用埋点",
        )

    # ── 7. 新鲜度 ──
    last = cur.execute("SELECT MAX(date(timestamp)) FROM conversations").fetchone()[0]
    if last:
        days_idle = (date.today() - datetime.strptime(last, "%Y-%m-%d").date()).days
        if days_idle > 14:
            add(
                "high",
                "conversations",
                "数据停滞（新鲜度）",
                days_idle,
                f"最近一次对话在 {last}，已停滞 {days_idle} 天，报告结论可能过时",
                "检查 MCP 连接与 record_dialogue 链路；超 14 天报告标注 '数据可能过时'",
            )
        elif days_idle > 7:
            add(
                "medium",
                "conversations",
                "数据新鲜度偏低",
                days_idle,
                f"最近对话 {last}，停滞 {days_idle} 天",
                "关注采集链路健康",
            )

    # ── 8. status 枚举合法性 ──
    valid_steps = {"completed", "orphaned", "failed", "pending", "running"}
    rows = cur.execute("SELECT status, COUNT(*) FROM conversation_steps GROUP BY status").fetchall()
    bad = sum(n for s, n in rows if s not in valid_steps)
    if bad:
        add(
            "medium",
            "conversation_steps",
            "status 枚举非法",
            bad,
            f"{bad} 行 status 不在合法集合 {valid_steps}",
            "写入层约束枚举；历史修正",
        )

    # ── 9. schema 漂移（DDL 与运行库不一致）──
    cur.execute("PRAGMA table_info(task_queue)")
    tq_cols = {r[1] for r in cur.fetchall()}
    if "created_at" not in tq_cols:
        add(
            "high",
            "task_queue",
            "schema 漂移（缺 created_at）",
            1,
            f"DDL 声明 task_queue.created_at，但运行库仅有 {sorted(tq_cols)[:6]}…；"
            f"可靠性/效率指标已自动回退到 queued_at，存在统计口径偏差",
            "对齐 DDL 与运行库（迁移脚本补齐 created_at），或统一以 queued_at 为权威时间戳",
        )

    score = max(0, 100 - penalties)
    con.close()
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    return {
        "score": score,
        "grade": grade,
        "issues": issues,
        "summary": f"DQ 评分 {score}/100（{grade}），发现 {len(issues)} 项问题，"
        f"其中 high={sum(1 for i in issues if i['severity'] == 'high')} 项需优先修复",
    }


def dq_brief(dq):
    """给报告用的简短 DQ 摘要。"""
    return dq["summary"]
