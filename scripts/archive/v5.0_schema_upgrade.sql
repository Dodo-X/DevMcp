-- ============================================================
-- DevPartner v5.0 Schema Upgrade Script
-- ============================================================
-- 核心改进：
--   1. ★ conversation_id 唯一约束（UUID v4）+ 自动生成
--   2. ★ 新增 conversation_steps 表（步骤化异步处理）
--   3. ★ 新增 knowledge_points 表（技能知识点有序落地）
--   4. ★ 加强外键约束（CASCADE 删除）
--   5. ★ 大字段 JSON 类型优化
--   6. ★ 新增 task_queue 表（异步任务调度）
-- 
-- 执行方式：
--   - 自动：Database._migrate_to_v50() 启动时调用
--   - 手动：sqlite3 data/databases/devpartner.db < this_script.sql
-- ============================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ══════════════════════════════════════════════════════════
-- 1. conversations 表升级：添加唯一约束 + UUID 生成
-- ══════════════════════════════════════════════════════════

-- 1.1 回填空白的 conversation_id（使用 UUID）
UPDATE conversations
SET conversation_id = 'conv_' || lower(hex(randomblob(16)))
WHERE conversation_id IS NULL OR conversation_id = '' OR conversation_id = 'unknown';

-- 1.2 创建新表（带唯一约束）
CREATE TABLE IF NOT EXISTS conversations_v5 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL UNIQUE,  -- ★ 唯一业务ID（UUID格式）
    timestamp TEXT NOT NULL,
    client TEXT DEFAULT 'unknown',
    topic TEXT,
    task_type TEXT,
    user_intent TEXT,
    status TEXT DEFAULT 'active',          -- active/completed/failed/paused
    priority TEXT DEFAULT 'medium',        -- low/medium/high/critical
    total_steps INTEGER DEFAULT 0,         -- 总步骤数
    completed_steps INTEGER DEFAULT 0,     -- 已完成步骤数
    actions JSON,
    problems TEXT,
    solutions TEXT,
    decisions TEXT,
    files_touched JSON,
    thinking_steps JSON,
    self_reflection TEXT,
    raw_json JSON,
    skill_domains JSON DEFAULT '{}',
    complexity TEXT DEFAULT 'simple',
    feedback_type JSON DEFAULT '{}',
    analyzed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT                     -- 任务完成时间
);

-- 1.3 迁移数据到新表
INSERT OR IGNORE INTO conversations_v5 (
    id, conversation_id, timestamp, client, topic, task_type,
    user_intent, status, priority, actions, problems, solutions,
    decisions, files_touched, thinking_steps, self_reflection,
    raw_json, skill_domains, complexity, feedback_type, analyzed,
    created_at, updated_at
)
SELECT 
    id, 
    CASE WHEN conversation_id IS NULL OR conversation_id = '' THEN 'conv_' || lower(hex(randomblob(16))) ELSE conversation_id END,
    timestamp, client, topic, task_type,
    user_intent, 'active', 'medium', actions, problems, solutions,
    decisions, files_touched, thinking_steps, self_reflection,
    raw_json, skill_domains, complexity, feedback_type, analyzed,
    timestamp, timestamp
FROM conversations;

-- 1.4 替换旧表
DROP TABLE IF EXISTS conversations;
ALTER TABLE conversations_v5 RENAME TO conversations;

-- 1.5 创建索引（加速查询）
CREATE INDEX IF NOT EXISTS idx_conversations_conversation_id ON conversations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_client ON conversations(client);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC);


