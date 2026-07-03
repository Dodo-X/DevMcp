#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
传统升级模块（硬编码逻辑回退方案）
==================================
当 LLM 服务不可用时，使用此模块执行数据库升级。
保留原有逻辑以确保系统可用性。

注意：此模块仅作为 LLM 驱动模式的降级方案，
建议优先使用 upgrade_to_v5.py 的 LLM 模式。
"""
import sqlite3


def check_table_columns(conn, table_name: str) -> list:
    """获取表的所有列名"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def add_missing_columns(conn):
    """添加 v4.3+ 缺失的列（如果存在）- 硬编码版本"""
    cursor = conn.cursor()

    conv_cols = check_table_columns(conn, "conversations")

    missing_columns = {
        "conversations": [
            ("analyzed", "INTEGER DEFAULT 0"),
            ("status", "TEXT DEFAULT 'active'"),
            ("priority", "TEXT DEFAULT 'medium'"),
            ("total_steps", "INTEGER DEFAULT 0"),
            ("completed_steps", "INTEGER DEFAULT 0"),
            ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
            ("completed_at", "TEXT"),
        ],
        "conversation_archive": [
            ("conversations_id", "INTEGER"),
            ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ],
        "optimization_feedback": [
            ("conversations_id", "INTEGER"),
            ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ],
        "evolution_log": [
            ("conversations_id", "INTEGER"),
            ("success", "INTEGER DEFAULT 1"),
            ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ],
        "improvement_log": [
            ("conversations_id", "INTEGER"),
            ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ],
    }

    total_added = 0

    for table, columns in missing_columns.items():
        current_cols = check_table_columns(conn, table)

        for col_name, col_def in columns:
            if col_name not in current_cols:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    print(f"  ➕ 添加列: {table}.{col_name}")
                    total_added += 1
                except sqlite3.OperationalError as e:
                    print(f"  ⚠️ 添加 {table}.{col_name} 失败: {e}")

    if total_added > 0:
        conn.commit()
        print(f"\n✅ 成功添加 {total_added} 个缺失列\n")
    else:
        print("✅ 所有必需列已存在\n")

    return total_added


def execute_v50_upgrade(conn):
    """执行 v5.0 Schema 升级 - 硬编码版本"""
    print("🚀 开始执行 v5.0 Schema 升级...")

    script_path = "scripts/v5.0_schema_upgrade.sql"
    if not os.path.exists(script_path):
        print(f"❌ 升级脚本不存在: {script_path}")
        return False

    with open(script_path, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    try:
        cursor = conn.cursor()

        statements = []
        current_stmt = []
        for line in sql_script.split('\n'):
            stripped = line.strip()
            if stripped.startswith('--') or stripped == '':
                continue
            current_stmt.append(line)
            if stripped.endswith(';'):
                stmt = '\n'.join(current_stmt).strip()
                if stmt:
                    statements.append(stmt)
                current_stmt = []

        executed = 0
        for stmt in statements:
            try:
                cursor.execute(stmt)
                executed += 1
            except sqlite3.OperationalError as e:
                if "already exists" in str(e) or "duplicate column" in str(e):
                    pass
                else:
                    print(f"  ⚠️ 执行语句时出错: {e}")

        conn.commit()
        print(f"✅ v5.0 Schema 升级成功！共执行 {executed} 条 SQL 语句\n")
        return True

    except Exception as e:
        print(f"❌ v5.0 Schema 升级失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_upgrade(conn):
    """验证升级结果 - 硬编码版本"""
    print("🔍 验证升级结果...")

    cursor = conn.cursor()

    new_tables = ["conversation_steps", "knowledge_points", "task_queue"]
    existing_tables = []

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    all_tables = [row[0] for row in cursor.fetchall()]

    for table in new_tables:
        if table in all_tables:
            existing_tables.append(table)
            print(f"  ✅ 表 {table} 已创建")
        else:
            print(f"  ❌ 表 {table} 缺失！")

    cursor.execute("SELECT sql FROM sqlite_master WHERE name='conversations'")
    conv_row = cursor.fetchone()
    conv_sql = conv_row[0] if conv_row else ""

    if "UNIQUE" in conv_sql and "conversation_id" in conv_sql:
        print("  ✅ conversation_id 唯一约束已设置")
    else:
        print("  ⚠️ conversation_id 唯一约束可能未生效（SQLite限制）")

    for table in ["conversations", "conversation_steps", "knowledge_points", "task_queue"]:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  📊 {table}: {count} 条记录")
        except:
            pass

    print("\n" + "="*60)
    if len(existing_tables) == len(new_tables):
        print("🎉 升级验证通过！所有新表已成功创建。")
        return True
    else:
        print("⚠️ 升级可能未完全成功，请检查日志。")
        return False