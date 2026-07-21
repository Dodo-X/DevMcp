"""
存量数据修复脚本：重新归类 user_skills 表的 skill_domain 字段

问题背景：
  user_skills 表有 UNIQUE INDEX on skill_domain，但历史数据中 skill_domain 存的是
  细粒度技能名（如"Ponytail 原则"、"Python调试"），导致41条记录对应41个不同的 domain。
  Dashboard 的领域分布图和技能雷达因此碎片化严重。

修复策略（合并模式）：
  1. 删除 UNIQUE INDEX idx_user_skills_unique
  2. 将细粒度技能名归类到标准领域（关键词匹配）
  3. 同领域的多条记录合并：保留 skill_level 最高的一条，合并 sub_skills
  4. 重建 UNIQUE INDEX

执行方式：
  python scripts/fix_skill_domains.py [--dry-run] [--force]
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# v9.3.1: 使用统一领域标准化模块（单一数据源）
from devpartner_agent.core.skill_domain_standard import (
    STANDARD_DOMAINS, STANDARD_DOMAINS_SET,
    normalize_domain, is_standard_domain,
)

LEVEL_ORDER = {"expert": 4, "advanced": 3, "intermediate": 2, "beginner": 1}


def classify_skill(skill_domain_value):
    """使用统一标准化函数（单一数据源）"""
    return normalize_domain(skill_domain_value)


def fix_skill_domains(dry_run=True, force=False):
    import sqlite3
    from pathlib import Path
    from devpartner_agent.core.config import get_config

    cfg = get_config()
    db_path = cfg.data.db_path if hasattr(cfg, 'data') and hasattr(cfg.data, 'db_path') else "data/databases/devpartner.db"
    db_path = str(Path(db_path))
    print(f"📂 数据库路径: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, skill_domain, skill_level, sub_skills, evidence, conversation_ids, "
        "hours_spent, growth_trend, last_updated, confidence, first_seen, last_seen, "
        "evidence_count, source_conversation_id, source_timestamp, extraction_method "
        "FROM user_skills ORDER BY skill_domain"
    )
    all_skills = [dict(row) for row in cursor.fetchall()]

    if not all_skills:
        print("📭 user_skills 表为空，无需修复")
        conn.close()
        return

    print(f"📊 当前共 {len(all_skills)} 条技能记录\n")

    # 统计当前状态
    domain_stats = {}
    for row in all_skills:
        dom = row["skill_domain"] or "其他"
        domain_stats[dom] = domain_stats.get(dom, 0) + 1

    print("【当前 skill_domain 分布 (前 20)】")
    for dom, cnt in sorted(domain_stats.items(), key=lambda x: -x[1])[:20]:
        tag = "✅" if dom in STANDARD_DOMAINS_SET else "⚠️"
        print(f"  {tag} {dom}: {cnt} 条")

    # 按标准领域分组
    groups = {}
    for row in all_skills:
        current = row["skill_domain"] or "其他"
        new_domain = classify_skill(current) if (current not in STANDARD_DOMAINS_SET or force) else current
        if new_domain not in groups:
            groups[new_domain] = []
        groups[new_domain].append(row)

    print(f"\n【修复后领域分组】")
    for dom in sorted(groups.keys()):
        rows = groups[dom]
        skills = [r["skill_domain"] for r in rows]
        print(f"  ✅ {dom}: {len(rows)} 条 → {skills}")

    # 检查哪些领域有重复需要合并
    needs_merge = {k: v for k, v in groups.items() if len(v) > 1}
    needs_update = {k: v for k, v in groups.items() if len(v) == 1 and v[0]["skill_domain"] != k}

    total_merge = sum(len(v) for v in needs_merge.values())
    total_update = len(needs_update)
    deleted = total_merge - len(needs_merge)  # 合并后删除的条数

    print(f"\n📋 修复计划:")
    print(f"  需要合并的领域: {len(needs_merge)} 个 (共 {total_merge} 条 → {len(needs_merge)} 条, 删除 {deleted} 条)")
    for dom, rows in sorted(needs_merge.items()):
        skills = [r["skill_domain"] for r in rows]
        print(f"    - {dom}: {skills}")
    print(f"  需要重命名的领域: {len(needs_update)} 条")
    for dom, rows in sorted(needs_update.items()):
        for r in rows:
            print(f"    - {r['skill_domain']} → {dom}")

    if dry_run:
        print(f"\n🧪 预览模式，未实际修改。使用 --force 执行写入。")
        conn.close()
        return

    # 执行修复
    print(f"\n🔧 开始修复...")

    # 1. 删除 UNIQUE INDEX
    print("  [1/3] 删除 UNIQUE INDEX...")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_user_skills_unique")
        conn.commit()
        print("  ✅ 索引已删除")
    except Exception as e:
        print(f"  ⚠️ 删除索引失败: {e}")

    # 2. 处理需要重命名的（单个记录，直接 UPDATE）
    print("  [2/3] 重命名单条记录...")
    renamed = 0
    for domain, rows in needs_update.items():
        for row in rows:
            old_name = row["skill_domain"]
            conn.execute("UPDATE user_skills SET skill_domain = ? WHERE id = ?", (domain, row["id"]))
            renamed += 1
            print(f"    {old_name} → {domain}")
    conn.commit()
    print(f"  ✅ 重命名完成: {renamed} 条")

    # 3. 处理需要合并的（保留 skill_level 最高的，合并 sub_skills 和 evidence）
    print("  [3/3] 合并同领域重复记录...")
    merged = 0
    deleted = 0
    for domain, rows in sorted(needs_merge.items()):
        # 按 skill_level 排序，保留最高的一条
        rows_sorted = sorted(rows, key=lambda r: LEVEL_ORDER.get(r["skill_level"] or "beginner", 1), reverse=True)
        keeper = rows_sorted[0]
        duplicates = rows_sorted[1:]

        # 合并 sub_skills
        all_subs = set()
        for r in rows_sorted:
            subs = (r.get("sub_skills") or "").strip()
            if subs:
                for s in subs.split(","):
                    s = s.strip()
                    if s and s not in STANDARD_DOMAINS_SET:
                        all_subs.add(s)

        # 把旧 skill_domain 也加入 sub_skills
        for r in rows_sorted:
            old_name = r["skill_domain"]
            if old_name and old_name not in STANDARD_DOMAINS_SET and old_name != domain:
                all_subs.add(old_name)

        merged_subs = ", ".join(sorted(all_subs))

        # 合并 evidence
        all_evidence = []
        for r in rows_sorted:
            ev = (r.get("evidence") or "").strip()
            if ev and ev not in all_evidence:
                all_evidence.append(ev)
        merged_evidence = "; ".join(all_evidence)

        # 合并 conversation_ids
        all_conv_ids = set()
        for r in rows_sorted:
            cids = (r.get("conversation_ids") or "").strip()
            if cids:
                for c in cids.split(","):
                    c = c.strip()
                    if c:
                        all_conv_ids.add(c)
        merged_conv_ids = ", ".join(sorted(all_conv_ids))

        # 合并 hours_spent
        total_hours = sum(r.get("hours_spent") or 0 for r in rows_sorted)

        # 合并 evidence_count
        total_evidence = sum(r.get("evidence_count") or 0 for r in rows_sorted)

        # 更新 keeper
        conn.execute(
            "UPDATE user_skills SET skill_domain = ?, sub_skills = ?, evidence = ?, "
            "conversation_ids = ?, hours_spent = ?, evidence_count = ?, "
            "last_updated = datetime('now') "
            "WHERE id = ?",
            (domain, merged_subs, merged_evidence, merged_conv_ids, total_hours, total_evidence, keeper["id"])
        )

        # 删除重复记录
        for dup in duplicates:
            conn.execute("DELETE FROM user_skills WHERE id = ?", (dup["id"],))

        merged += 1
        deleted += len(duplicates)
        skills_list = [r["skill_domain"] for r in rows_sorted]
        print(f"    {domain}: {skills_list} → 合并为 1 条 (保留 ID:{keeper['id']}, 删除 {len(duplicates)} 条)")

    conn.commit()
    print(f"  ✅ 合并完成: {merged} 个领域合并, {deleted} 条记录删除")

    # 4. 重建 UNIQUE INDEX
    print("  [4/4] 重建 UNIQUE INDEX...")
    try:
        conn.execute("CREATE UNIQUE INDEX idx_user_skills_unique ON user_skills(skill_domain)")
        conn.commit()
        print("  ✅ 索引已重建")
    except Exception as e:
        print(f"  ⚠️ 重建索引失败: {e}")

    # 修复后统计
    cursor2 = conn.cursor()
    cursor2.execute(
        "SELECT skill_domain, COUNT(*) as cnt, "
        "GROUP_CONCAT(sub_skills, ' | ') as all_subs "
        "FROM user_skills GROUP BY skill_domain ORDER BY cnt DESC"
    )
    print("\n【修复后领域分布】")
    total = 0
    for row in cursor2.fetchall():
        dom = row["skill_domain"] or "其他"
        cnt = row["cnt"]
        total += cnt
        subs = (row["all_subs"] or "")[:80]
        tag = "✅" if dom in STANDARD_DOMAINS_SET else "⚠️"
        print(f"  {tag} {dom}: {cnt} 条 | {subs}...")

    print(f"\n📊 总计: {total} 条记录 (修复前: {len(all_skills)} 条)")
    conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "--preview" in sys.argv
    force = "--force" in sys.argv

    print("=" * 60)
    print("  DevPartner 技能领域存量数据修复 (合并模式)")
    print(f"  模式: {'预览 (dry-run)' if dry_run else '执行写入'}")
    print("=" * 60)

    try:
        fix_skill_domains(dry_run=dry_run, force=force)
    except Exception as e:
        print(f"\n❌ 脚本执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