-- ══════════════════════════════════════════════════════════
-- 2. 新增 conversation_steps 表（★ 核心功能）
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS conversation_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id TEXT NOT NULL UNIQUE,           -- 步骤唯一ID（conv_xxx_step_001）
    conversation_id TEXT NOT NULL,          -- 关联会话业务ID
    step_order INTEGER NOT NULL,            -- 执行顺序（1,2,3...）
    step_type TEXT NOT NULL,                -- 类型：analysis/knowledge_gen/user_profile/system_optimize
    step_name TEXT,                         -- 步骤名称（如："对话内容分析"）
    status TEXT DEFAULT 'pending',          -- pending/running/completed/failed/skipped
    input_data JSON,                        -- 输入参数（JSON）
    output_data JSON,                       -- 输出结果（JSON）
    error_message TEXT,                     -- 错误信息
    knowledge_point_ids TEXT,               -- 关联的知识点ID列表（逗号分隔）
    started_at TEXT,                        -- 开始时间
    completed_at TEXT,                      -- 完成时间
    duration_ms INTEGER,                    -- 执行耗时（毫秒）
    retry_count INTEGER DEFAULT 0,          -- 重试次数
    max_retries INTEGER DEFAULT 3,          -- 最大重试次数
    priority INTEGER DEFAULT 0,             -- 优先级（数字越大越优先）
    depends_on TEXT,                        -- 依赖的步骤ID（逗号分隔）
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- 步骤表索引
CREATE INDEX IF NOT EXISTS idx_conversation_steps_conv_id ON conversation_steps(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_steps_status ON conversation_steps(status);
CREATE INDEX IF NOT EXISTS idx_conversation_steps_order ON conversation_steps(conversation_id, step_order);


-- ══════════════════════════════════════════════════════════
-- 3. 新增 knowledge_points 表（★ 知识库落地）
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS knowledge_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id TEXT NOT NULL UNIQUE,      -- 知识点唯一ID（kp_YYYYMMDD_HHMMSS_uuid）
    title TEXT NOT NULL,                    -- 知识点标题
    content TEXT NOT NULL,                  -- 知识点详细内容
    category TEXT NOT NULL,                 -- 分类：skill/concept/pattern/troubleshooting/best_practice
    domain TEXT NOT NULL,                   -- 技术领域（Python/前端/DevOps/AI等）
    tags JSON DEFAULT '[]',                 -- 标签列表
    source_type TEXT,                       -- 来源：conversation/step/manual/import
    source_id TEXT,                         -- 来源ID（conversation_id 或 step_id）
    confidence REAL DEFAULT 0.8,            -- 置信度（0.0-1.0）
    difficulty TEXT DEFAULT 'medium',       -- 难度：easy/medium/hard/expert
    usage_count INTEGER DEFAULT 0,          -- 被引用次数
    last_used_at TEXT,                      -- 最后使用时间
    related_knowledge_ids TEXT,             -- 相关知识点ID（逗号分隔）
    version INTEGER DEFAULT 1,              -- 版本号（支持迭代更新）
    is_verified INTEGER DEFAULT 0,          -- 是否已验证（人工确认）
    metadata JSON DEFAULT '{}',             -- 扩展元数据
    created_by TEXT DEFAULT 'system',       -- 创建者：system/user/ai
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 知识点表索引
CREATE INDEX IF NOT EXISTS idx_knowledge_points_domain ON knowledge_points(domain);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_category ON knowledge_points(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_source ON knowledge_points(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_tags ON knowledge_points(tags);


-- ══════════════════════════════════════════════════════════
-- 4. 新增 task_queue 表（★ 异步任务调度）
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,           -- 任务唯一ID
    task_type TEXT NOT NULL,                -- 任务类型：conversation_analysis/knowledge_extraction/profile_update
    payload JSON NOT NULL,                  -- 任务载荷（JSON）
    status TEXT DEFAULT 'pending',          -- pending/queued/running/completed/failed/cancelled
    priority INTEGER DEFAULT 0,             -- 优先级（越大越优先）
    max_retries INTEGER DEFAULT 3,          -- 最大重试次数
    retry_count INTEGER DEFAULT 0,          -- 当前重试次数
    error_message TEXT,                     -- 最后错误信息
    result JSON,                            -- 执行结果（JSON）
    progress REAL DEFAULT 0.0,             -- 进度百分比（0.0-1.0）
    estimated_memory_mb INTEGER DEFAULT 0, -- 预估内存占用（MB）
    actual_memory_mb INTEGER DEFAULT 0,    -- 实际内存占用（MB）
    queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    timeout_seconds INTEGER DEFAULT 300,    -- 超时时间（秒）
    worker_id TEXT                          -- 执行的工作线程ID
);

-- 任务队列表索引
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_task_queue_priority ON task_queue(priority DESC);
CREATE INDEX IF NOT EXISTS idx_task_queue_type ON task_queue(task_type);


-- ══════════════════════════════════════════════════════════
-- 5. 升级现有表的外键约束
-- ══════════════════════════════════════════════════════════

-- 5.1 conversation_archive 添加 CASCADE 删除
CREATE TABLE IF NOT EXISTS conversation_archive_v5 (
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversations_id) REFERENCES conversations(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO conversation_archive_v5 SELECT * FROM conversation_archive;
DROP TABLE IF EXISTS conversation_archive;
ALTER TABLE conversation_archive_v5 RENAME TO conversation_archive;

-- 5.2 optimization_feedback 添加 CASCADE
CREATE TABLE IF NOT EXISTS optimization_feedback_v5 (
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversations_id) REFERENCES conversations(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO optimization_feedback_v5 SELECT * FROM optimization_feedback;
DROP TABLE IF EXISTS optimization_feedback;
ALTER TABLE optimization_feedback_v5 RENAME TO optimization_feedback;

-- 5.3 evolution_log 添加 CASCADE
CREATE TABLE IF NOT EXISTS evolution_log_v5 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    version TEXT DEFAULT '',
    change_type TEXT,
    description TEXT,
    files_changed TEXT,
    success INTEGER DEFAULT 1,
    conversations_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversations_id) REFERENCES conversations(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO evolution_log_v5 SELECT * FROM evolution_log;
DROP TABLE IF EXISTS evolution_log;
ALTER TABLE evolution_log_v5 RENAME TO evolution_log;

-- 5.4 improvement_log 添加 CASCADE
CREATE TABLE IF NOT EXISTS improvement_log_v5 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    category TEXT,
    suggestion TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'pending',
    applied_at TEXT,
    result TEXT,
    conversations_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversations_id) REFERENCES conversations(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO improvement_log_v5 SELECT * FROM improvement_log;
DROP TABLE IF EXISTS improvement_log;
ALTER TABLE improvement_log_v5 RENAME TO improvement_log;


-- ══════════════════════════════════════════════════════════
-- 6. 数据完整性校验与修复
-- ══════════════════════════════════════════════════════════

-- 6.1 清理无效外键引用
UPDATE conversation_archive SET conversations_id = NULL WHERE conversations_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM conversations WHERE id = conversations_id);
UPDATE optimization_feedback SET conversations_id = NULL WHERE conversations_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM conversations WHERE id = conversations_id);
UPDATE evolution_log SET conversations_id = NULL WHERE conversations_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM conversations WHERE id = conversations_id);
UPDATE improvement_log SET conversations_id = NULL WHERE conversations_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM conversations WHERE id = conversations_id);

-- 6.2 统计信息输出
SELECT '=== v5.0 Schema Upgrade Complete ===' AS message;
SELECT 'conversations' AS table_name, COUNT(*) AS total FROM conversations UNION ALL
SELECT 'conversation_steps', COUNT(*) FROM conversation_steps UNION ALL
SELECT 'knowledge_points', COUNT(*) FROM knowledge_points UNION ALL
SELECT 'task_queue', COUNT(*) FROM task_queue UNION ALL
SELECT 'conversation_archive', COUNT(*) FROM conversation_archive UNION ALL
SELECT 'optimization_feedback', COUNT(*) FROM optimization_feedback UNION ALL
SELECT 'evolution_log', COUNT(*) FROM evolution_log UNION ALL
SELECT 'improvement_log', COUNT(*) FROM improvement_log;

-- ============================================================
-- 执行完毕！请重启 DevPartner 服务以应用更改。
-- ============================================================