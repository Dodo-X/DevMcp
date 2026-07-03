"""
devPartner 数据库模块 v5.0
===========================
v5.0 变更：
  - ★ 新增 conversation_steps 表（步骤化异步处理）
  - ★ 新增 knowledge_points 表（技能知识点有序落地）
  - ★ 新增 task_queue 表（异步任务优先级调度）
  - ★ conversations 表新增 status/priority/total_steps/completed_steps/created_at/updated_at/completed_at 列
  - ★ 自动创建三张新表 + 补全缺失列，无需外部 SQL 脚本

v4.3 变更：
  - ★ FK 外键约束：conversation_archive / optimization_feedback / evolution_log /
    improvement_log 增加 FOREIGN KEY(conversations_id) REFERENCES conversations(id)
  - ★ conversations 表新增 analyzed 列（标记是否完成用户画像分析）
  - ★ 数据完整性保障：insert 后校验关键字段非空 + 日志埋点记录写入成功率
  - ★ 存量回填：_backfill_conversations_id() 补全历史数据外键关联
  - ★ 应用层 FK 校验：validate_conversation_integrity() 检查关联完整性
  - JSON 字段类型优化：TEXT → JSON 类型（v4.3 部分）
  - 存量表自动迁移：_migrate_text_to_json() + _migrate_add_foreign_keys()

v4.2 变更：
  - evolution_log / improvement_log 新增 conversations_id 外键
  - version_history 扩充 diff_detail/optimize_point/bug_fix/new_feature/data_change 五字段
  - get_conversation_with_relations 补充 evolution_log / improvement_log 联查
  - insert_improvement / log_evolution 支持 conversations_id 参数
  - 存量表 ALTER TABLE 自动迁移

v3.0 重构：
  - 删除死表：rule_executions / knowledge_graph / mindmaps
  - 重命名：system_improvements → improvement_log
  - 重命名：skill_profile → user_skills
  - 重命名：mcp_discovery → mcp_tool_registry
  - 新增：version_history（版本变更记录）
  - 新增：user_skill_plan（技能规划与目标）
  - 新增：mcp_tool_registry（MCP工具注册表）
  - 旧表自动迁移，数据不丢失
"""
import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Optional


