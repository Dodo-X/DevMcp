"""
devPartner 数据库模块
- 本地 SQLite 数据库管理
- 共享数据库连接
- 表结构自动初始化
"""
import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Optional


class Database:
    """线程安全的 SQLite 数据库管理器"""

    _instance: Optional["Database"] = None
    _local_lock = threading.Lock()
    _shared_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._local_conn: Optional[sqlite3.Connection] = None
        self._shared_conn: Optional[sqlite3.Connection] = None
        self._initialized = True

    def init_local(self, db_path: str, use_wal: bool = True):
        """初始化本地数据库（可选WAL模式，适合云盘同步场景）"""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._local_lock:
            self._local_conn = sqlite3.connect(db_path, check_same_thread=False)
            self._local_conn.row_factory = sqlite3.Row

            if use_wal:
                # WAL 模式：.db-wal/.db-shm 是临时的，云盘不冲突
                self._local_conn.execute("PRAGMA journal_mode=WAL")
                self._local_conn.execute("PRAGMA synchronous=NORMAL")
                self._local_conn.execute("PRAGMA wal_autocheckpoint=1000")

            self._create_local_tables()

    def init_shared(self, db_path: str):
        """初始化共享数据库连接"""
        try:
            with self._shared_lock:
                self._shared_conn = sqlite3.connect(db_path, check_same_thread=False)
                self._shared_conn.row_factory = sqlite3.Row
        except Exception:
            self._shared_conn = None

    def _create_local_tables(self):
        """创建本地数据库表"""
        cursor = self._local_conn.cursor()

        # 对话日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                client TEXT DEFAULT 'unknown',
                topic TEXT,
                task_type TEXT,
                user_intent TEXT,
                actions TEXT,
                problems TEXT,
                solutions TEXT,
                decisions TEXT,
                files_touched TEXT,
                thinking_steps TEXT,
                self_reflection TEXT,
                raw_json TEXT
            )
        """)

        # 规则执行记录
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rule_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                trigger_reason TEXT,
                result TEXT,
                applied_changes TEXT
            )
        """)

        # 自我进化记录
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evolution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                version_from TEXT,
                version_to TEXT,
                change_type TEXT,
                description TEXT,
                files_changed TEXT,
                success INTEGER DEFAULT 1
            )
        """)

        # MCP 服务发现记录
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_discovery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                server_name TEXT UNIQUE,
                npm_package TEXT,
                description TEXT,
                tools_count INTEGER,
                status TEXT DEFAULT 'discovered',
                last_check TEXT
            )
        """)

        # 知识图谱
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_graph (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                entity_type TEXT,
                entity_name TEXT,
                relation TEXT,
                target_entity TEXT,
                metadata TEXT
            )
        """)

        # 思维导图历史
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mindmaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                title TEXT,
                topic TEXT,
                format TEXT DEFAULT 'mermaid',
                content TEXT,
                file_path TEXT
            )
        """)

        # 系统改进建议
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_improvements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT,
                suggestion TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                applied_at TEXT,
                result TEXT
            )
        """)

        # 迁移：为已有数据库添加 client 列
        try:
            cursor.execute("ALTER TABLE conversations ADD COLUMN client TEXT DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass  # 列已存在

        self._local_conn.commit()

    def query_local(self, sql: str, params: tuple = ()) -> list[dict]:
        """执行本地数据库查询"""
        if not self._local_conn:
            raise RuntimeError("本地数据库未初始化")
        with self._local_lock:
            cursor = self._local_conn.cursor()
            cursor.execute(sql, params)
            if sql.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cursor.fetchall()]
            self._local_conn.commit()
            return [{"affected_rows": cursor.rowcount, "last_id": cursor.lastrowid}]

    def query_shared(self, sql: str, params: tuple = ()) -> list[dict]:
        """执行共享数据库查询"""
        if not self._shared_conn:
            raise RuntimeError("共享数据库未连接")
        with self._shared_lock:
            cursor = self._shared_conn.cursor()
            cursor.execute(sql, params)
            if sql.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cursor.fetchall()]
            self._shared_conn.commit()
            return [{"affected_rows": cursor.rowcount}]

    def insert_conversation(self, data: dict):
        """插入对话记录（本地DB）"""
        # 获取当前客户端
        client = data.get("client") or data.get("agent", "unknown")

        sql = """
            INSERT INTO conversations
            (timestamp, client, topic, task_type, user_intent, actions, problems,
             solutions, decisions, files_touched, thinking_steps, self_reflection, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            data.get("timestamp", datetime.now().isoformat()),
            client,
            data.get("topic", ""),
            data.get("task_type", ""),
            data.get("user_intent", ""),
            data.get("actions", ""),
            data.get("problems", ""),
            data.get("solutions", ""),
            data.get("decisions", ""),
            json.dumps(data.get("files_touched", []), ensure_ascii=False),
            json.dumps(data.get("thinking_steps", []), ensure_ascii=False),
            data.get("self_reflection", ""),
            json.dumps(data, ensure_ascii=False),
        )
        return self.query_local(sql, params)

    def insert_improvement(self, category: str, suggestion: str, priority: str = "medium"):
        """插入系统改进建议"""
        sql = """
            INSERT INTO system_improvements (timestamp, category, suggestion, priority)
            VALUES (?, ?, ?, ?)
        """
        return self.query_local(sql, (datetime.now().isoformat(), category, suggestion, priority))

    def get_pending_improvements(self) -> list[dict]:
        """获取待处理的改进建议"""
        return self.query_local(
            "SELECT * FROM system_improvements WHERE status='pending' ORDER BY priority DESC, timestamp ASC"
        )

    def get_daily_stats(self, date_str: str = None) -> dict:
        """获取每日统计"""
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        sql = """
            SELECT task_type, COUNT(*) as cnt
            FROM conversations
            WHERE date(timestamp) = ?
            GROUP BY task_type
        """
        rows = self.query_local(sql, (date_str,))
        total_sql = "SELECT COUNT(*) as total FROM conversations WHERE date(timestamp) = ?"
        total = self.query_local(total_sql, (date_str,))
        return {
            "date": date_str,
            "total": total[0]["total"] if total else 0,
            "by_type": {row["task_type"]: row["cnt"] for row in rows},
        }

    def close(self):
        """关闭所有数据库连接"""
        if self._local_conn:
            self._local_conn.close()
        if self._shared_conn:
            self._shared_conn.close()


# 全局便捷访问
def get_db() -> Database:
    return Database()
