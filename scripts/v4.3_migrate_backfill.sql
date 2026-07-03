-- ============================================================
-- DevPartner v4.3 存量数据迁移 SQL 脚本
-- ============================================================
-- 用途：补全历史数据中的 conversations_id 外键关联、
--       设置 conversations.analyzed 标记、清理无效 FK 引用
-- 执行方式：MCP 启动时自动执行（_backfill_conversations_id）
-- 手动执行：sqlite3 data/databases/devpartner.db < this_script.sql
-- ============================================================

-- 启用外键约束
PRAGMA foreign_keys = ON;

-- ── 1. 回填 conversation_archive 的 conversations_id ──
-- 通过 conversation_id (业务ID) 匹配 conversations.id
UPDATE conversation_archive
SET conversations_id = (
    SELECT c.id FROM conversations c
    WHERE c.conversation_id = conversation_archive.conversation_id
      AND c.conversation_id != ''
)
WHERE conversations_id IS NULL
  AND conversation_id IS NOT NULL
  AND conversation_id != '';

-- ── 2. 回填 optimization_feedback 的 conversations_id ──
UPDATE optimization_feedback
SET conversations_id = (
    SELECT c.id FROM conversations c
    WHERE c.conversation_id = optimization_feedback.conversation_id
      AND c.conversation_id != ''
)
WHERE conversations_id IS NULL
  AND conversation_id IS NOT NULL
  AND conversation_id != '';

-- ── 3. 回填 evolution_log 的 conversations_id ──
-- 通过时间戳范围估算 — 取 timestamp 之前最近的 conversation
UPDATE evolution_log
SET conversations_id = (
    SELECT c.id FROM conversations c
    WHERE c.timestamp <= evolution_log.timestamp
    ORDER BY c.timestamp DESC LIMIT 1
)
WHERE conversations_id IS NULL;

-- ── 4. 回填 improvement_log 的 conversations_id ──
UPDATE improvement_log
SET conversations_id = (
    SELECT c.id FROM conversations c
    WHERE c.timestamp <= improvement_log.timestamp
    ORDER BY c.timestamp DESC LIMIT 1
)
WHERE conversations_id IS NULL;

-- ── 5. 清理无效 FK 引用（conversations_id 指向不存在的记录）──
-- 注意：FK 约束启用后，这些行会阻止 INSERT 操作
UPDATE conversation_archive
SET conversations_id = NULL
WHERE conversations_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM conversations WHERE id = conversation_archive.conversations_id
  );

UPDATE optimization_feedback
SET conversations_id = NULL
WHERE conversations_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM conversations WHERE id = optimization_feedback.conversations_id
  );

UPDATE evolution_log
SET conversations_id = NULL
WHERE conversations_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM conversations WHERE id = evolution_log.conversations_id
  );

UPDATE improvement_log
SET conversations_id = NULL
WHERE conversations_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM conversations WHERE id = improvement_log.conversations_id
  );

-- ── 6. 设置存量 conversations.analyzed ──
-- 有对应 archive 且 archive.analyzed=1 → conversations.analyzed=1
UPDATE conversations
SET analyzed = 1
WHERE id IN (
    SELECT DISTINCT ca.conversations_id
    FROM conversation_archive ca
    WHERE ca.analyzed = 1
      AND ca.conversations_id IS NOT NULL
)
AND (analyzed IS NULL OR analyzed = 0);

-- 其余未见 archive 或 archive.analyzed=0 的 → 维持 analyzed=0
UPDATE conversations
SET analyzed = 0
WHERE analyzed IS NULL;

-- ── 7. 校验回填结果 ──
SELECT '=== 回填统计 ===' AS info;

SELECT 'conversation_archive NULL' AS field,
       COUNT(*) AS count FROM conversation_archive WHERE conversations_id IS NULL
UNION ALL
SELECT 'conversation_archive valid',
       COUNT(*) FROM conversation_archive WHERE conversations_id IS NOT NULL
UNION ALL
SELECT 'optimization_feedback NULL',
       COUNT(*) FROM optimization_feedback WHERE conversations_id IS NULL
UNION ALL
SELECT 'optimization_feedback valid',
       COUNT(*) FROM optimization_feedback WHERE conversations_id IS NOT NULL
UNION ALL
SELECT 'evolution_log NULL',
       COUNT(*) FROM evolution_log WHERE conversations_id IS NULL
UNION ALL
SELECT 'evolution_log valid',
       COUNT(*) FROM evolution_log WHERE conversations_id IS NOT NULL
UNION ALL
SELECT 'improvement_log NULL',
       COUNT(*) FROM improvement_log WHERE conversations_id IS NULL
UNION ALL
SELECT 'improvement_log valid',
       COUNT(*) FROM improvement_log WHERE conversations_id IS NOT NULL;

SELECT '=== analyzed 标记统计 ===' AS info;
SELECT analyzed, COUNT(*) AS count FROM conversations GROUP BY analyzed;

SELECT '=== 无效FK引用（应为0） ===' AS info;
SELECT 'conversation_archive orph' AS table_name,
       COUNT(*) FROM conversation_archive ca
       WHERE ca.conversations_id IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM conversations WHERE id = ca.conversations_id);

-- ============================================================
-- 执行完毕
-- ============================================================
