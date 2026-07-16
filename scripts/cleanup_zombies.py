"""Cleanup zombie tasks that have been running for >10 minutes."""
import sqlite3, datetime, sys, os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'databases', 'devpartner.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
now_dt = datetime.datetime.now()

rows = conn.execute("SELECT task_id, task_type, status, started_at FROM task_queue WHERE status='running'").fetchall()
cleaned = 0
for r in rows:
    started_at = r['started_at']
    if started_at:
        started = datetime.datetime.fromisoformat(started_at)
        age_s = (now_dt - started).total_seconds()
        if age_s > 600:  # 10 minutes
            conn.execute(
                "UPDATE task_queue SET status='timeout', error_message=?, completed_at=? WHERE task_id=?",
                (f"Zombie cleanup after {age_s/3600:.1f}h", now_dt.isoformat(), r['task_id'])
            )
            cleaned += 1
            sys.stdout.write(f"[CLEAN] {r['task_id'][:20]}... {r['task_type']} age={age_s/3600:.1f}h\n")

conn.commit()
sys.stdout.write(f"Cleaned: {cleaned} zombie tasks\n")
conn.close()
