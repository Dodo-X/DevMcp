"""
数据库迁移脚本 v9.6.1
修复 connected_systems 和 knowledge_points 表结构，使其与 database.py DDL 一致。

问题：
  1. connected_systems 表使用旧 schema（id + system_name + first_seen + notes），
     缺少 display_name, project_path, last_seen_at, metadata, project_description, first_connected
  2. knowledge_points 表残留 9 个废弃列：
     source_type, last_used_at, version, is_verified, metadata,
     created_by, updated_at, source_session_id, source_step_id
  3. knowledge_points 表缺少 category 字段
  4. 废弃索引：idx_knowledge_points_source, idx_kp_source_session

策略：SQLite 不支持 DROP COLUMN（旧版本），用重建表的方式迁移。
"""

import os
import shutil
import sqlite3
from datetime import datetime

DB_PATH = "data/databases/devpartner.db"


def migrate():
    # 备份
    backup_path = (
        f"data/databases/devpartner_backup_v961_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)
        print(f"[v9.6.1] 备份已创建: {backup_path}")
    else:
        print(f"[v9.6.1] 数据库文件不存在: {DB_PATH}，跳过迁移")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=OFF")  # 迁移期间关闭 FK 约束
    cursor = conn.cursor()

    # ============================================================
    # 1. connected_systems 表重建
    # ============================================================
    print("\n[v9.6.1] 检查 connected_systems 表...")
    cursor.execute("PRAGMA table_info(connected_systems)")
    old_cols = {row[1] for row in cursor.fetchall()}
    expected_cols = {
        "system_id",
        "system_type",
        "display_name",
        "project_path",
        "tech_stack",
        "architecture",
        "business_domains",
        "maturity",
        "first_connected",
        "last_active",
        "last_seen_at",
        "conversation_count",
        "metadata",
        "project_description",
    }

    if old_cols != expected_cols:
        print("  [MIGRATE] connected_systems schema 不匹配，重建中...")
        print(f"  旧列: {sorted(old_cols)}")
        print(f"  新列: {sorted(expected_cols)}")

        # 保存旧数据
        cursor.execute("SELECT * FROM connected_systems")
        old_rows = cursor.fetchall()
        old_col_names = [desc[0] for desc in cursor.description]

        # 删除旧表
        cursor.execute("DROP TABLE connected_systems")

        # 创建新表（与 DDL 一致）
        cursor.execute("""
            CREATE TABLE connected_systems (
                system_id TEXT PRIMARY KEY,
                system_type TEXT NOT NULL,
                display_name TEXT,
                project_path TEXT DEFAULT '',
                tech_stack JSON DEFAULT '[]',
                architecture JSON DEFAULT '{}',
                business_domains JSON DEFAULT '[]',
                maturity TEXT DEFAULT 'unknown',
                first_connected TEXT NOT NULL,
                last_active TEXT NOT NULL,
                last_seen_at TEXT DEFAULT '',
                conversation_count INTEGER DEFAULT 0,
                metadata JSON DEFAULT '{}',
                project_description TEXT DEFAULT ''
            )
        """)

        # 迁移数据
        migrated = 0
        for row in old_rows:
            old_data = dict(zip(old_col_names, row))

            system_id = old_data.get("system_id", "")
            if not system_id:
                continue

            # 映射：system_name → display_name
            display_name = old_data.get("system_name", "") or system_id
            # first_seen → first_connected（确保非空）
            now_iso = datetime.now().isoformat()
            first_connected = old_data.get("first_seen") or old_data.get("last_active") or now_iso
            last_active = old_data.get("last_active") or first_connected
            # 旧列映射到新列
            tech_stack = old_data.get("tech_stack", "[]")
            architecture = old_data.get("architecture", "{}")
            business_domains = old_data.get("business_domains", "[]")
            maturity = old_data.get("maturity", "unknown")
            conversation_count = old_data.get("conversation_count", 0)
            project_description = old_data.get("notes", "") or ""

            cursor.execute(
                """
                INSERT INTO connected_systems
                (system_id, system_type, display_name, project_path,
                 tech_stack, architecture, business_domains, maturity,
                 first_connected, last_active, last_seen_at,
                 conversation_count, metadata, project_description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    system_id,
                    old_data.get("system_type", "code_project"),
                    display_name,
                    old_data.get("project_path", ""),
                    tech_stack,
                    architecture,
                    business_domains,
                    maturity,
                    first_connected,
                    last_active,
                    old_data.get("last_seen_at", ""),
                    conversation_count,
                    old_data.get("metadata", "{}"),
                    project_description,
                ),
            )
            migrated += 1

        print(f"  [OK] connected_systems 重建完成，迁移 {migrated} 条记录")
    else:
        print("  [OK] connected_systems 已是最新 schema")

    # ============================================================
    # 2. knowledge_points 表重建（删除废弃列 + 补充 category）
    # ============================================================
    print("\n[v9.6.1] 检查 knowledge_points 表...")
    cursor.execute("PRAGMA table_info(knowledge_points)")
    old_cols = {row[1] for row in cursor.fetchall()}
    expected_cols = {
        "id",
        "knowledge_id",
        "title",
        "content",
        "category",
        "domain",
        "tags",
        "source_id",
        "confidence",
        "difficulty",
        "usage_count",
        "related_knowledge_ids",
        "created_at",
        "type",
        "aliases",
    }

    if old_cols != expected_cols:
        print("  [MIGRATE] knowledge_points schema 不匹配，重建中...")
        print(f"  旧列: {sorted(old_cols)}")
        print(f"  新列: {sorted(expected_cols)}")

        # 保存旧数据
        cursor.execute("SELECT * FROM knowledge_points")
        old_rows = cursor.fetchall()
        old_col_names = [desc[0] for desc in cursor.description]

        # 删除旧表
        cursor.execute("DROP TABLE knowledge_points")

        # 创建新表（与 DDL 一致）
        cursor.execute("""
            CREATE TABLE knowledge_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                domain TEXT NOT NULL,
                tags JSON DEFAULT '[]',
                source_id TEXT,
                confidence REAL DEFAULT 0.8,
                difficulty TEXT DEFAULT 'medium',
                usage_count INTEGER DEFAULT 0,
                related_knowledge_ids TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                type TEXT NOT NULL DEFAULT 'skill' CHECK(type IN ('skill','business')),
                aliases JSON DEFAULT '[]'
            )
        """)

        # 重建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_points_domain
            ON knowledge_points(domain)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_points_category
            ON knowledge_points(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_points_usage
            ON knowledge_points(usage_count DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_kp_type
            ON knowledge_points(type)
        """)

        # 迁移数据（category 从 domain 或 source_type 推导）
        migrated = 0
        for row in old_rows:
            old_data = dict(zip(old_col_names, row))

            knowledge_id = old_data.get("knowledge_id", "")
            if not knowledge_id:
                continue

            # category: 旧表没有，从 source_type 推导或默认 "step_extracted"
            category = old_data.get("source_type", "step_extracted") or "step_extracted"

            # source_id: 旧表使用 source_step_id，取最后一个非空的
            source_id = old_data.get("source_step_id", "") or old_data.get("source_id", "") or ""

            cursor.execute(
                """
                INSERT INTO knowledge_points
                (knowledge_id, title, content, category, domain,
                 tags, source_id, confidence, difficulty, usage_count,
                 related_knowledge_ids, created_at, type, aliases)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    knowledge_id,
                    old_data.get("title", ""),
                    old_data.get("content", ""),
                    category,
                    old_data.get("domain", ""),
                    old_data.get("tags", "[]"),
                    source_id,
                    old_data.get("confidence", 0.8),
                    old_data.get("difficulty", "medium"),
                    old_data.get("usage_count", 0),
                    old_data.get("related_knowledge_ids", ""),
                    old_data.get("created_at", datetime.now().isoformat()),
                    old_data.get("type", "skill"),
                    old_data.get("aliases", "[]"),
                ),
            )
            migrated += 1

        print(f"  [OK] knowledge_points 重建完成，迁移 {migrated} 条记录")
    else:
        print("  [OK] knowledge_points 已是最新 schema")

    # ============================================================
    # 3. user_profile: 确保 updated_at 有默认值
    # ============================================================
    print("\n[v9.6.1] 检查 user_profile 表...")
    cursor.execute("PRAGMA table_info(user_profile)")
    cols = {row[1]: row for row in cursor.fetchall()}
    if "updated_at" in cols:
        up_col = cols["updated_at"]
        if up_col[4] is None:  # dflt_value is None
            print("  [FIX] user_profile.updated_at 缺少 DEFAULT，重建...")
            # 重建 user_profile 表
            cursor.execute("SELECT * FROM user_profile")
            old_rows = cursor.fetchall()
            old_col_names = [desc[0] for desc in cursor.description]

            cursor.execute("DROP TABLE user_profile")
            cursor.execute("""
                CREATE TABLE user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dimension TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    evidence TEXT,
                    first_observed TEXT NOT NULL,
                    last_observed TEXT NOT NULL,
                    observation_count INTEGER DEFAULT 1,
                    trend TEXT DEFAULT 'stable',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(dimension)
                )
            """)

            for row in old_rows:
                old_data = dict(zip(old_col_names, row))
                cursor.execute(
                    """
                    INSERT INTO user_profile
                    (dimension, value, confidence, evidence,
                     first_observed, last_observed, observation_count,
                     trend, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        old_data["dimension"],
                        old_data["value"],
                        old_data.get("confidence", 0.5),
                        old_data.get("evidence", ""),
                        old_data.get("first_observed", ""),
                        old_data.get("last_observed", ""),
                        old_data.get("observation_count", 1),
                        old_data.get("trend", "stable"),
                        old_data.get("updated_at", datetime.now().isoformat()),
                    ),
                )
            print("  [OK] user_profile 重建完成")
        else:
            print("  [OK] user_profile 已是最新 schema")
    else:
        print("  [OK] user_profile 已是最新 schema")

    # ============================================================
    # 4. 清理废弃索引
    # ============================================================
    print("\n[v9.6.1] 清理废弃索引...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
    indexes = {row[0] for row in cursor.fetchall()}
    deprecated_idxs = {"idx_knowledge_points_source", "idx_kp_source_session"}
    for idx in deprecated_idxs:
        if idx in indexes:
            cursor.execute(f"DROP INDEX IF EXISTS {idx}")
            print(f"  [DROP] {idx}")

    # ============================================================
    # 5. 更新 schema 版本
    # ============================================================
    cursor.execute("""
        INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', '9.6.1', datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = '9.6.1', updated_at = datetime('now')
    """)

    conn.commit()
    conn.close()
    print("\n[v9.6.1] 迁移完成！")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    migrate()
