#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速检查 v5.0 升级状态"""
import sqlite3
import os

DB_PATH = "data/databases/devpartner.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("="*60)
print("🔍 DevPartner v5.0 升级状态检查")
print("="*60)

# 检查新表
new_tables = ["conversation_steps", "knowledge_points", "task_queue"]
print("\n📦 核心新表:")
for table in new_tables:
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if cursor.fetchone():
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  ✅ {table} ({count} 条记录)")
    else:
        print(f"  ❌ {table} (缺失！)")

# 检查 conversations 表结构
print("\n📋 conversations 表字段:")
cursor.execute("PRAGMA table_info(conversations)")
columns = [row[1] for row in cursor.fetchall()]
important_cols = ["conversation_id", "status", "priority", "total_steps", "completed_steps"]
for col in important_cols:
    if col in columns:
        print(f"  ✅ {col}")
    else:
        print(f"  ❌ {col} (缺失！)")

# 统计数据
print("\n📊 数据统计:")
try:
    cursor.execute("SELECT COUNT(*) FROM conversations")
    print(f"  对话总数: {cursor.fetchone()[0]}")
except: pass

try:
    cursor.execute("SELECT COUNT(*) FROM conversation_steps")
    print(f"  步骤总数: {cursor.fetchone()[0]}")
except: pass

try:
    cursor.execute("SELECT COUNT(*) FROM knowledge_points")
    print(f"  知识点数: {cursor.fetchone()[0]}")
except: pass

try:
    cursor.execute("SELECT COUNT(*) FROM task_queue")
    print(f"  任务队列: {cursor.fetchone()[0]}")
except: pass

conn.close()
print("\n" + "="*60)
print("✅ 检查完成！")