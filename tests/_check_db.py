import sqlite3
import os

db_path = "data/databases/devpartner.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = sorted([r[0] for r in cur.fetchall()])

print("=" * 60)
print("数据库表概况")
print("=" * 60)

for t in tables:
    cur.execute("SELECT COUNT(*) FROM {}".format(t))
    count = cur.fetchone()[0]
    # 采样前3条数据
    cur.execute("SELECT * FROM {} LIMIT 3".format(t))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print("")
    print("--- {} ({} 行) ---".format(t, count))
    print("  列: {}".format(", ".join(cols)))
    if rows:
        print("  样例数据:")
        for row in rows:
            print("    {}".format(dict(zip(cols, row))))

conn.close()