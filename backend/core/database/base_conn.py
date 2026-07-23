"""
devPartner 数据库模块 v9.5.5
===========================
v9.5.5 变更：
  - ★ 所有列直接写入 DDL，删除所有 ALTER TABLE 补列代码
  - ★ 删除所有迁移方法（_migrate_old_tables/_migrate_text_to_json/...等 9 个方法）
  - ★ user_skills DDL 补齐 7 个追溯字段
  - ★ improvement_log DDL 补齐 dimensions 字段
  - ★ conversations DDL 补齐 status/total_steps/.../ai_analysis 等 11 个字段
  - ★ 删除 7 个死方法
  - ★ 删除 version_history/mcp_tool_registry 表（v9.5.4 已删 DDL，v9.5.5 确认无残留）
  - ★ 数据库重建策略：DROP 旧文件 → 重新创建

v5.0 核心架构：
  - conversation_steps 表（步骤化异步处理）
  - knowledge_points 表（技能知识点有序落地）
  - task_queue 表（异步任务优先级调度）
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    """
    线程安全的 SQLite 数据库管理器

    v5.3 并发优化：
      - 读写锁分离：读不互斥（利用 WAL 多读并发），写串行化（SQLite 单写限制）
      - init_local 仍用 _local_lock 保护一次性初始化
      - 写操作用 _write_lock 串行，避免 SQLITE_BUSY
    """

    _local_lock = threading.Lock()  # 保护 init_local 一次性初始化
    _write_lock = threading.Lock()  # 保护写操作串行化（SQLite 单写）
    _shared_lock = threading.Lock()  # 保护 shared 连接

    def __init__(self):
        self._local_conn: sqlite3.Connection | None = None
        self._shared_conn: sqlite3.Connection | None = None

    def init_local(self, db_path: str):
        """初始化本地数据库，始终启用 WAL 模式以提升写入性能 + FK 约束"""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._local_lock:
            # v9.5.5: 检测旧 schema — 如果数据库存在但包含废弃列，删除重建
            actual_path = db_path
            if Path(db_path).exists() and self._check_schema_incompatible(db_path):
                print("[DB] 检测到旧 schema 数据库，尝试删除重建...")
                deleted = False
                try:
                    Path(db_path).unlink()
                    deleted = True
                except PermissionError:
                    # 文件被锁，尝试用新文件名
                    import uuid

                    actual_path = str(
                        Path(db_path).parent / f"devpartner_v955_{uuid.uuid4().hex[:8]}.db"
                    )
                    print(f"[DB] 旧文件被占用，使用新数据库: {actual_path}")
                    print("[DB] 提示: 下次重启前请手动删除旧文件 data/databases/devpartner.db")
                except Exception as e:
                    print(f"[DB] 删除旧数据库失败: {e}，使用新数据库")
                    import uuid

                    actual_path = str(
                        Path(db_path).parent / f"devpartner_v955_{uuid.uuid4().hex[:8]}.db"
                    )
                if deleted:
                    print("[DB] 旧数据库已删除，将创建全新数据库")

            self._local_conn = sqlite3.connect(actual_path, check_same_thread=False)
            self._local_conn.row_factory = sqlite3.Row

            self._local_conn.execute("PRAGMA journal_mode=WAL")
            self._local_conn.execute("PRAGMA synchronous=NORMAL")
            self._local_conn.execute("PRAGMA wal_autocheckpoint=1000")
            self._local_conn.execute("PRAGMA foreign_keys=ON")

            # 建表（CREATE IF NOT EXISTS，幂等安全）
            self._create_local_tables()

            # v9.5.5: 删除所有迁移逻辑 — DDL 已包含所有列，无需任何迁移
            from foundation.config.app_settings import get_project_version

            current_version = get_project_version()
            self._set_schema_version(current_version)
            print(f"[DB] Schema 初始化完成 → {current_version}")

    def _check_schema_incompatible(self, db_path: str) -> bool:
        """
        v9.5.5: 检测数据库 schema 是否与当前 DDL 兼容。

        如果 conversations 表包含 priority 列（v9.5.5 已从 DDL 删除），
        说明是旧 schema，需要重建。
        """
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 检查 conversations 表是否包含已废弃的 priority 列
            cursor.execute("PRAGMA table_info(conversations)")
            conv_cols = {row[1] for row in cursor.fetchall()}
            if "priority" in conv_cols:
                conn.close()
                return True  # 旧 schema，需要重建

            conn.close()
            return False
        except Exception:
            return False  # 数据库可能损坏，让后续建表流程处理

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

        # ════════════════════════════════════════════════════════════════
        # 表: conversations — 核心对话记录表
        # 用途: 存储每次对话的元信息（主题、类型等）
        # v9.5.5: DDL 补齐所有补列字段，删除所有 ALTER TABLE 补列代码
        # 字段:
        #   id               INTEGER  自增主键
        #   conversation_id  TEXT     全局唯一对话标识（UUID）
        #   timestamp        TEXT     对话创建时间（ISO 8601）
        #   client           TEXT     客户端标识（codebuddy/cursor/...）
        #   topic            TEXT     对话主题（一句话）
        #   task_type        TEXT     任务类型（debug/design/code_change/learn/deploy/general）
        #   user_intent      TEXT     用户意图描述
        #   self_reflection  TEXT     AI 复盘反思
        #   complexity       TEXT     复杂度（simple/medium/complex）
        #   analyzed         INTEGER  是否已完成用户画像分析（0/1）
        #   status           TEXT     状态（active/completed/failed）
        #   total_steps      INTEGER  总步骤数
        #   completed_steps  INTEGER  已完成步骤数
        #   created_at       TEXT     创建时间
        #   updated_at       TEXT     更新时间
        #   completed_at     TEXT     完成时间
        #   summary_generated INTEGER 总结是否已生成（0/1）
        #   system_id        TEXT     多系统隔离标识
        #   user_raw_input   TEXT     用户原始输入文本
        #   archive_tier     TEXT     归档层级（hot/warm/cold/archived）
        #   ai_analysis      TEXT     AI 对用户意图的分析推理过程
        # ════════════════════════════════════════════════════════════════
        # v9.5.3: 删除废弃字段 actions/skill_domains/feedback_type/behavior_signals
        # v9.2: 删除废弃字段 problems/solutions/decisions/files_touched/thinking_steps/raw_json
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT UNIQUE,
                timestamp TEXT NOT NULL,
                client TEXT DEFAULT 'unknown',
                topic TEXT,
                task_type TEXT,
                user_intent TEXT,
                self_reflection TEXT,
                complexity TEXT DEFAULT 'simple',
                analyzed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                total_steps INTEGER DEFAULT 0,
                completed_steps INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                summary_generated INTEGER DEFAULT 0,
                system_id TEXT DEFAULT 'default',
                user_raw_input TEXT DEFAULT '',
                archive_tier TEXT DEFAULT 'hot',
                ai_analysis TEXT DEFAULT ''
            )
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: evolution_log — 进化日志表
        # 用途: 记录每次系统自我进化的变更（自动优化/代码变更/配置更新）
        # 字段:
        #   id               INTEGER  自增主键
        #   timestamp        TEXT     变更时间
        #   version          TEXT     触发版本号
        #   change_type      TEXT     变更类型（auto_optimize/code_change/config/...）
        #   description      TEXT     变更描述
        #   files_changed    TEXT     变更的文件列表
        #   success          INTEGER  是否成功（0/1）
        #   conversations_id INTEGER  关联 conversations.id（FK）
        # ════════════════════════════════════════════════════════════════
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
        # v9.5.5 技术审查修复: 原此处有一个 `CREATE INDEX ... ON improvement_log(status)`，
        # 但 improvement_log 表此时尚未创建，在全新/重建数据库上会触发 OperationalError 中断初始化。
        # 该索引的正确版本已在 improvement_log 建表后创建（见下方），此处删除重复定义。

        # ════════════════════════════════════════════════════════════════
        # 表: improvement_log — 系统自改进日志表
        # 用途: 记录 AI 分析生成的系统改进建议（与 optimization_feedback 分工：系统 vs 用户）
        # 字段:
        #   id               INTEGER  自增主键
        #   timestamp        TEXT     记录时间
        #   category         TEXT     类别（system_issue/decision/user_insight/self_improvement）
        #   suggestion       TEXT     改进建议
        #   priority         TEXT     优先级（high/medium/low）
        #   status           TEXT     状态（pending → in_progress → applied/rejected）
        #   applied_at       TEXT     应用时间
        #   result           TEXT     应用结果
        #   conversations_id INTEGER  关联 conversations.id（FK）
        #   dimensions       TEXT     多维度数据（JSON）
        # ════════════════════════════════════════════════════════════════
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
                dimensions TEXT,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_improvement_log_status
            ON improvement_log(status)
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: user_skills — 用户技能表
        # 用途: 记录用户已掌握的技术技能及其熟练度
        # v9.3: 新增 skill_name 字段，skill_domain 回归"领域"语义
        # v9.5.5: DDL 补齐 7 个追溯字段（confidence/first_seen/last_seen/
        #          evidence_count/source_conversation_id/source_timestamp/extraction_method）
        # 字段:
        #   id                    INTEGER  自增主键
        #   timestamp             TEXT     记录时间
        #   skill_domain          TEXT     技能领域（Python/前端/AI/DevOps/数据库/架构/...）
        #   skill_name            TEXT     具体技能名称（如"FastAPI"、"React Hooks"）
        #   skill_level           TEXT     熟练度（beginner/intermediate/advanced/expert）
        #   sub_skills            TEXT     子技能列表
        #   evidence              TEXT     技能证据（观察来源）
        #   conversation_ids      TEXT     关联的对话ID列表
        #   hours_spent           REAL     累计投入时间（小时）
        #   growth_trend          TEXT     成长趋势（stable/improving/declining）
        #   last_updated          TEXT     最后更新时间
        #   confidence            REAL     置信度（0~1）
        #   first_seen            TEXT     首次发现时间
        #   last_seen             TEXT     最近观察到的时间
        #   evidence_count        INTEGER  证据累计次数
        #   source_conversation_id TEXT    来源对话ID
        #   source_timestamp      TEXT     来源时间戳
        #   extraction_method     TEXT     提取方式（llm/manual/heuristic）
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                skill_domain TEXT NOT NULL,
                skill_name TEXT DEFAULT '',
                skill_level TEXT DEFAULT 'beginner',
                sub_skills TEXT,
                evidence TEXT,
                conversation_ids TEXT,
                hours_spent REAL DEFAULT 0,
                growth_trend TEXT DEFAULT 'stable',
                last_updated TEXT,
                confidence REAL DEFAULT 0.5,
                first_seen TEXT,
                last_seen TEXT,
                evidence_count INTEGER DEFAULT 1,
                source_conversation_id TEXT,
                source_timestamp TEXT,
                extraction_method TEXT DEFAULT 'unknown'
            )
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: user_skill_plan — 用户技能规划表
        # 用途: 记录用户的学习目标与进度追踪
        # 字段:
        #   id               INTEGER  自增主键
        #   timestamp        TEXT     记录时间
        #   skill_domain     TEXT     技能领域
        #   goal             TEXT     学习目标
        #   target_level     TEXT     目标级别
        #   target_date      TEXT     目标达成日期
        #   current_progress TEXT     当前进度描述
        #   milestones       JSON     里程碑列表
        #   status           TEXT     状态（active/completed/paused）
        #   created_at       TEXT     创建时间
        #   updated_at       TEXT     更新时间
        # ════════════════════════════════════════════════════════════════
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

        # ════════════════════════════════════════════════════════════════
        # 表: optimization_feedback — 优化反馈表
        # 用途: 记录用户主动提交的优化反馈（与 improvement_log 分工：用户 vs 系统）
        # 字段:
        #   id               INTEGER  自增主键
        #   timestamp        TEXT     反馈时间
        #   source           TEXT     反馈来源（auto/manual/user）
        #   feedback_type    TEXT     反馈类型
        #   target_tool      TEXT     目标工具
        #   target_rule      TEXT     目标规则
        #   description      TEXT     问题描述
        #   suggestion       TEXT     改进建议
        #   priority         TEXT     优先级
        #   status           TEXT     状态（pending/in_progress/applied/rejected）
        #   applied_at       TEXT     应用时间
        #   result           TEXT     应用结果
        #   conversations_id INTEGER  关联 conversations.id（FK）
        # ════════════════════════════════════════════════════════════════
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
                conversations_id INTEGER,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_improvement_log_status
            ON improvement_log(status)
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: growth_analysis — 系统成长分析表（v8.1.0）
        # 用途: 月报触发，汇总系统优化建议，经 Dashboard 人工审核后执行
        #       取代原 conversation_engine 中的 optimization_feedback 写入流程
        # 字段:
        #   id               INTEGER  自增主键
        #   timestamp        TEXT     创建时间
        #   analysis_type    TEXT     分析类型（prompt_optimize/analysis_add/knowledge_gap/user_profile_enhance）
        #   title            TEXT     标题
        #   description      TEXT     问题描述
        #   suggestion       TEXT     优化建议
        #   related_data     JSON     关联数据（对话ID、Prompt模板等）
        #   priority         TEXT     优先级（high/medium/low）
        #   status           TEXT     审核状态（pending/approved/rejected）
        #   reviewer         TEXT     审核人
        #   review_comment   TEXT     审核意见/拒绝原因
        #   reviewed_at      TEXT     审核时间
        #   applied_at       TEXT     应用时间
        #   source           TEXT     来源（monthly_report/daily_report/manual）
        #   source_period    TEXT     分析周期（如 "2026-07"）
        #   conversations_id INTEGER  关联 conversations.id（FK）
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                analysis_type TEXT NOT NULL,
                title TEXT,
                description TEXT,
                suggestion TEXT,
                related_data JSON DEFAULT '{}',
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                reviewer TEXT,
                review_comment TEXT,
                reviewed_at TEXT,
                applied_at TEXT,
                source TEXT DEFAULT 'monthly_report',
                source_period TEXT,
                conversations_id INTEGER,
                FOREIGN KEY (conversations_id) REFERENCES conversations(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_growth_analysis_status
            ON growth_analysis(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_growth_analysis_source_period
            ON growth_analysis(source_period)
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: conversation_steps — 会话步骤表（v5.0 步骤化异步处理核心表）
        # 用途: 总分总架构的「分」环节，记录对话中每个子任务的执行状态和分析结果
        # 状态机: pending → in_progress → completed/failed/timeout → orphaned（兜底）
        # 字段:
        #   id                  INTEGER  自增主键
        #   step_id             TEXT     全局唯一步骤ID
        #   conversation_id     TEXT     所属对话ID（FK → conversations.conversation_id，CASCADE）
        #   step_order          INTEGER  步骤顺序号
        #   step_type           TEXT     步骤类型（code_change/debug/config/design/learn/deploy/general）
        #   step_name           TEXT     步骤名称
        #   status              TEXT     状态（pending/in_progress/completed/failed/timeout/orphaned）
        #   input_data          JSON     输入数据（客户端提交的步骤详情）
        #   output_data         JSON     输出数据（Worker 分析结果）
        #   error_message       TEXT     错误信息
        #   started_at          TEXT     开始执行时间
        #   completed_at        TEXT     完成时间
        #   duration_ms         INTEGER  实际耗时（毫秒）
        #   retry_count         INTEGER  重试次数
        #   max_retries         INTEGER  最大重试次数
        #   priority            INTEGER  优先级（越大越高）
        #   created_at          TEXT     创建时间
        # ════════════════════════════════════════════════════════════════
        # v9.5.3: 删除 knowledge_point_ids（knowledge_points.source_step_id 已足够）
        #         删除 conversations_id（conversation_id 已足够关联）
        # v9.2: 删除 depends_on 字段 — 从未被实际使用，始终写入空字符串
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
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                priority INTEGER DEFAULT 0,
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation_steps_created
            ON conversation_steps(created_at)
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: knowledge_points — 知识点表（v9.5.7 精简：删除 9 个无用字段）
        # 用途: 存储从对话中提取的技术知识点，支持按域/分类/标签检索
        # 字段:
        #   id                    INTEGER  自增主键
        #   knowledge_id          TEXT     全局唯一知识点ID
        #   title                 TEXT     知识点标题
        #   content               TEXT     知识点详细内容
        #   category              TEXT     分类（step_extracted/manual）
        #   domain                TEXT     技术领域（Python/SQL/...）
        #   tags                  JSON     标签列表
        #   source_id             TEXT     来源ID（step_id）
        #   confidence            REAL     置信度（0~1）
        #   difficulty            TEXT     难度（easy/medium/hard）
        #   usage_count           INTEGER  被引用次数（知识点复用统计）
        #   related_knowledge_ids TEXT     关联知识点ID列表
        #   created_at            TEXT     创建时间
        #   type                  TEXT     类型：skill/business（用于去重+导出区分）
        #   aliases               JSON     别名列表
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_points (
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

        # v9.5.7: 迁移 — 删除 knowledge_points 表 9 个无用列 + 2 个无用索引
        try:
            _kp_cols = {
                row[1] for row in cursor.execute("PRAGMA table_info(knowledge_points)").fetchall()
            }
            _kp_drop = {
                "source_type",
                "last_used_at",
                "version",
                "is_verified",
                "metadata",
                "created_by",
                "updated_at",
                "source_session_id",
                "source_step_id",
            }
            for _col in _kp_drop & _kp_cols:
                try:
                    cursor.execute(f"ALTER TABLE knowledge_points DROP COLUMN {_col}")
                except Exception:
                    pass
            # 删除废弃索引
            for _idx in ("idx_knowledge_points_source", "idx_kp_source_session"):
                try:
                    cursor.execute(f"DROP INDEX IF EXISTS {_idx}")
                except Exception:
                    pass
        except Exception:
            pass

        # ════════════════════════════════════════════════════════════════
        # 表: task_queue — 异步任务队列表（v5.0 优先级调度 + 资源控制）
        # 用途: 后台 Worker 消费的异步任务队列，支持 FIFO 调度、重试、软删除
        # 字段:
        #   id                  INTEGER  自增主键
        #   task_id             TEXT     全局唯一任务ID
        #   task_type           TEXT     任务类型（step_analysis/conversation_finalize/...）
        #   payload             JSON     任务载荷
        #   status              TEXT     状态（pending/running/completed/failed/timeout）
        #   priority            INTEGER  优先级（越大越高）
        #   max_retries         INTEGER  最大重试次数
        #   retry_count         INTEGER  当前重试次数
        #   error_message       TEXT     错误信息
        #   result              JSON     任务执行结果
        #   progress            REAL     执行进度（0~1）
        #   estimated_memory_mb INTEGER  预估内存占用
        #   actual_memory_mb    INTEGER  实际内存占用（完成后回写）
        #   queued_at           TEXT     入队时间
        #   started_at          TEXT     开始执行时间
        #   completed_at        TEXT     完成时间
        #   timeout_seconds     INTEGER  超时时间（秒）
        #   worker_id           TEXT     执行的 Worker 标识
        #   is_deleted          INTEGER  软删除标记（0/1）
        #   next_retry_at       TEXT     下次重试时间
        #   sort_order          INTEGER  FIFO 排序序号
        #   last_heartbeat      TEXT     Worker 心跳时间（v9.5.1）
        #   partial_result      TEXT     部分结果预览（v9.5.1）
        #   status_note         TEXT     状态备注（v9.5.1）
        # ════════════════════════════════════════════════════════════════
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
                timeout_seconds INTEGER DEFAULT 10800,
                worker_id TEXT,
                is_deleted INTEGER DEFAULT 0,
                next_retry_at TEXT,
                sort_order INTEGER DEFAULT 0,
                last_heartbeat TEXT,
                partial_result TEXT DEFAULT '',
                status_note TEXT DEFAULT ''
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
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_deleted
            ON task_queue(is_deleted)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_retry
            ON task_queue(status, next_retry_at)
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: connected_systems — 对接系统注册表（v8.0 多系统隔离）
        # 用途: 记录通过 MCP 对接的不同系统（Trae/Cursor/VSCode/CLI等）
        # 字段:
        #   system_id          TEXT     系统唯一标识（主键，如 'trae_main'）
        #   system_type        TEXT     系统类型（trae/cursor/vscode/cli）
        #   display_name       TEXT     显示名称
        #   project_path       TEXT     项目根路径（v9.5.3 补充）
        #   tech_stack         JSON     技术栈信息
        #   architecture       JSON     架构信息
        #   business_domains   JSON     业务领域信息
        #   maturity           TEXT     成熟度（unknown/early/growing/mature）
        #   first_connected    TEXT     首次连接时间
        #   last_active        TEXT     最近活跃时间
        #   last_seen_at       TEXT     最后出现时间（v9.5.3 补充，rest_api 使用）
        #   conversation_count INTEGER  对话总数
        #   metadata           JSON     扩展元数据
        #   project_description TEXT    项目主要作用描述（v9.5.6，用于LLM分析时的项目上下文）
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS connected_systems (
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
                project_description TEXT DEFAULT ''
            )
        """)

        # v9.5.6: 为已有数据库补列 project_description
        cursor.execute("PRAGMA table_info(connected_systems)")
        cols = {row[1] for row in cursor.fetchall()}
        if "project_description" not in cols:
            cursor.execute(
                "ALTER TABLE connected_systems ADD COLUMN project_description TEXT DEFAULT ''"
            )

        # ════════════════════════════════════════════════════════════════
        # 表: user_profile — 全局用户画像表（v8.0 每日画像合并）
        # 用途: 存储从多轮对话行为信号中提取的用户画像维度数据
        # 字段:
        #   id                INTEGER  自增主键
        #   dimension         TEXT     画像维度（如 skill_level/communication_style/...）
        #   value             TEXT     维度值
        #   confidence        REAL     置信度（0~1）
        #   evidence          TEXT     证据来源描述
        #   first_observed    TEXT     首次观察时间
        #   last_observed     TEXT     最近观察时间
        #   observation_count INTEGER  观察次数
        #   trend             TEXT     趋势（stable/rising/declining）
        #   updated_at        TEXT     更新时间
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
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

        # ════════════════════════════════════════════════════════════════
        # 表: system_context_fragments — 系统认知片段表（v8.0 渐进式系统认知）
        # 用途: 每次对话结束时提取的系统认知片段，每日合并为全局项目画像
        # 字段:
        #   id                  INTEGER  自增主键
        #   conversation_id     TEXT     来源对话ID
        #   system_id           TEXT     系统标识（默认 'default'）
        #   tech_signals        JSON     技术栈信号
        #   architecture_signals JSON    架构信号
        #   business_signals    JSON     业务领域信号
        #   new_discoveries     JSON     新发现
        #   confidence          REAL     置信度（0~1）
        #   observed_at         TEXT     观察时间
        #   merged              INTEGER  是否已合并到全局画像（0/1）
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_context_fragments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                system_id TEXT NOT NULL DEFAULT 'default',
                tech_signals JSON DEFAULT '[]',
                architecture_signals JSON DEFAULT '[]',
                business_signals JSON DEFAULT '[]',
                new_discoveries JSON DEFAULT '[]',
                confidence REAL DEFAULT 0.5,
                observed_at TEXT NOT NULL,
                merged INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scf_system_id
            ON system_context_fragments(system_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scf_merged
            ON system_context_fragments(merged)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scf_observed
            ON system_context_fragments(observed_at)
        """)

        # ════════════════════════════════════════════════════════════════
        # 表: pending_analyses — 待分析数据表（v8.0 LLM 不可用时的数据暂存）
        # 用途: LLM 不可用时，将原始分析数据暂存于此表，标记缺失的分析维度，
        #        下次定时任务优先清算历史欠账后再处理当日数据
        # 字段:
        #   id                INTEGER  自增主键
        #   analysis_type     TEXT     分析类型（daily_profile_merge/daily_system_merge）
        #   source_date       TEXT     原始数据所属日期（YYYY-MM-DD）
        #   system_id         TEXT     系统标识（system_merge 时使用）
        #   raw_data          JSON     原始分析输入数据（行为信号/认知片段等）
        #   missing_dimensions JSON    缺失的分析维度列表
        #   retry_count       INTEGER  重试次数
        #   created_at        TEXT     创建时间
        #   last_attempted_at TEXT     最近一次尝试时间
        #   status            TEXT     状态（pending/retrying/completed/failed）
        #   error_message     TEXT     最近一次失败原因
        # ════════════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_type TEXT NOT NULL,
                source_date TEXT NOT NULL,
                system_id TEXT DEFAULT 'default',
                raw_data JSON NOT NULL DEFAULT '{}',
                missing_dimensions JSON DEFAULT '[]',
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_attempted_at TEXT,
                status TEXT DEFAULT 'pending',
                error_message TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pa_status
            ON pending_analyses(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pa_type_date
            ON pending_analyses(analysis_type, source_date)
        """)

        # v9.5.5: 删除所有 ALTER TABLE 补列代码 — 所有列已在 DDL 中定义

        # meta 元数据表 — 跟踪 schema 版本
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
        cursor.execute(
            """
            INSERT INTO meta (key, value, updated_at) VALUES ('schema_version', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
            (version,),
        )
        self._local_conn.commit()

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

        # 1. 检查 conversations 表关键字段非空（v9.5.3: 移除废弃字段）
        for field in ["topic", "task_type"]:
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
        fk_tables = ["optimization_feedback", "evolution_log", "improvement_log"]
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

    def is_local_initialized(self) -> bool:
        return self._local_conn is not None

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

    # v9.2: insert_conversation 已删除 — 已被 start_conversation (conversation_engine) 替代
    # 旧方法依赖 6 个废弃字段 (problems/solutions/decisions/files_touched/thinking_steps/raw_json)

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

    def insert_improvement(
        self, category: str, suggestion: str, priority: str = "medium", conversations_id: int = None
    ):
        """插入改进建议（v4.2: 支持 conversations_id 关联）"""
        sql = """
            INSERT INTO improvement_log (timestamp, category, suggestion, priority, conversations_id)
            VALUES (?, ?, ?, ?, ?)
        """
        return self.query_local(
            sql, (datetime.now().isoformat(), category, suggestion, priority, conversations_id)
        )

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
        """
        插入或更新用户技能（v9.3 兼容旧调用）

        旧调用方式：domain 参数传入的是 skill_name（因为历史原因）
        v9.3 新调用：domain 是 skill_domain，skill_name 在 data 中
        """
        skill_name = data.get("skill_name", domain)
        now = datetime.now().isoformat()

        # 优先按 (skill_domain, skill_name) 联合查询
        existing = self.query_local(
            "SELECT id FROM user_skills WHERE skill_domain = ? AND skill_name = ?",
            (domain, skill_name),
        )
        if not existing:
            # fallback: 只按 skill_name 查
            existing = self.query_local(
                "SELECT id FROM user_skills WHERE skill_name = ? OR (skill_name = '' AND skill_domain = ?)",
                (skill_name, domain),
            )

        if existing:
            sql = """
                UPDATE user_skills
                SET skill_level = ?, sub_skills = ?, evidence = ?,
                    conversation_ids = ?, hours_spent = hours_spent + ?,
                    growth_trend = ?, last_updated = ?
                WHERE skill_domain = ? AND skill_name = ?
            """
            self.query_local(
                sql,
                (
                    data.get("skill_level", "beginner"),
                    data.get("sub_skills", ""),
                    data.get("evidence", ""),
                    data.get("conversation_ids", ""),
                    data.get("hours_spent", 0),
                    data.get("growth_trend", "stable"),
                    now,
                    domain,
                    skill_name,
                ),
            )
        else:
            sql = """
                INSERT INTO user_skills
                (timestamp, skill_domain, skill_name, skill_level, sub_skills, evidence,
                 conversation_ids, hours_spent, growth_trend, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            self.query_local(
                sql,
                (
                    now,
                    domain,
                    skill_name,
                    data.get("skill_level", "beginner"),
                    data.get("sub_skills", ""),
                    data.get("evidence", ""),
                    data.get("conversation_ids", ""),
                    data.get("hours_spent", 0),
                    data.get("growth_trend", "stable"),
                    now,
                ),
            )

    # ══════════════════════════════════════════════════════════
    # v6.0: 技能追溯与增量合并支持
    # ══════════════════════════════════════════════════════════

    def query_user_skill(self, skill_name: str, skill_domain: str = "") -> dict | None:
        """
        查询单个用户技能（用于增量合并判断）

        v9.3: 支持 skill_domain + skill_name 联合查询

        Args:
            skill_name: 技能名称（对应 skill_name 字段）
            skill_domain: 技能领域（可选，配合 skill_name 精确定位）

        Returns:
            技能记录字典，不存在则返回 None
        """
        if skill_domain:
            results = self.query_local(
                "SELECT * FROM user_skills WHERE skill_domain = ? AND skill_name = ?",
                (skill_domain, skill_name),
            )
        else:
            # 兼容旧调用：优先匹配 skill_name，fallback 到 skill_domain
            results = self.query_local(
                "SELECT * FROM user_skills WHERE skill_name = ? OR (skill_name = '' AND skill_domain = ?)",
                (skill_name, skill_name),
            )

        if results and len(results) > 0:
            return dict(results[0])

        return None

    def update_user_skill(self, skill_name: str, data: dict, skill_domain: str = ""):
        """
        更新用户技能记录（增量合并时使用）

        v9.3: 支持 skill_domain + skill_name 联合定位

        Args:
            skill_name: 技能名称
            data: 要更新的字段字典
            skill_domain: 技能领域（可选）
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

        if skill_domain:
            values.append(skill_domain)
            sql = f"UPDATE user_skills SET {', '.join(set_clauses)} WHERE skill_domain = ? AND skill_name = ?"
        else:
            sql = f"UPDATE user_skills SET {', '.join(set_clauses)} WHERE skill_name = ? OR (skill_name = '' AND skill_domain = ?)"
        self.query_local(sql, values)

    def insert_user_skill(self, data: dict):
        """
        新增用户技能记录

        v9.3: skill_domain 存领域名，skill_name 存具体技能名

        Args:
            data: 技能数据字典，必须包含 skill_name 和 skill_domain
        """
        now = datetime.now().isoformat()

        sql = """
            INSERT INTO user_skills 
            (timestamp, skill_domain, skill_name, skill_level, sub_skills, evidence,
             conversation_ids, hours_spent, growth_trend, last_updated,
             confidence, first_seen, last_seen, evidence_count,
             source_conversation_id, source_timestamp, extraction_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        self.query_local(
            sql,
            (
                now,
                data.get("skill_domain", "其他"),
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
            ),
        )

    # ══════════════════════════════════════════════════════════
    # v6.0: 多维度 improvement_log 支持
    # ══════════════════════════════════════════════════════════

    def insert_improvement_with_dimensions(
        self,
        category: str,
        dimensions: dict,
        priority: str = "medium",
        conversations_id: int = None,
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

        self.query_local(
            sql,
            (
                datetime.now().isoformat(),
                category,
                suggestion,
                priority,
                conversations_id,
                _json.dumps(dimensions, ensure_ascii=False) if dimensions else None,
            ),
        )

    # ══════════════════════════════════════════════════════════
    # 用户技能规划（新增）
    # ══════════════════════════════════════════════════════════

    def set_skill_plan(
        self,
        domain: str,
        goal: str,
        target_level: str = "",
        target_date: str = "",
        milestones: list = None,
    ):
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
            self.query_local(
                sql, (goal, target_level, target_date or "", milestones_str, now, domain)
            )
        else:
            sql = """
                INSERT INTO user_skill_plan
                (timestamp, skill_domain, goal, target_level, target_date,
                 milestones, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            self.query_local(
                sql, (now, domain, goal, target_level, target_date or "", milestones_str, now, now)
            )

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

    # v9.5.7: project_description 自动维护
    def update_project_description(self, system_id: str, description: str):
        """更新系统的项目描述（LLM 对话总结时自动优化）"""
        self.query_local(
            "UPDATE connected_systems SET project_description = ?, last_active = ? "
            "WHERE system_id = ?",
            (description, datetime.now().isoformat(), system_id),
        )

    # ══════════════════════════════════════════════════════════
    # 优化反馈
    # ══════════════════════════════════════════════════════════

    def insert_optimization_feedback(self, data: dict):
        """插入优化反馈（v7.0: 删除废弃 conversation_id 列）"""
        sql = """
            INSERT INTO optimization_feedback
            (timestamp, source, feedback_type, target_tool, target_rule,
             description, suggestion, priority, status, conversations_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.query_local(
            sql,
            (
                data.get("timestamp", datetime.now().isoformat()),
                data.get("source", "auto"),
                data.get("feedback_type", ""),
                data.get("target_tool", ""),
                data.get("target_rule", ""),
                data.get("description", ""),
                data.get("suggestion", ""),
                data.get("priority", "medium"),
                data.get("status", "pending"),
                data.get("conversations_id"),
            ),
        )

    # ══════════════════════════════════════════════════════════
    # 系统成长分析（v8.1.0 — 月报触发，Dashboard 审核）
    # ══════════════════════════════════════════════════════════

    def insert_growth_analysis(self, data: dict) -> int:
        """
        插入系统成长分析记录。

        data 字段:
          - analysis_type (必填): prompt_optimize / analysis_add / knowledge_gap / user_profile_enhance
          - title, description, suggestion
          - related_data (JSON)
          - priority, source, source_period
          - conversations_id (可选)
        """
        sql = """
            INSERT INTO growth_analysis
            (timestamp, analysis_type, title, description, suggestion,
             related_data, priority, source, source_period, conversations_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.query_local(
            sql,
            (
                data.get("timestamp", datetime.now().isoformat()),
                data.get("analysis_type", ""),
                data.get("title", ""),
                data.get("description", ""),
                data.get("suggestion", ""),
                json.dumps(data.get("related_data", {}), ensure_ascii=False),
                data.get("priority", "medium"),
                data.get("source", "monthly_report"),
                data.get("source_period", ""),
                data.get("conversations_id"),
            ),
        )
        row = self.query_local("SELECT last_insert_rowid()", ())
        return row[0][0] if row else 0

    def get_pending_growth_analysis(self, limit: int = 50) -> list[dict]:
        """获取待审核的增长分析"""
        return self.query_local(
            "SELECT * FROM growth_analysis WHERE status = 'pending' "
            "ORDER BY priority DESC, timestamp ASC LIMIT ?",
            (limit,),
        )

    def get_growth_analysis_by_period(self, source_period: str) -> list[dict]:
        """按分析周期获取增长分析"""
        return self.query_local(
            "SELECT * FROM growth_analysis WHERE source_period = ? "
            "ORDER BY priority DESC, timestamp ASC",
            (source_period,),
        )

    def review_growth_analysis(
        self, analysis_id: int, status: str, reviewer: str = "", comment: str = ""
    ) -> bool:
        """
        审核增长分析记录。

        Args:
            analysis_id: 记录 ID
            status: 'approved' 或 'rejected'
            reviewer: 审核人
            comment: 审核意见/拒绝原因
        """
        self.query_local(
            "UPDATE growth_analysis SET status = ?, reviewer = ?, "
            "review_comment = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewer, comment, datetime.now().isoformat(), analysis_id),
        )
        return True

    def apply_growth_analysis(self, analysis_id: int) -> bool:
        """标记增长分析为已应用"""
        self.query_local(
            "UPDATE growth_analysis SET applied_at = ? WHERE id = ?",
            (datetime.now().isoformat(), analysis_id),
        )
        return True

    def cleanup_growth_analysis(self, before_period: str) -> int:
        """
        清理已处理的指定周期之前的增长分析数据。

        Args:
            before_period: 清理此周期之前的数据（如 "2026-06" 清理 6月及之前）

        Returns:
            删除的记录数
        """
        cursor = self._local_conn.cursor()
        cursor.execute(
            "DELETE FROM growth_analysis "
            "WHERE status IN ('approved', 'rejected') "
            "AND source_period <= ?",
            (before_period,),
        )
        deleted = cursor.rowcount
        self._local_conn.commit()
        return deleted

    # ══════════════════════════════════════════════════════════
    # 知识点写入（v8.0: 从 conversation_engine 解耦，services 层可直接调用）
    # ══════════════════════════════════════════════════════════

    def insert_knowledge_point(
        self,
        title: str,
        content: str,
        category: str,
        domain: str,
        tags: list,
        source_id: str = "",
        kp_type: str = "skill",
        aliases: list = None,
    ) -> str | None:
        """创建知识点记录，返回 knowledge_id 或 None（v9.5.7 精简参数）"""
        import uuid

        try:
            kp_id = f"kp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            self.query_local(
                """
                INSERT INTO knowledge_points (
                    knowledge_id, title, content, category, domain,
                    tags, source_id, type, difficulty,
                    aliases, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'medium', ?, ?)
            """,
                (
                    kp_id,
                    title,
                    content,
                    category,
                    domain,
                    json.dumps(tags, ensure_ascii=False),
                    source_id,
                    kp_type,
                    json.dumps(aliases or [], ensure_ascii=False),
                    now,
                ),
            )
            return kp_id
        except Exception as e:
            logger.error(f"创建知识点失败: {e}", exc_info=True)
            return None

    # ══════════════════════════════════════════════════════════
    # 进化日志
    # ══════════════════════════════════════════════════════════

    def log_evolution(
        self,
        change_type: str,
        description: str,
        files_changed: str = "",
        version: str = "",
        success: bool = True,
        conversations_id: int = None,
    ):
        """记录进化日志（v4.2: 支持 conversations_id 关联）"""
        sql = """
            INSERT INTO evolution_log
            (timestamp, version, change_type, description, files_changed, success, conversations_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        self.query_local(
            sql,
            (
                datetime.now().isoformat(),
                version,
                change_type,
                description,
                files_changed,
                1 if success else 0,
                conversations_id,
            ),
        )

    def get_evolution_history(self, limit: int = 50) -> list[dict]:
        """获取进化历史"""
        return self.query_local(
            "SELECT * FROM evolution_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        )

    def close(self):
        """关闭所有数据库连接"""
        if self._local_conn:
            self._local_conn.close()
        if self._shared_conn:
            self._shared_conn.close()


# NOTE: 模块级单例；如需多实例隔离，后续可改为依赖注入容器。
_db_instance: Database | None = None


def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