class Database:
    """
    线程安全的 SQLite 数据库管理器

    v5.3 并发优化：
      - 读写锁分离：读不互斥（利用 WAL 多读并发），写串行化（SQLite 单写限制）
      - init_local 仍用 _local_lock 保护一次性初始化
      - 写操作用 _write_lock 串行，避免 SQLITE_BUSY
    """

    _instance: Optional["Database"] = None
    _local_lock = threading.Lock()       # 保护 init_local 一次性初始化
    _write_lock = threading.Lock()       # 保护写操作串行化（SQLite 单写）
    _shared_lock = threading.Lock()      # 保护 shared 连接

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

    def init_local(self, db_path: str):
        """初始化本地数据库，始终启用 WAL 模式以提升写入性能 + FK 约束"""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._local_lock:
            self._local_conn = sqlite3.connect(db_path, check_same_thread=False)
            self._local_conn.row_factory = sqlite3.Row

            self._local_conn.execute("PRAGMA journal_mode=WAL")
            self._local_conn.execute("PRAGMA synchronous=NORMAL")
            self._local_conn.execute("PRAGMA wal_autocheckpoint=1000")
            # v4.3: 启用外键约束运行时检查
            self._local_conn.execute("PRAGMA foreign_keys=ON")

            # 总是建表（CREATE IF NOT EXISTS，幂等安全）
            self._create_local_tables()

            # v6.0.1: 检查 schema 版本，跳过已完成的迁移
            from devpartner_agent.core.config import get_project_version
            current_version = get_project_version()
            schema_version = self._get_schema_version()

            if schema_version == current_version:
                print(f"[DB] Schema 已是最新 ({current_version})，跳过迁移")
            else:
                print(f"[DB] Schema 版本变更 {schema_version} → {current_version}，执行迁移...")
                self._migrate_old_tables()
                self._migrate_text_to_json()
                self._migrate_add_foreign_keys()
                # v4.3: 存量数据回填 conversations_id
                self._backfill_conversations_id()
                # v5.3: 补全缺失列
                self._migrate_v53()
                # v6.0: 表结构优化（多维度 JSON + 技能追溯字段）
                self._migrate_v60()
                # 记录当前 schema 版本
                self._set_schema_version(current_version)
                print(f"[DB] Schema 迁移完成 → {current_version}")

    def init_shared(self, db_path: str):
        """初始化共享数据库连接"""
        try:
            with self._shared_lock:
                self._shared_conn = sqlite3.connect(db_path, check_same_thread=False)
                self._shared_conn.row_factory = sqlite3.Row
        except Exception:
            self._shared_conn = None

    def _create_local_tables(self):
        """创建本地数据库表（v3.0 精简版）"""
        cursor = self._local_conn.cursor()

        # ── 对话日志表（核心表，v4.3 新增 analyzed 列）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT UNIQUE,  -- v6.0: 添加唯一约束以支持外键引用
                timestamp TEXT NOT NULL,
                client TEXT DEFAULT 'unknown',
                topic TEXT,
                task_type TEXT,
                user_intent TEXT,
                actions JSON,
                problems TEXT,
                solutions TEXT,
                decisions TEXT,
                files_touched JSON,
                thinking_steps JSON,
                self_reflection TEXT,
                raw_json JSON,
                skill_domains JSON DEFAULT '',
                complexity TEXT DEFAULT 'simple',
                feedback_type JSON DEFAULT '',
                analyzed INTEGER DEFAULT 0
            )
        """)

        # ── 对话存档表（完整对话存档，v4.3 强制 FK 外键约束）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT DEFAULT 'unknown',
                client TEXT DEFAULT 'unknown',
                conversation_id TEXT,
                conversations_id INTEGER,
                raw_content TEXT,
                summary TEXT,
                skill_domains JSON,
                complexity TEXT DEFAULT 'simple',
                tool_calls JSON,
                user_feedback JSON,
                analyzed INTEGER DEFAULT 0,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)

        # ── 进化日志表（增强版：记录每次自我进化，v4.3 强制 FK 外键约束）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evolution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                version TEXT DEFAULT '',
                change_type TEXT,
                description TEXT,
                files_changed TEXT,
                success INTEGER DEFAULT 1,
                conversations_id INTEGER,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)

        # ── 版本历史表（v4.2: 扩充结构化字段）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS version_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                version TEXT NOT NULL,
                previous_version TEXT,
                change_summary TEXT,
                changelog TEXT,
                tools_count INTEGER DEFAULT 0,
                triggered_by TEXT DEFAULT 'startup',
                diff_detail TEXT DEFAULT '',
                optimize_point TEXT DEFAULT '',
                bug_fix TEXT DEFAULT '',
                new_feature TEXT DEFAULT '',
                data_change TEXT DEFAULT ''
            )
        """)

        # ── MCP 工具注册表（新增：记录所有已注册的 MCP 工具）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_tool_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                module TEXT,
                description TEXT,
                version_registered TEXT,
                last_called TEXT,
                call_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active'
            )
        """)

        # ── 改进日志表（原 system_improvements，v4.3 强制 FK 外键约束）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS improvement_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT,
                suggestion TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                applied_at TEXT,
                result TEXT,
                conversations_id INTEGER,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)

        # ── 用户技能表（原 skill_profile）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                skill_domain TEXT NOT NULL,
                skill_level TEXT DEFAULT 'beginner',
                sub_skills TEXT,
                evidence TEXT,
                conversation_ids TEXT,
                hours_spent REAL DEFAULT 0,
                growth_trend TEXT DEFAULT 'stable',
                last_updated TEXT
            )
        """)

        # ── 用户技能规划表（新增：目标与进度）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_skill_plan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                skill_domain TEXT NOT NULL,
                goal TEXT,
                target_level TEXT,
                target_date TEXT,
                current_progress TEXT,
                milestones JSON,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # ── 优化反馈表（v4.3 强制 FK 外键约束）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS optimization_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT DEFAULT 'auto',
                feedback_type TEXT NOT NULL,
                target_tool TEXT,
                target_rule TEXT,
                description TEXT,
                suggestion TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                applied_at TEXT,
                result TEXT,
                conversation_id TEXT,
                conversations_id INTEGER,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)

        # ── v5.0: 会话步骤表（★ 步骤化异步处理）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL,
                step_order INTEGER NOT NULL,
                step_type TEXT NOT NULL,
                step_name TEXT,
                status TEXT DEFAULT 'pending',
                input_data JSON,
                output_data JSON,
                error_message TEXT,
                knowledge_point_ids TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                priority INTEGER DEFAULT 0,
                depends_on TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_steps_conv_id
            ON conversation_steps(conversation_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_steps_status
            ON conversation_steps(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_steps_order
            ON conversation_steps(conversation_id, step_order)
        """)

        # ── v5.0: 知识点表（★ 知识库有序落地）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                domain TEXT NOT NULL,
                tags JSON DEFAULT '[]',
                source_type TEXT,
                source_id TEXT,
                confidence REAL DEFAULT 0.8,
                difficulty TEXT DEFAULT 'medium',
                usage_count INTEGER DEFAULT 0,
                last_used_at TEXT,
                related_knowledge_ids TEXT,
                version INTEGER DEFAULT 1,
                is_verified INTEGER DEFAULT 0,
                metadata JSON DEFAULT '{}',
                created_by TEXT DEFAULT 'system',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_points_domain
            ON knowledge_points(domain)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_points_category
            ON knowledge_points(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_points_source
            ON knowledge_points(source_type, source_id)
        """)

        # ── v5.0: 异步任务队列表（★ 优先级调度 + 资源控制）──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                task_type TEXT NOT NULL,
                payload JSON NOT NULL,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                result JSON,
                progress REAL DEFAULT 0.0,
                estimated_memory_mb INTEGER DEFAULT 0,
                actual_memory_mb INTEGER DEFAULT 0,
                queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                timeout_seconds INTEGER DEFAULT 300,
                worker_id TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_status
            ON task_queue(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_priority
            ON task_queue(priority DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_type
            ON task_queue(task_type)
        """)

        # ── 迁移：为已有 conversations 表补列 ──
        # 注意：SQLite ALTER TABLE ADD COLUMN 不支持 UNIQUE 约束，
        # conversation_id 的唯一性由应用层保证
        for col, col_def in [
            ("client", "TEXT DEFAULT 'unknown'"),
            ("conversation_id", "TEXT DEFAULT ''"),
            ("skill_domains", "TEXT DEFAULT ''"),
            ("complexity", "TEXT DEFAULT 'simple'"),
            ("feedback_type", "TEXT DEFAULT ''"),
            ("analyzed", "INTEGER DEFAULT 0"),  # v4.3: 标记是否完成用户画像分析
            ("status", "TEXT DEFAULT 'active'"),       # v5.0: 状态机
            ("priority", "TEXT DEFAULT 'medium'"),      # v5.0: 优先级
            ("total_steps", "INTEGER DEFAULT 0"),       # v5.0: 总步骤数
            ("completed_steps", "INTEGER DEFAULT 0"),   # v5.0: 已完成步骤
            ("created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),  # v5.0
            ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),  # v5.0
            ("completed_at", "TEXT"),                   # v5.0
        ]:
            try:
                cursor.execute(f"ALTER TABLE conversations ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass

        # v4.1: 为 conversation_archive 补 conversations_id 列
        try:
            cursor.execute("ALTER TABLE conversation_archive ADD COLUMN conversations_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # v4.1: 为 optimization_feedback 补 conversations_id 列
        try:
            cursor.execute("ALTER TABLE optimization_feedback ADD COLUMN conversations_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # v4.1: 为 evolution_log 补 success 列（修复迁移bug导致缺失的列）
        try:
            cursor.execute("ALTER TABLE evolution_log ADD COLUMN success INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass

        # v4.2: 为 evolution_log 补 conversations_id 列
        try:
            cursor.execute("ALTER TABLE evolution_log ADD COLUMN conversations_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # v4.2: 为 improvement_log 补 conversations_id 列
        try:
            cursor.execute("ALTER TABLE improvement_log ADD COLUMN conversations_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # v4.2: 为 version_history 补结构化字段
        for col, col_def in [
            ("diff_detail", "TEXT DEFAULT ''"),
            ("optimize_point", "TEXT DEFAULT ''"),
            ("bug_fix", "TEXT DEFAULT ''"),
            ("new_feature", "TEXT DEFAULT ''"),
            ("data_change", "TEXT DEFAULT ''"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE version_history ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass

        # v6.0.1: 元数据表 — 跟踪 schema 版本，避免每次重启重跑迁移
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self._local_conn.commit()

    # ══════════════════════════════════════════════════════════
    # Schema 版本管理（v6.0.1）
    # ══════════════════════════════════════════════════════════

    def _get_schema_version(self) -> str:
        """获取当前数据库 schema 版本号"""
        try:
            cursor = self._local_conn.cursor()
            cursor.execute("SELECT value FROM meta WHERE key='schema_version'")
            row = cursor.fetchone()
            return row["value"] if row else "0.0.0"
        except Exception:
            return "0.0.0"

    def _set_schema_version(self, version: str):
        """设置数据库 schema 版本号"""
        cursor = self._local_conn.cursor()
        cursor.execute("""
            INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """, (version,))
        self._local_conn.commit()

    def _migrate_old_tables(self):
        """迁移旧表数据到新表（v3.0 平滑升级）"""
        cursor = self._local_conn.cursor()

        # 1. system_improvements → improvement_log
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='system_improvements'"
            )
            if cursor.fetchone():
                count = cursor.execute(
                    "SELECT COUNT(*) FROM system_improvements"
                ).fetchone()[0]
                if count > 0:
                    cursor.execute("""
                        INSERT INTO improvement_log
                        (id, timestamp, category, suggestion, priority, status, applied_at, result)
                        SELECT id, timestamp, category, suggestion, priority, status, applied_at, result
                        FROM system_improvements
                    """)
                    print(f"[DB] 迁移 system_improvements → improvement_log: {count} 条")
                cursor.execute("DROP TABLE IF EXISTS system_improvements")
                print("[DB] 已删除旧表 system_improvements")
        except Exception:
            pass

        # 2. skill_profile → user_skills
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_profile'"
            )
            if cursor.fetchone():
                count = cursor.execute(
                    "SELECT COUNT(*) FROM skill_profile"
                ).fetchone()[0]
                if count > 0:
                    cursor.execute("""
                        INSERT INTO user_skills
                        (id, timestamp, skill_domain, skill_level, sub_skills,
                         evidence, conversation_ids, hours_spent, growth_trend, last_updated)
                        SELECT id, timestamp, skill_domain, skill_level, sub_skills,
                               evidence, conversation_ids, hours_spent, growth_trend, last_updated
                        FROM skill_profile
                    """)
                    print(f"[DB] 迁移 skill_profile → user_skills: {count} 条")
                cursor.execute("DROP TABLE IF EXISTS skill_profile")
                print("[DB] 已删除旧表 skill_profile")
        except Exception:
            pass

        # 3. mcp_discovery → mcp_tool_registry（仅迁移数据，表结构不同）
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_discovery'"
            )
            if cursor.fetchone():
                count = cursor.execute(
                    "SELECT COUNT(*) FROM mcp_discovery"
                ).fetchone()[0]
                if count > 0:
                    cursor.execute("""
                        INSERT INTO mcp_tool_registry
                        (timestamp, tool_name, module, description, status, last_called, call_count)
                        SELECT timestamp, server_name, npm_package, description, status, last_check, 0
                        FROM mcp_discovery
                    """)
                    print(f"[DB] 迁移 mcp_discovery → mcp_tool_registry: {count} 条")
                cursor.execute("DROP TABLE IF EXISTS mcp_discovery")
                print("[DB] 已删除旧表 mcp_discovery")
        except Exception:
            pass

        # 4. 删除其他死表
        for dead_table in ["rule_executions", "knowledge_graph", "mindmaps"]:
            try:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (dead_table,)
                )
                if cursor.fetchone():
                    cursor.execute("DROP TABLE IF EXISTS {}".format(dead_table))
                    print("[DB] 已删除死表 {}".format(dead_table))
            except Exception:
                pass

        # 5. evolution_log 结构迁移（旧表有 version_from/version_to，新表有 version）
        try:
            cursor.execute("PRAGMA table_info(evolution_log)")
            columns = [row[1] for row in cursor.fetchall()]
            if "version_from" in columns and "version" not in columns:
                rows = cursor.execute("SELECT * FROM evolution_log").fetchall()
                cursor.execute("DROP TABLE IF EXISTS evolution_log")
                cursor.execute("""
                    CREATE TABLE evolution_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        version TEXT DEFAULT '',
                        change_type TEXT NOT NULL,
                        description TEXT,
                        files_changed TEXT,
                        success INTEGER DEFAULT 1
                    )
                """)
                for row in rows:
                    cursor.execute("""
                        INSERT INTO evolution_log
                        (id, timestamp, version, change_type, description, files_changed)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (row[0], row[1], row[2] if row[2] else "", row[4], row[5], row[6]))
                print("[DB] 已迁移 evolution_log 表结构")
        except Exception:
            pass

        self._local_conn.commit()

    def _migrate_text_to_json(self):
        """v4.3: 将存储 JSON 数据的 TEXT 字段迁移为 JSON 类型，方便 DB 工具展示"""
        cursor = self._local_conn.cursor()

        # ── 需要迁移的表与字段映射 ──
        migrations = {
            "conversations": {
                "json_columns": ["actions", "files_touched", "thinking_steps",
                                 "raw_json", "skill_domains", "feedback_type"],
                "create_sql": """
                    CREATE TABLE conversations_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT,
                        timestamp TEXT NOT NULL,
                        client TEXT DEFAULT 'unknown',
                        topic TEXT,
                        task_type TEXT,
                        user_intent TEXT,
                        actions JSON,
                        problems TEXT,
                        solutions TEXT,
                        decisions TEXT,
                        files_touched JSON,
                        thinking_steps JSON,
                        self_reflection TEXT,
                        raw_json JSON,
                        skill_domains JSON DEFAULT '',
                        complexity TEXT DEFAULT 'simple',
                        feedback_type JSON DEFAULT '',
                        analyzed INTEGER DEFAULT 0
                    )
                """,
            },
            "conversation_archive": {
                "json_columns": ["skill_domains", "tool_calls", "user_feedback"],
                "create_sql": """
                    CREATE TABLE conversation_archive_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        source TEXT DEFAULT 'unknown',
                        client TEXT DEFAULT 'unknown',
                        conversation_id TEXT,
                        conversations_id INTEGER,
                        raw_content TEXT,
                        summary TEXT,
                        skill_domains JSON,
                        complexity TEXT DEFAULT 'simple',
                        tool_calls JSON,
                        user_feedback JSON,
                        analyzed INTEGER DEFAULT 0
                    )
                """,
            },
            "user_skill_plan": {
                "json_columns": ["milestones"],
                "create_sql": """
                    CREATE TABLE user_skill_plan_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        skill_domain TEXT NOT NULL,
                        goal TEXT,
                        target_level TEXT,
                        target_date TEXT,
                        current_progress TEXT,
                        milestones JSON,
                        status TEXT DEFAULT 'active',
                        created_at TEXT,
                        updated_at TEXT
                    )
                """,
            },
        }

        for table_name, config in migrations.items():
            try:
                # 检查表是否存在
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if not cursor.fetchone():
                    continue

                # 检查当前列类型：如果所有目标列都已是 JSON 类型则跳过
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns_info = {row[1]: row[2].upper() for row in cursor.fetchall()}

                need_migration = False
                for col in config["json_columns"]:
                    col_type = columns_info.get(col, "")
                    if col_type != "JSON":
                        need_migration = True
                        break

                if not need_migration:
                    continue

                print(f"[DB] 检测到 {table_name} 表使用 TEXT 存储 JSON，开始迁移...")

                # 创建新表
                cursor.execute(config["create_sql"])

                # 获取旧表所有列名
                cursor.execute(f"PRAGMA table_info({table_name})")
                old_columns = [row[1] for row in cursor.fetchall()]

                # 获取新表所有列名
                cursor.execute(f"PRAGMA table_info({table_name}_new)")
                new_columns = [row[1] for row in cursor.fetchall()]

                # 取交集列名（保证兼容性）
                common_columns = [c for c in old_columns if c in new_columns]
                columns_str = ", ".join(common_columns)
                placeholders = ", ".join(["?" for _ in common_columns])

                # 复制数据
                cursor.execute(f"SELECT {columns_str} FROM {table_name}")
                rows = cursor.fetchall()
                if rows:
                    cursor.executemany(
                        f"INSERT INTO {table_name}_new ({columns_str}) VALUES ({placeholders})",
                        rows
                    )

                # 删除旧表，重命名新表
                cursor.execute(f"DROP TABLE {table_name}")
                cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")

                print(f"[DB] {table_name} 表 JSON 字段迁移完成 ({len(rows)} 条数据)")

            except Exception as e:
                print(f"[DB] {table_name} 表 JSON 迁移失败: {e}")
                # 清理残留的新表
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name}_new")
                except Exception:
                    pass

        self._local_conn.commit()

    def _migrate_add_foreign_keys(self):
        """
        v4.3: 为存量子表添加 FK 外键约束。

        SQLite 不支持 ALTER TABLE ADD CONSTRAINT，因此采用重建表方式：
        1. 创建带 FK 的新表
        2. 复制数据
        3. 删除旧表，重命名新表

        仅当子表不存在 FK 约束时才执行迁移。
        """
        cursor = self._local_conn.cursor()

        # 需要迁移的子表定义
        fk_migrations = {
            "conversation_archive": """
                CREATE TABLE conversation_archive_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT DEFAULT 'unknown',
                    client TEXT DEFAULT 'unknown',
                    conversation_id TEXT,
                    conversations_id INTEGER,
                    raw_content TEXT,
                    summary TEXT,
                    skill_domains JSON,
                    complexity TEXT DEFAULT 'simple',
                    tool_calls JSON,
                    user_feedback JSON,
                    analyzed INTEGER DEFAULT 0,
                    FOREIGN KEY (conversations_id) REFERENCES conversations(id)
                )
            """,
            "optimization_feedback": """
                CREATE TABLE optimization_feedback_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT DEFAULT 'auto',
                    feedback_type TEXT NOT NULL,
                    target_tool TEXT,
                    target_rule TEXT,
                    description TEXT,
                    suggestion TEXT,
                    priority TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'pending',
                    applied_at TEXT,
                    result TEXT,
                    conversation_id TEXT,
                    conversations_id INTEGER,
                    FOREIGN KEY (conversations_id) REFERENCES conversations(id)
                )
            """,
            "evolution_log": """
                CREATE TABLE evolution_log_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    version TEXT DEFAULT '',
                    change_type TEXT,
                    description TEXT,
                    files_changed TEXT,
                    success INTEGER DEFAULT 1,
                    conversations_id INTEGER,
                    FOREIGN KEY (conversations_id) REFERENCES conversations(id)
                )
            """,
            "improvement_log": """
                CREATE TABLE improvement_log_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT,
                    suggestion TEXT,
                    priority TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'pending',
                    applied_at TEXT,
                    result TEXT,
                    conversations_id INTEGER,
                    FOREIGN KEY (conversations_id) REFERENCES conversations(id)
                )
            """,
        }

        for table_name, create_sql in fk_migrations.items():
            try:
                # 检查表是否存在
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if not cursor.fetchone():
                    continue

                # 检查当前表建表语句中是否已包含 FOREIGN KEY
                cursor.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                row = cursor.fetchone()
                if row and "FOREIGN KEY" in (row[0] or ""):
                    continue  # 已有 FK，跳过

                print(f"[DB] 为 {table_name} 添加 FOREIGN KEY 约束...")

                # 获取旧表所有列名
                cursor.execute(f"PRAGMA table_info({table_name})")
                old_columns = [r[1] for r in cursor.fetchall()]

                # 创建新表
                cursor.execute(create_sql)

                # 获取新表所有列名
                cursor.execute(f"PRAGMA table_info({table_name}_new)")
                new_columns = [r[1] for r in cursor.fetchall()]

                # 取交集列
                common_columns = [c for c in old_columns if c in new_columns]
                columns_str = ", ".join(common_columns)
                placeholders = ", ".join(["?" for _ in common_columns])

                # 复制数据（注意：不会复制违反 FK 的行—conversations_id 为 NULL 或指向不存在记录）
                cursor.execute(f"SELECT {columns_str} FROM {table_name}")
                rows = cursor.fetchall()
                valid_rows = []
                skipped = 0
                for row in rows:
                    row_dict = dict(zip(common_columns, row))
                    cid = row_dict.get("conversations_id")
                    if cid is not None:
                        # 验证 conversations_id 引用的记录存在
                        cursor.execute("SELECT 1 FROM conversations WHERE id = ?", (cid,))
                        if not cursor.fetchone():
                            # FK 约束违反：指向不存在的 conversations 记录，置为 NULL
                            row_dict["conversations_id"] = None
                            skipped += 1
                    valid_rows.append(tuple(row_dict[c] for c in common_columns))

                if valid_rows:
                    cursor.executemany(
                        f"INSERT INTO {table_name}_new ({columns_str}) VALUES ({placeholders})",
                        valid_rows
                    )

                # 替换表
                cursor.execute(f"DROP TABLE {table_name}")
                cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name}")

                print(f"[DB] {table_name} FK 约束添加完成 ({len(valid_rows)} 条数据"
                      f"{f', {skipped} 条 FK 无效已清理' if skipped > 0 else ''})")

            except Exception as e:
                print(f"[DB] {table_name} FK 迁移失败: {e}")
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name}_new")
                except Exception:
                    pass

        self._local_conn.commit()

    def _backfill_conversations_id(self):
        """
        v4.3: 存量数据回填 — 为历史记录中 conversations_id 为 NULL 的行补全关联。

        策略：
        1. 通过 conversation_id (业务ID) 匹配 conversations 表中的对应记录
        2. 无法匹配的保留 NULL（安全策略，不猜测关联）
        """
        cursor = self._local_conn.cursor()
        backfilled = {"conversation_archive": 0, "optimization_feedback": 0,
                       "evolution_log": 0, "improvement_log": 0}

        # conversation_archive: 通过 conversation_id (业务ID) 匹配 conversations 表
        try:
            cursor.execute("""
                UPDATE conversation_archive
                SET conversations_id = (
                    SELECT c.id FROM conversations c
                    WHERE c.conversation_id = conversation_archive.conversation_id
                    AND c.conversation_id != ''
                )
                WHERE conversations_id IS NULL
            """)
            backfilled["conversation_archive"] = cursor.rowcount
        except Exception as e:
            print(f"[DB] conversation_archive 存量回填失败: {e}")

        # optimization_feedback: 通过 conversation_id (业务ID) 匹配
        try:
            cursor.execute("""
                UPDATE optimization_feedback
                SET conversations_id = (
                    SELECT c.id FROM conversations c
                    WHERE c.conversation_id = optimization_feedback.conversation_id
                    AND c.conversation_id != ''
                )
                WHERE conversations_id IS NULL
                  AND conversation_id IS NOT NULL
                  AND conversation_id != ''
            """)
            backfilled["optimization_feedback"] = cursor.rowcount
        except Exception as e:
            print(f"[DB] optimization_feedback 存量回填失败: {e}")

        # evolution_log / improvement_log: 通过时间戳范围估算关联
        # 这两张表没有 conversation_id 业务ID，只能通过 timestamp 范围匹配最近的 conversation
        try:
            cursor.execute("""
                UPDATE evolution_log
                SET conversations_id = (
                    SELECT c.id FROM conversations c
                    WHERE c.timestamp <= evolution_log.timestamp
                    ORDER BY c.timestamp DESC LIMIT 1
                )
                WHERE conversations_id IS NULL
            """)
            backfilled["evolution_log"] = cursor.rowcount
        except Exception as e:
            print(f"[DB] evolution_log 存量回填失败: {e}")

        try:
            cursor.execute("""
                UPDATE improvement_log
                SET conversations_id = (
                    SELECT c.id FROM conversations c
                    WHERE c.timestamp <= improvement_log.timestamp
                    ORDER BY c.timestamp DESC LIMIT 1
                )
                WHERE conversations_id IS NULL
            """)
            backfilled["improvement_log"] = cursor.rowcount
        except Exception as e:
            print(f"[DB] improvement_log 存量回填失败: {e}")

        total = sum(backfilled.values())
        if total > 0:
            print(f"[DB] 存量数据 conversations_id 回填完成: {backfilled}")
        self._local_conn.commit()

    def _migrate_v53(self):
        """v5.3: 补全 conversation_steps 表缺失列 + task_queue 表补充"""
        cursor = self._local_conn.cursor()

        # conversation_steps 添加 timeout_seconds 列
        try:
            cursor.execute("ALTER TABLE conversation_steps ADD COLUMN timeout_seconds INTEGER DEFAULT 300")
            print("[DB] conversation_steps.timeout_seconds 列已添加")
        except Exception:
            pass  # 列已存在

        self._local_conn.commit()

    def _migrate_v60(self):
        """
        v6.0: improvement_log 表结构优化 + 外键修复
        
        变更内容：
        1. improvement_log 新增 dimensions JSON 字段
        2. user_skills 新增 7 个追溯字段（confidence, first_seen 等）
        3. ★ conversations.conversation_id 添加 UNIQUE 约束（修复外键不匹配问题）
        4. 创建索引优化查询性能
        """
        cursor = self._local_conn.cursor()
        
        # ════════════════════════════════════════════
        # 1. improvement_log 表新增 dimensions 字段
        # ════════════════════════════════════════════
        try:
            cursor.execute("""
                ALTER TABLE improvement_log 
                ADD COLUMN dimensions TEXT
            """)
            
            cursor.execute("""
                UPDATE improvement_log 
                SET dimensions = json_object(
                    'category', category,
                    'suggestion', suggestion,
                    'original_category', category
                )
                WHERE dimensions IS NULL
            """)
            
            print("[DB] improvement_log.dimensions (JSON) 列已添加")
            
        except Exception as e:
            print(f"[DB] improvement_log.dimensions 列可能已存在: {e}")
        
        # ════════════════════════════════════════════
        # 2. ★ 修复外键约束：给 conversation_id 添加唯一约束
        # ════════════════════════════════════════════
        try:
            # 检查是否已有唯一索引
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND tbl_name='conversations' 
                AND sql LIKE '%conversation_id%UNIQUE%'
            """)
            
            if not cursor.fetchone():
                # ★ v6.0.1: 创建索引前先清理无效数据，否则 UNIQUE 索引会失败
                #   NULL/空字符串 → 生成 UUID 填充
                cursor.execute("""
                    UPDATE conversations 
                    SET conversation_id = 'conv_' || lower(hex(randomblob(16)))
                    WHERE conversation_id IS NULL OR conversation_id = ''
                """)
                #   → 删除重复记录（保留最新的 id）
                cursor.execute("""
                    DELETE FROM conversations 
                    WHERE id NOT IN (
                        SELECT MAX(id) FROM conversations 
                        WHERE conversation_id IS NOT NULL AND conversation_id != ''
                        GROUP BY conversation_id
                    )
                """)
                
                # 创建唯一索引（等价于添加 UNIQUE 约束）
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique 
                    ON conversations(conversation_id)
                """)
                
                print("[DB] ✅ conversations.conversation_id 唯一约束已添加（修复外键不匹配）")
            else:
                print("[DB] conversations.conversation_id 唯一约束已存在")
                
        except Exception as e:
            print(f"[DB] ⚠️ 添加唯一约束失败（可能存在重复数据）: {e}")
            print("[DB] 提示：如需修复，请手动清理重复的 conversation_id 后重试")
        
        try:
            # 2. user_skills 表新增追溯字段
            new_columns = [
                ("confidence", "REAL DEFAULT 0.5"),
                ("first_seen", "TEXT"),
                ("last_seen", "TEXT"),
                ("evidence_count", "INTEGER DEFAULT 1"),
                ("source_conversation_id", "INTEGER"),
                ("source_timestamp", "TEXT"),
                ("extraction_method", "TEXT"),
            ]
            
            for col_name, col_type in new_columns:
                try:
                    cursor.execute(f"""
                        ALTER TABLE user_skills 
                        ADD COLUMN {col_name} {col_type}
                    """)
                    print(f"[DB] user_skills.{col_name} 列已添加")
                except Exception:
                    pass  # 列已存在
            
            # 3. 为 user_skills 创建唯一索引（防重复）
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_skills_unique 
                ON user_skills(skill_domain)
            """)
            print("[DB] user_skills 唯一索引已创建")
            
            # 4. 为 source_conversation_id 创建索引（加速追溯查询）
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_source 
                ON user_skills(source_conversation_id)
            """)
            print("[DB] user_skills.source_conversation_id 索引已创建")
            
        except Exception as e:
            print(f"[DB] user_skills 追溯字段迁移失败: {e}")
        
        self._local_conn.commit()
        print("[DB] v6.0 数据库迁移完成")

    def validate_conversation_integrity(self) -> dict:
        """
        v4.3: 数据完整性校验 — 检查关键字段非空 + 外键关联有效性。

        Returns:
            {
                "status": "ok|warning|error",
                "total_records": N,
                "null_fields": {"field_name": count, ...},
                "orphaned_fks": {"table_name": count, ...},
                "details": [...]
            }
        """
        cursor = self._local_conn.cursor()
        issues = []
        null_fields = {}
        orphaned_fks = {}

        # 1. 检查 conversations 表关键字段非空
        for field in ["topic", "task_type", "skill_domains", "feedback_type"]:
            cursor.execute(
                f"SELECT COUNT(*) FROM conversations WHERE {field} IS NULL OR {field} = ''"
            )
            count = cursor.fetchone()[0]
            if count > 0:
                null_fields[field] = count
                issues.append(f"conversations.{field}: {count} 条记录为空")

        # 2. 检查 conversations.analyzed 状态
        cursor.execute("SELECT COUNT(*) FROM conversations WHERE analyzed IS NULL")
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            null_fields["analyzed"] = null_count
        cursor.execute("SELECT COUNT(*) FROM conversations WHERE analyzed = 0")
        unanalyzed = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM conversations")
        total_conv = cursor.fetchone()[0]
        if unanalyzed > 0:
            issues.append(f"conversations.analyzed: {unanalyzed}/{total_conv} 条记录未完成分析")

        # 3. 检查 FK 关联—子表中 conversations_id 是否指向有效记录
        fk_tables = ["conversation_archive", "optimization_feedback",
                      "evolution_log", "improvement_log"]
        for table in fk_tables:
            try:
                cursor.execute(f"""
                    SELECT COUNT(*) FROM {table} t
                    WHERE t.conversations_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM conversations c WHERE c.id = t.conversations_id
                      )
                """)
                count = cursor.fetchone()[0]
                if count > 0:
                    orphaned_fks[table] = count
                    issues.append(f"{table}: {count} 条记录指向不存在的 conversations")
            except Exception:
                pass

        # 4. 检查 conversation_archive.analyzed 与 conversations.analyzed 一致性
        cursor.execute("""
            SELECT count(*) FROM conversation_archive ca
            JOIN conversations c ON ca.conversations_id = c.id
            WHERE ca.analyzed = 0 AND c.analyzed = 1
        """)
        mismatch = cursor.fetchone()[0]
        if mismatch > 0:
            issues.append(f"archive.analyzed 与 conversations.analyzed 不一致: {mismatch} 条")

        status = "error" if orphaned_fks else ("warning" if issues else "ok")
        return {
            "status": status,
            "total_records": total_conv,
            "null_fields": null_fields,
            "orphaned_fks": orphaned_fks,
            "issues": issues,
        }

    # ══════════════════════════════════════════════════════════
    # 通用查询
    # ══════════════════════════════════════════════════════════

    def query_local(self, sql: str, params: tuple = ()) -> list[dict]:
        """
        执行本地数据库查询（v5.3: 读写锁分离）
        - SELECT: 不持锁，利用 WAL 多读并发
        - 写操作: _write_lock 串行化
        """
        if not self._local_conn:
            raise RuntimeError("本地数据库未初始化")
        is_read = sql.strip().upper().startswith("SELECT")
        if is_read:
            # 读操作：不持锁，WAL 模式下多读可并发
            cursor = self._local_conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        else:
            # 写操作：串行化，避免 SQLITE_BUSY
            with self._write_lock:
                cursor = self._local_conn.cursor()
                cursor.execute(sql, params)
                self._local_conn.commit()
                return [{"affected_rows": cursor.rowcount, "last_id": cursor.lastrowid}]

    def query_shared(self, sql: str, params: tuple = ()) -> list[dict]:
        """
        执行共享数据库查询（v5.3: 读写锁分离）
        """
        if not self._shared_conn:
            raise RuntimeError("共享数据库未连接")
        is_read = sql.strip().upper().startswith("SELECT")
        if is_read:
            cursor = self._shared_conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        else:
            with self._write_lock:
                cursor = self._shared_conn.cursor()
                cursor.execute(sql, params)
                self._shared_conn.commit()
                return [{"affected_rows": cursor.rowcount}]

    # ══════════════════════════════════════════════════════════
    # 对话记录
    # ══════════════════════════════════════════════════════════

    def insert_conversation(self, data: dict):
        """
        插入对话记录（v4.3 增强：analyzed 字段 + 关键字段非空校验）

        Returns:
            [{"affected_rows": N, "last_id": <conversations.id 主键>}]
        """
        client = data.get("client") or data.get("agent", "unknown")

        if "raw_json_override" in data:
            raw_json_str = json.dumps(data.pop("raw_json_override"), ensure_ascii=False)
        else:
            raw_json_str = json.dumps(data, ensure_ascii=False)

        # 确保有 conversation_id（优先用传入的，否则自动生成）
        conv_id = data.get("conversation_id", "") or datetime.now().strftime("%Y%m%d%H%M%S%f")

        # v4.1: skill_domains / feedback_type / complexity 填充
        skill_domains = data.get("skill_domains", "")
        if isinstance(skill_domains, (list, dict)):
            skill_domains = json.dumps(skill_domains, ensure_ascii=False)
        feedback_type = data.get("feedback_type", "")
        if isinstance(feedback_type, (list, dict)):
            feedback_type = json.dumps(feedback_type, ensure_ascii=False)
        complexity = data.get("complexity", "simple")
        analyzed = data.get("analyzed", 0)  # v4.3: 默认 0，分析后回写

        # v4.3: 关键字段非空校验
        topic = data.get("topic", "")
        task_type = data.get("task_type", "")
        if not topic or not task_type:
            print(f"[DB] ⚠️ insert_conversation 警告: topic='{topic[:30] if topic else '(空)'}', "
                  f"task_type='{task_type or '(空)'}' — 关键字段不应为空")

        sql = """
            INSERT INTO conversations
            (conversation_id, timestamp, client, topic, task_type, user_intent, actions,
             problems, solutions, decisions, files_touched, thinking_steps, self_reflection,
             raw_json, skill_domains, complexity, feedback_type, analyzed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            conv_id,
            data.get("timestamp", datetime.now().isoformat()),
            client,
            topic,
            task_type,
            data.get("user_intent", ""),
            data.get("actions", ""),
            data.get("problems", ""),
            data.get("solutions", ""),
            data.get("decisions", ""),
            json.dumps(data.get("files_touched", []), ensure_ascii=False),
            json.dumps(data.get("thinking_steps", []), ensure_ascii=False),
            data.get("self_reflection", ""),
            raw_json_str,
            skill_domains,
            complexity,
            feedback_type,
            analyzed,
        )
        return self.query_local(sql, params)

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

    # ══════════════════════════════════════════════════════════
    # 改进日志（原 system_improvements）
    # ══════════════════════════════════════════════════════════

    def insert_improvement(self, category: str, suggestion: str, priority: str = "medium",
                           conversations_id: int = None):
        """插入改进建议（v4.2: 支持 conversations_id 关联）"""
        sql = """
            INSERT INTO improvement_log (timestamp, category, suggestion, priority, conversations_id)
            VALUES (?, ?, ?, ?, ?)
        """
        return self.query_local(sql, (
            datetime.now().isoformat(), category, suggestion, priority, conversations_id
        ))

    def get_pending_improvements(self) -> list[dict]:
        """获取待处理的改进建议"""
        return self.query_local(
            "SELECT * FROM improvement_log WHERE status='pending' "
            "ORDER BY priority DESC, timestamp ASC"
        )

    # ══════════════════════════════════════════════════════════
    # 用户技能（原 skill_profile）
    # ══════════════════════════════════════════════════════════

    def upsert_user_skills(self, domain: str, data: dict):
        """插入或更新用户技能"""
        existing = self.query_local(
            "SELECT id FROM user_skills WHERE skill_domain = ?", (domain,)
        )
        now = datetime.now().isoformat()
        if existing:
            sql = """
                UPDATE user_skills
                SET skill_level = ?, sub_skills = ?, evidence = ?,
                    conversation_ids = ?, hours_spent = hours_spent + ?,
                    growth_trend = ?, last_updated = ?
                WHERE skill_domain = ?
            """
            self.query_local(sql, (
                data.get("skill_level", "beginner"),
                data.get("sub_skills", ""),
                data.get("evidence", ""),
                data.get("conversation_ids", ""),
                data.get("hours_spent", 0),
                data.get("growth_trend", "stable"),
                now,
                domain,
            ))
        else:
            sql = """
                INSERT INTO user_skills
                (timestamp, skill_domain, skill_level, sub_skills, evidence,
                 conversation_ids, hours_spent, growth_trend, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            self.query_local(sql, (
                now, domain,
                data.get("skill_level", "beginner"),
                data.get("sub_skills", ""),
                data.get("evidence", ""),
                data.get("conversation_ids", ""),
                data.get("hours_spent", 0),
                data.get("growth_trend", "stable"),
                now,
            ))

    def get_skill_profile(self, domain: str = None) -> list[dict]:
        """获取用户技能画像"""
        if domain:
            return self.query_local(
                "SELECT * FROM user_skills WHERE skill_domain = ?", (domain,)
            )
        return self.query_local(
            "SELECT * FROM user_skills ORDER BY last_updated DESC"
        )

    def get_skill_summary(self) -> dict:
        """获取技能评估摘要"""
        rows = self.query_local(
            "SELECT skill_domain, skill_level, hours_spent, growth_trend FROM user_skills"
        )
        domains = {}
        total_hours = 0
        for r in rows:
            domains[r["skill_domain"]] = {
                "level": r["skill_level"],
                "hours": r["hours_spent"] or 0,
                "trend": r["growth_trend"],
            }
            total_hours += r["hours_spent"] or 0
        return {
            "total_domains": len(rows),
            "total_hours": round(total_hours, 1),
            "domains": domains,
        }

    # ══════════════════════════════════════════════════════════
    # v6.0 新增: 技能追溯与增量合并支持
    # ══════════════════════════════════════════════════════════

    def query_user_skill(self, skill_name: str) -> Optional[dict]:
        """
        查询单个用户技能（用于增量合并判断）
        
        Args:
            skill_name: 技能名称（对应 skill_domain 字段）
            
        Returns:
            技能记录字典，不存在则返回 None
        """
        results = self.query_local(
            "SELECT * FROM user_skills WHERE skill_domain = ?", (skill_name,)
        )
        
        if results and len(results) > 0:
            return dict(results[0])
        
        return None

    def update_user_skill(self, skill_name: str, data: dict):
        """
        更新用户技能记录（增量合并时使用）
        
        Args:
            skill_name: 技能名称
            data: 要更新的字段字典
        """
        if not data:
            return
            
        set_clauses = []
        values = []
        
        for key, value in data.items():
            if value is not None:
                set_clauses.append(f"{key} = ?")
                values.append(value)
        
        if not set_clauses:
            return
            
        values.append(skill_name)
        
        sql = f"UPDATE user_skills SET {', '.join(set_clauses)} WHERE skill_domain = ?"
        self.query_local(sql, values)

    def insert_user_skill(self, data: dict):
        """
        新增用户技能记录
        
        Args:
            data: 技能数据字典，必须包含 skill_name
        """
        now = datetime.now().isoformat()
        
        sql = """
            INSERT INTO user_skills 
            (timestamp, skill_domain, skill_level, sub_skills, evidence,
             conversation_ids, hours_spent, growth_trend, last_updated,
             confidence, first_seen, last_seen, evidence_count,
             source_conversation_id, source_timestamp, extraction_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        self.query_local(sql, (
            now,
            data.get("skill_name", ""),
            data.get("skill_level", "beginner"),
            data.get("sub_skills", ""),
            data.get("evidence", ""),
            data.get("conversation_ids", ""),
            data.get("hours_spent", 0),
            data.get("growth_trend", "stable"),
            now,
            data.get("confidence", 0.5),
            data.get("first_seen", now),
            data.get("last_seen", now),
            data.get("evidence_count", 1),
            data.get("source_conversation_id"),
            data.get("source_timestamp", now),
            data.get("extraction_method", "unknown"),
        ))

    def query_skill_history(self, skill_name: str) -> list:
        """
        查询技能的学习轨迹（用于画像追溯）
        
        通过 source_conversation_id 关联 conversations 表，
        获取该技能在哪些对话中被观察到。
        
        Args:
            skill_name: 技能名称
            
        Returns:
            学习轨迹列表，包含时间戳和上下文信息
        """
        base_skill = self.query_user_skill(skill_name)
        
        if not base_skill:
            return []
        
        lineage = []
        
        # 基础信息
        lineage.append({
            "timestamp": base_skill.get("first_seen"),
            "event": "首次发现",
            "confidence": base_skill.get("confidence", 0.5),
            "source_conversation_id": base_skill.get("source_conversation_id"),
            "context": base_skill.get("evidence", "")[:100],
        })
        
        # 如果有关联的对话 ID，查询对话详情
        conv_id = base_skill.get("source_conversation_id")
        if conv_id:
            conv = self.query_local(
                "SELECT timestamp, summary, raw_content FROM conversations WHERE id = ?", 
                (conv_id,)
            )
            
            if conv and len(conv) > 0:
                lineage.append({
                    "timestamp": conv[0].get("timestamp"),
                    "event": "来源对话",
                    "conversation_id": conv_id,
                    "summary": conv[0].get("summary", "")[:150],
                })
        
        return lineage

    def query_all_user_skills(self) -> list:
        """查询所有用户技能（用于画像展示）"""
        return self.query_local(
            """SELECT * FROM user_skills 
               ORDER BY confidence DESC, evidence_count DESC"""
        )

    # ══════════════════════════════════════════════════════════
    # v6.0 新增: 多维度 improvement_log 支持
    # ══════════════════════════════════════════════════════════

    def insert_improvement_with_dimensions(
        self, 
        category: str, 
        dimensions: dict, 
        priority: str = "medium",
        conversations_id: int = None
    ):
        """
        插入改进建议（v6.0 增强：支持多维度 JSON 存储）
        
        Args:
            category: 分类标签
            dimensions: 多维度数据字典，可包含：
                - behavior_notes: 行为模式观察
                - communication_style: 沟通风格
                - decision_pattern: 决策模式
                - emotional_state: 情绪状态
                - mistakes: 错误记录列表
                - strengths: 优势列表
                - learning_progress: 学习进度对象
            priority: 优先级
            conversations_id: 关联的对话 ID
        """
        import json as _json
        
        sql = """
            INSERT INTO improvement_log 
            (timestamp, category, suggestion, priority, conversations_id, dimensions)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        
        suggestion = dimensions.get("suggestion", "") or dimensions.get("behavior_notes", "")
        
        self.query_local(sql, (
            datetime.now().isoformat(),
            category,
            suggestion,
            priority,
            conversations_id,
            _json.dumps(dimensions, ensure_ascii=False) if dimensions else None,
        ))

    def query_improvements_by_dimension(
        self, 
        dimension_key: str = None, 
        limit: int = 50
    ) -> list:
        """
        按维度查询改进日志
        
        Args:
            dimension_key: 维度键名（如 "mistakes", "strengths" 等）
                        为 None 时返回所有记录
            limit: 返回记录数上限
                        
        Returns:
            改进日志列表，每条记录包含解析后的 dimensions 字段
        """
        import json as _json
        
        if dimension_key:
            # 使用 JSON 函数查询特定维度
            rows = self.query_local(f"""
                SELECT * FROM improvement_log 
                WHERE json_extract(dimensions, '$.{dimension_key}') IS NOT NULL
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
        else:
            rows = self.query_local("""
                SELECT * FROM improvement_log 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
        
        # 解析 dimensions JSON 字段
        result = []
        for row in rows:
            row_dict = dict(row)
            if row_dict.get("dimensions"):
                try:
                    row_dict["dimensions_parsed"] = _json.loads(row_dict["dimensions"])
                except Exception:
                    row_dict["dimensions_parsed"] = {}
            else:
                row_dict["dimensions_parsed"] = {}
            
            result.append(row_dict)
        
        return result

    # ══════════════════════════════════════════════════════════
    # 用户技能规划（新增）
    # ══════════════════════════════════════════════════════════

    def set_skill_plan(self, domain: str, goal: str, target_level: str = "",
                       target_date: str = "", milestones: list = None):
        """设置或更新技能规划"""
        now = datetime.now().isoformat()
        existing = self.query_local(
            "SELECT id FROM user_skill_plan WHERE skill_domain = ?", (domain,)
        )
        milestones_str = json.dumps(milestones or [], ensure_ascii=False)
        if existing:
            sql = """
                UPDATE user_skill_plan
                SET goal = ?, target_level = ?, target_date = ?,
                    milestones = ?, updated_at = ?
                WHERE skill_domain = ?
            """
            self.query_local(sql, (goal, target_level, target_date or "",
                                    milestones_str, now, domain))
        else:
            sql = """
                INSERT INTO user_skill_plan
                (timestamp, skill_domain, goal, target_level, target_date,
                 milestones, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            self.query_local(sql, (now, domain, goal, target_level,
                                    target_date or "", milestones_str, now, now))

    def get_skill_plan(self, domain: str = None) -> list[dict]:
        """获取技能规划"""
        if domain:
            return self.query_local(
                "SELECT * FROM user_skill_plan WHERE skill_domain = ?", (domain,)
            )
        return self.query_local(
            "SELECT * FROM user_skill_plan WHERE status = 'active' ORDER BY updated_at DESC"
        )

    def update_skill_progress(self, domain: str, progress: str):
        """更新技能学习进度"""
        self.query_local(
            "UPDATE user_skill_plan SET current_progress = ?, updated_at = ? "
            "WHERE skill_domain = ?",
            (progress, datetime.now().isoformat(), domain),
        )

    # ══════════════════════════════════════════════════════════
    # 优化反馈
    # ══════════════════════════════════════════════════════════

    def insert_optimization_feedback(self, data: dict):
        """插入优化反馈（v4.1: 支持 conversations_id 关联）"""
        sql = """
            INSERT INTO optimization_feedback
            (timestamp, source, feedback_type, target_tool, target_rule,
             description, suggestion, priority, status, conversation_id, conversations_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.query_local(sql, (
            data.get("timestamp", datetime.now().isoformat()),
            data.get("source", "auto"),
            data.get("feedback_type", ""),
            data.get("target_tool", ""),
            data.get("target_rule", ""),
            data.get("description", ""),
            data.get("suggestion", ""),
            data.get("priority", "medium"),
            data.get("status", "pending"),
            data.get("conversation_id", ""),
            data.get("conversations_id"),
        ))

    def get_pending_optimizations(self, limit: int = 20) -> list[dict]:
        """获取待处理的优化反馈"""
        return self.query_local(
            "SELECT * FROM optimization_feedback WHERE status = 'pending' "
            "ORDER BY priority DESC, timestamp ASC LIMIT ?", (limit,)
        )

    def mark_optimization_applied(self, feedback_id: int, result: str = ""):
        """标记优化已应用"""
        self.query_local(
            "UPDATE optimization_feedback SET status = 'applied', "
            "applied_at = ?, result = ? WHERE id = ?",
            (datetime.now().isoformat(), result, feedback_id),
        )

    # ══════════════════════════════════════════════════════════
    # 对话存档
    # ══════════════════════════════════════════════════════════

    def archive_conversation(self, data: dict):
        """
        存档完整对话（v4.1 增强：关联 conversations.id）

        Args:
            data: 必须包含 conversation_id（业务ID，非DB主键）
                  可选 conversations_id（关联 conversations 表的 id 主键）
        """
        conv_id = data.get("conversation_id", "")
        existing = self.query_local(
            "SELECT id FROM conversation_archive WHERE conversation_id = ?", (conv_id,)
        )
        if existing:
            return existing[0]

        conversations_id = data.get("conversations_id")  # v4.1: 关联 conversations.id

        sql = """
            INSERT INTO conversation_archive
            (timestamp, source, client, conversation_id, conversations_id,
             raw_content, summary, skill_domains, complexity, tool_calls,
             user_feedback, analyzed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.query_local(sql, (
            data.get("timestamp", datetime.now().isoformat()),
            data.get("source", "unknown"),
            data.get("client", "unknown"),
            conv_id,
            conversations_id,
            data.get("raw_content", ""),
            data.get("summary", ""),
            data.get("skill_domains", ""),
            data.get("complexity", "simple"),
            data.get("tool_calls", ""),
            data.get("user_feedback", ""),
            data.get("analyzed", 0),
        ))

    def get_unanalyzed_conversations(self, limit: int = 50) -> list[dict]:
        """获取未分析的对话（v4.1: 关联 conversations 表获取完整上下文）"""
        return self.query_local(
            "SELECT ca.*, c.topic as conv_topic, c.task_type as conv_task_type "
            "FROM conversation_archive ca "
            "LEFT JOIN conversations c ON ca.conversations_id = c.id "
            "WHERE ca.analyzed = 0 "
            "ORDER BY ca.timestamp ASC LIMIT ?", (limit,)
        )

    def mark_conversation_analyzed(self, archive_id: int, skill_domains: str = "",
                                     complexity: str = ""):
        """
        标记对话已分析（v4.3: 同时标记 conversations.analyzed=1）

        写入 conversation_archive.analyzed=1 并同时更新 conversations.analyzed=1，
        保证两张表的 analyzed 状态一致。
        """
        self.query_local(
            "UPDATE conversation_archive SET analyzed = 1, "
            "skill_domains = ?, complexity = ? WHERE id = ?",
            (skill_domains, complexity, archive_id),
        )
        # 同时更新关联的 conversations 表的 analyzed 和 skill_domains
        archive_row = self.query_local(
            "SELECT conversations_id FROM conversation_archive WHERE id = ?", (archive_id,)
        )
        if archive_row and archive_row[0].get("conversations_id"):
            self.query_local(
                "UPDATE conversations SET analyzed = 1, skill_domains = ?, complexity = ? WHERE id = ?",
                (skill_domains, complexity, archive_row[0]["conversations_id"]),
            )

    # ══════════════════════════════════════════════════════════
    # 版本历史（新增）
    # ══════════════════════════════════════════════════════════

    def record_version(self, version: str, previous_version: str = "",
                       change_summary: str = "", changelog: str = "",
                       tools_count: int = 0, triggered_by: str = "startup",
                       diff_detail: str = "", optimize_point: str = "",
                       bug_fix: str = "", new_feature: str = "",
                       data_change: str = ""):
        """记录版本变更（v4.2: 扩充结构化字段）"""
        sql = """
            INSERT INTO version_history
            (timestamp, version, previous_version, change_summary, changelog,
             tools_count, triggered_by, diff_detail, optimize_point,
             bug_fix, new_feature, data_change)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.query_local(sql, (
            datetime.now().isoformat(),
            version,
            previous_version,
            change_summary,
            changelog,
            tools_count,
            triggered_by,
            diff_detail,
            optimize_point,
            bug_fix,
            new_feature,
            data_change,
        ))

    def get_version_history(self, limit: int = 20) -> list[dict]:
        """获取版本历史"""
        return self.query_local(
            "SELECT * FROM version_history ORDER BY timestamp DESC LIMIT ?", (limit,)
        )

    def get_latest_version(self) -> Optional[str]:
        """获取最新记录的版本号"""
        rows = self.query_local(
            "SELECT version FROM version_history ORDER BY timestamp DESC LIMIT 1"
        )
        return rows[0]["version"] if rows else None

    # ══════════════════════════════════════════════════════════
    # MCP 工具注册表（新增）
    # ══════════════════════════════════════════════════════════

    def register_tool(self, tool_name: str, module: str = "",
                      description: str = "", version: str = ""):
        """注册 MCP 工具"""
        existing = self.query_local(
            "SELECT id FROM mcp_tool_registry WHERE tool_name = ?", (tool_name,)
        )
        now = datetime.now().isoformat()
        if existing:
            self.query_local(
                "UPDATE mcp_tool_registry SET module = ?, description = ?, "
                "version_registered = ? WHERE tool_name = ?",
                (module, description, version, tool_name),
            )
        else:
            sql = """
                INSERT INTO mcp_tool_registry
                (timestamp, tool_name, module, description, version_registered)
                VALUES (?, ?, ?, ?, ?)
            """
            self.query_local(sql, (now, tool_name, module, description, version))

    def record_tool_call(self, tool_name: str):
        """记录工具调用次数（工具不存在时自动注册）"""
        now = datetime.now().isoformat()
        # 先尝试更新
        result = self.query_local(
            "UPDATE mcp_tool_registry SET call_count = call_count + 1, "
            "last_called = ? WHERE tool_name = ?",
            (now, tool_name),
        )
        # query_local 对非 SELECT 返回 [{"affected_rows": N, "last_id": N}]
        # 所以需要检查 affected_rows 而非直接判空列表
        affected = result[0].get("affected_rows", 0) if result else 0
        if affected == 0:
            self.query_local(
                "INSERT OR IGNORE INTO mcp_tool_registry "
                "(timestamp, tool_name, module, description, version_registered, "
                "last_called, call_count, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 'active')",
                (now, tool_name, "auto-discovered", f"MCP工具: {tool_name}", "", now),
            )

    def get_registered_tools(self) -> list[dict]:
        """获取所有已注册的工具（仅 active）"""
        return self.query_local(
            "SELECT * FROM mcp_tool_registry WHERE status = 'active' "
            "ORDER BY tool_name ASC"
        )

    def get_all_tools(self) -> list[dict]:
        """获取所有工具（含 disabled）"""
        return self.query_local(
            "SELECT * FROM mcp_tool_registry ORDER BY call_count DESC"
        )

    def get_tool_stats(self) -> dict:
        """获取工具统计"""
        rows = self.query_local(
            "SELECT COUNT(*) as total, SUM(call_count) as total_calls "
            "FROM mcp_tool_registry WHERE status = 'active'"
        )
        if rows:
            return {
                "total_tools": rows[0]["total"] or 0,
                "total_calls": rows[0]["total_calls"] or 0,
            }
        return {"total_tools": 0, "total_calls": 0}

    def update_tool_status(self, tool_name: str, status: str):
        """更新工具状态（active/disabled/deprecated）"""
        self.query_local(
            "UPDATE mcp_tool_registry SET status = ? WHERE tool_name = ?",
            (status, tool_name),
        )

    def batch_update_tool_status(self, tool_names: list[str], status: str) -> int:
        """批量更新工具状态，返回影响行数"""
        count = 0
        for name in tool_names:
            self.query_local(
                "UPDATE mcp_tool_registry SET status = ? WHERE tool_name = ?",
                (status, name),
            )
            count += 1
        return count

    def get_zero_usage_tools(self) -> list[dict]:
        """获取零使用工具列表"""
        return self.query_local(
            "SELECT * FROM mcp_tool_registry "
            "WHERE call_count = 0 AND status = 'active' "
            "ORDER BY tool_name ASC"
        )

    # ══════════════════════════════════════════════════════════
    # 进化日志
    # ══════════════════════════════════════════════════════════

    def log_evolution(self, change_type: str, description: str,
                      files_changed: str = "", version: str = "",
                      success: bool = True, conversations_id: int = None):
        """记录进化日志（v4.2: 支持 conversations_id 关联）"""
        sql = """
            INSERT INTO evolution_log
            (timestamp, version, change_type, description, files_changed, success, conversations_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        self.query_local(sql, (
            datetime.now().isoformat(),
            version,
            change_type,
            description,
            files_changed,
            1 if success else 0,
            conversations_id,
        ))

    def get_evolution_history(self, limit: int = 50) -> list[dict]:
        """获取进化历史"""
        return self.query_local(
            "SELECT * FROM evolution_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        )

    # ══════════════════════════════════════════════════════════
    # 领域统计
    # ══════════════════════════════════════════════════════════

    def get_domain_stats(self) -> list[dict]:
        """获取领域统计"""
        return self.query_local("""
            SELECT skill_domain, COUNT(*) as cnt, SUM(hours_spent) as total_hours
            FROM user_skills
            GROUP BY skill_domain
            ORDER BY total_hours DESC
        """)

    # ══════════════════════════════════════════════════════════
    # v4.1: 跨表关联查询 — 以 conversations.id 为主键关联
    # ══════════════════════════════════════════════════════════

    def get_conversation_with_relations(self, conversations_id: int) -> dict:
        """
        以 conversations.id 为主键，关联查询全链路数据

        v4.2: 补充 evolution_log 和 improvement_log 关联

        Returns:
            {
                "conversation": {...},
                "archive": {...},
                "optimization_feedbacks": [...],
                "evolution_logs": [...],
                "improvement_logs": [...],
                "related_skills": [...]
            }
        """
        conv = self.query_local(
            "SELECT * FROM conversations WHERE id = ?", (conversations_id,)
        )
        if not conv:
            return {}

        archive = self.query_local(
            "SELECT * FROM conversation_archive WHERE conversations_id = ?",
            (conversations_id,)
        )

        feedbacks = self.query_local(
            "SELECT * FROM optimization_feedback WHERE conversations_id = ?",
            (conversations_id,)
        )

        # v4.2: 关联 evolution_log
        evo_logs = self.query_local(
            "SELECT * FROM evolution_log WHERE conversations_id = ?",
            (conversations_id,)
        )

        # v4.2: 关联 improvement_log
        imp_logs = self.query_local(
            "SELECT * FROM improvement_log WHERE conversations_id = ?",
            (conversations_id,)
        )

        # 通过 conversation_archive.conversation_id 查找关联的 user_skills
        conv_biz_id = conv[0].get("conversation_id", "")
        skills = self.query_local(
            "SELECT * FROM user_skills WHERE conversation_ids LIKE ?",
            (f"%{conv_biz_id}%",)
        )

        return {
            "conversation": conv[0],
            "archive": archive[0] if archive else None,
            "optimization_feedbacks": feedbacks,
            "evolution_logs": evo_logs,
            "improvement_logs": imp_logs,
            "related_skills": skills,
        }

    def get_unanalyzed_archives_count(self) -> int:
        """获取未分析的存档数量"""
        rows = self.query_local(
            "SELECT COUNT(*) as cnt FROM conversation_archive WHERE analyzed = 0"
        )
        return rows[0]["cnt"] if rows else 0

    def get_feedback_stats(self) -> dict:
        """获取优化反馈统计（按状态、类型分组）"""
        by_status = self.query_local("""
            SELECT status, COUNT(*) as cnt FROM optimization_feedback
            GROUP BY status
        """)
        by_type = self.query_local("""
            SELECT feedback_type, COUNT(*) as cnt FROM optimization_feedback
            GROUP BY feedback_type
        """)
        return {
            "total": sum(r["cnt"] for r in by_status),
            "by_status": {r["status"]: r["cnt"] for r in by_status},
            "by_type": {r["feedback_type"]: r["cnt"] for r in by_type},
        }

    def close(self):
        """关闭所有数据库连接"""
        if self._local_conn:
            self._local_conn.close()
        if self._shared_conn:
            self._shared_conn.close()


def get_db() -> Database:
    return Database()