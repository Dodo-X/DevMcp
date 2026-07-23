"""验证数据库 schema 与 database.py DDL 一致"""

import sqlite3

conn = sqlite3.connect("data/databases/devpartner.db")
c = conn.cursor()

expected = {
    "conversations": [
        "id",
        "conversation_id",
        "timestamp",
        "client",
        "topic",
        "task_type",
        "user_intent",
        "self_reflection",
        "complexity",
        "analyzed",
        "status",
        "total_steps",
        "completed_steps",
        "created_at",
        "updated_at",
        "completed_at",
        "summary_generated",
        "system_id",
        "user_raw_input",
        "archive_tier",
        "ai_analysis",
    ],
    "conversation_steps": [
        "id",
        "step_id",
        "conversation_id",
        "step_order",
        "step_type",
        "step_name",
        "status",
        "input_data",
        "output_data",
        "error_message",
        "started_at",
        "completed_at",
        "duration_ms",
        "retry_count",
        "max_retries",
        "priority",
        "created_at",
    ],
    "connected_systems": [
        "system_id",
        "system_type",
        "display_name",
        "project_path",
        "tech_stack",
        "architecture",
        "business_domains",
        "maturity",
        "first_connected",
        "last_active",
        "last_seen_at",
        "conversation_count",
        "metadata",
        "project_description",
    ],
    "evolution_log": [
        "id",
        "timestamp",
        "version",
        "change_type",
        "description",
        "files_changed",
        "success",
        "conversations_id",
    ],
    "improvement_log": [
        "id",
        "timestamp",
        "category",
        "suggestion",
        "priority",
        "status",
        "applied_at",
        "result",
        "conversations_id",
        "dimensions",
    ],
    "growth_analysis": [
        "id",
        "timestamp",
        "analysis_type",
        "title",
        "description",
        "suggestion",
        "related_data",
        "priority",
        "status",
        "reviewer",
        "review_comment",
        "reviewed_at",
        "applied_at",
        "source",
        "source_period",
        "conversations_id",
    ],
    "knowledge_points": [
        "id",
        "knowledge_id",
        "title",
        "content",
        "category",
        "domain",
        "tags",
        "source_id",
        "confidence",
        "difficulty",
        "usage_count",
        "related_knowledge_ids",
        "created_at",
        "type",
        "aliases",
    ],
    "task_queue": [
        "id",
        "task_id",
        "task_type",
        "payload",
        "status",
        "priority",
        "max_retries",
        "retry_count",
        "error_message",
        "result",
        "progress",
        "estimated_memory_mb",
        "actual_memory_mb",
        "queued_at",
        "started_at",
        "completed_at",
        "timeout_seconds",
        "worker_id",
        "is_deleted",
        "next_retry_at",
        "sort_order",
        "last_heartbeat",
        "partial_result",
        "status_note",
    ],
    "user_skills": [
        "id",
        "timestamp",
        "skill_domain",
        "skill_name",
        "skill_level",
        "sub_skills",
        "evidence",
        "conversation_ids",
        "hours_spent",
        "growth_trend",
        "last_updated",
        "confidence",
        "first_seen",
        "last_seen",
        "evidence_count",
        "source_conversation_id",
        "source_timestamp",
        "extraction_method",
    ],
    "user_skill_plan": [
        "id",
        "timestamp",
        "skill_domain",
        "goal",
        "target_level",
        "target_date",
        "current_progress",
        "milestones",
        "status",
        "created_at",
        "updated_at",
    ],
    "optimization_feedback": [
        "id",
        "timestamp",
        "source",
        "feedback_type",
        "target_tool",
        "target_rule",
        "description",
        "suggestion",
        "priority",
        "status",
        "applied_at",
        "result",
        "conversations_id",
    ],
    "user_profile": [
        "id",
        "dimension",
        "value",
        "confidence",
        "evidence",
        "first_observed",
        "last_observed",
        "observation_count",
        "trend",
        "updated_at",
    ],
    "system_context_fragments": [
        "id",
        "conversation_id",
        "system_id",
        "tech_signals",
        "architecture_signals",
        "business_signals",
        "new_discoveries",
        "confidence",
        "observed_at",
        "merged",
    ],
    "pending_analyses": [
        "id",
        "analysis_type",
        "source_date",
        "system_id",
        "raw_data",
        "missing_dimensions",
        "retry_count",
        "created_at",
        "last_attempted_at",
        "status",
        "error_message",
    ],
    "meta": ["key", "value", "updated_at"],
}

all_ok = True
for table, exp_cols in expected.items():
    c.execute(f"PRAGMA table_info({table})")
    actual_cols = [row[1] for row in c.fetchall()]
    if set(actual_cols) != set(exp_cols):
        extra = set(actual_cols) - set(exp_cols)
        missing = set(exp_cols) - set(actual_cols)
        print(f"[MISMATCH] {table}: extra={extra}, missing={missing}")
        all_ok = False

if all_ok:
    print("ALL TABLES MATCH DDL!")
else:
    print("SOME TABLES STILL HAVE MISMATCHES")

# 检查废弃索引
c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
idxs = {row[0] for row in c.fetchall()}
deprecated = {"idx_knowledge_points_source", "idx_kp_source_session"}
remaining = idxs & deprecated
if remaining:
    print(f"Deprecated indexes still exist: {remaining}")
else:
    print("No deprecated indexes found")

# 显示所有索引
print("\nCurrent indexes:")
for idx in sorted(idxs):
    print(f"  {idx}")

conn.close()
