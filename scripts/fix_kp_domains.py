"""
修复 knowledge_points 表的 domain 字段（v9.3.1）

问题：knowledge_points 表中有非标准 domain（如 "Prompt Engineering", "框架/协议",
     "系统设计", "知识管理", "系统架构"），以及大量 "General" fallback。

修复策略：
1. 非标准 domain → 通过 normalize_domain() 标准化
2. "General" 的 skill 类型 → 通过 title 关键词推断标准化 domain
3. 业务类型（type=business）的 domain 保持不变

注意：knowledge_points 表可能没有 type 列（v7.4 迁移未执行），
     此时所有记录视为 skill 类型处理。
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.skill_domain_standard import (
    is_standard_domain,
    normalize_domain,
)


def fix_kp_domains(dry_run=True):
    db_path = "data/databases/devpartner.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 检查是否有 type 列
    has_type = False
    for row in conn.execute("PRAGMA table_info(knowledge_points)"):
        if row[1] == "type":
            has_type = True
            break

    # 查询所有知识点
    rows = conn.execute(
        "SELECT id, knowledge_id, title, domain FROM knowledge_points ORDER BY id"
    ).fetchall()

    total = len(rows)
    to_fix = []

    for row in rows:
        domain = row["domain"] or "General"
        if is_standard_domain(domain):
            continue  # 已经是标准领域，跳过

        # 尝试从 title 推断标准化 domain
        title = row["title"] or ""
        new_domain = normalize_domain(title)

        # 如果 title 推断不出来，用 domain 本身推断
        if new_domain == "通用工程" and domain != "General":
            new_domain = normalize_domain(domain)

        to_fix.append(
            {
                "id": row["id"],
                "knowledge_id": row["knowledge_id"],
                "title": title[:60],
                "old_domain": domain,
                "new_domain": new_domain,
            }
        )

    print(f"📊 knowledge_points 共 {total} 条")
    print(f"🔧 需要修复: {len(to_fix)} 条\n")

    if not to_fix:
        print("✅ 所有 domain 已标准化，无需修复")
        conn.close()
        return

    for item in to_fix:
        print(f"  {item['old_domain']:25s} → {item['new_domain']:10s} | {item['title']}")

    if dry_run:
        print("\n🧪 预览模式。使用 --force 执行写入。")
        conn.close()
        return

    # 执行修复
    print("\n🔧 开始修复...")
    fixed = 0
    for item in to_fix:
        conn.execute(
            "UPDATE knowledge_points SET domain = ? WHERE id = ?", (item["new_domain"], item["id"])
        )
        fixed += 1

    conn.commit()
    print(f"✅ 修复完成: {fixed} 条\n")

    # 修复后统计
    stats = conn.execute(
        "SELECT domain, COUNT(*) as cnt FROM knowledge_points GROUP BY domain ORDER BY cnt DESC"
    ).fetchall()
    print("【修复后 domain 分布】")
    for row in stats:
        dom = row["domain"] or "?"
        tag = "✅" if is_standard_domain(dom) else "⚠️"
        print(f"  {tag} {dom:20s}: {row['cnt']} 条")

    conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" not in sys.argv or "--force" not in sys.argv
    force = "--force" in sys.argv
    dry_run = not force

    print("=" * 60)
    print("  DevPartner knowledge_points domain 修复")
    print(f"  模式: {'预览 (dry-run)' if dry_run else '执行写入'}")
    print("=" * 60)

    try:
        fix_kp_domains(dry_run=dry_run)
    except Exception as e:
        print(f"\n❌ 脚本执行失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
