"""
DDL 导出脚本 — 从 database.py 提取 CREATE TABLE 语句生成独立的 schema.sql

用法: python scripts/export_ddl.py
输出: data/schema.sql
"""

import os
import re

DB_PY = os.path.join(os.path.dirname(__file__), "..", "backend", "core", "database", "base_conn.py")
OUT_SQL = os.path.join(os.path.dirname(__file__), "..", "data", "schema.sql")

with open(DB_PY, encoding="utf-8") as f:
    content = f.read()

# 提取所有 CREATE TABLE 语句
tables = re.findall(r"(CREATE TABLE IF NOT EXISTS \w+.*?;)", content, re.DOTALL)

# 提取所有 CREATE INDEX 语句
indexes = re.findall(r"(CREATE INDEX IF NOT EXISTS \w+.*?;)", content, re.DOTALL)

header = """-- DevPartner Schema DDL (auto-generated from database.py)
-- 生成时间: {timestamp}
-- 注意: 此文件仅作参考，实际建表由 database.py 的 _create_local_tables() 执行

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

""".format(timestamp=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

with open(OUT_SQL, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n-- ════════════════════════════════════════\n")
    f.write("-- Tables\n")
    f.write("-- ════════════════════════════════════════\n\n")
    for t in tables:
        # 清理多余的空白
        cleaned = re.sub(r"\n\s*\n", "\n", t)
        f.write(cleaned + "\n\n")

    if indexes:
        f.write("-- ════════════════════════════════════════\n")
        f.write("-- Indexes\n")
        f.write("-- ════════════════════════════════════════\n\n")
        for idx in indexes:
            cleaned = re.sub(r"\n\s*\n", "\n", idx)
            f.write(cleaned + "\n\n")

print(f"Schema exported: {OUT_SQL}")
print(f"Tables: {len(tables)}, Indexes: {len(indexes)}")
