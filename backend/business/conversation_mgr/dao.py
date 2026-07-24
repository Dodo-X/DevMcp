"""
ConversationDAO — 纯 DB 操作层 (v9.10.1)
=========================================
所有 SQL 统一管理，只负责数据读写，不含业务逻辑/LLM/队列。
上层 Engine 不再写任何 SQL 字符串。

职责：
  - 会话 CRUD
  - 步骤 CRUD
  - 计数同步
  - FK 自修复
  - 系统注册
  - 项目上下文读取
"""

import json
import logging
from datetime import datetime
from typing import Any

from backend.business.conversation_mgr.constants import (
    DEFAULT_CLIENT,
    DEFAULT_SYSTEM_ID,
    DEFAULT_TASK_TYPE,
    TABLE_CONNECTED_SYSTEMS,
    TABLE_CONVERSATION_STEPS,
    TABLE_CONVERSATIONS,
    TABLE_KNOWLEDGE_POINTS,
    TABLE_SYSTEM_CONTEXT_FRAGMENTS,
    TABLE_TASK_QUEUE,
    TABLE_USER_PROFILE,
    TABLE_USER_SKILLS,
    TRUNC_RULES,
)

logger = logging.getLogger(__name__)


class ConversationDAO:
    """对话数据访问层 — 所有 SQL 操作统一封装"""

    def __init__(self, db):
        self.db = db

    # ══════════════════════════════════════════════════════════
    # 会话操作
    # ══════════════════════════════════════════════════════════

    def create_conversation(
        self,
        conv_id: str,
        timestamp: str,
        client: str = DEFAULT_CLIENT,
        topic: str = "",
        task_type: str = DEFAULT_TASK_TYPE,
        user_intent: str = "",
        system_id: str = DEFAULT_SYSTEM_ID,
        user_raw_input: str = "",
        ai_analysis: str = "",
    ) -> None:
        """创建新会话记录"""
        self.db.query_local(
            f"INSERT INTO {TABLE_CONVERSATIONS} ("
            "conversation_id, timestamp, client, topic, task_type,"
            "user_intent, status, created_at, updated_at,"
            "system_id, user_raw_input, ai_analysis,"
            "total_steps, completed_steps"
            ") VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, 0, 0)",
            (
                conv_id,
                timestamp,
                client,
                topic,
                task_type,
                user_intent,
                timestamp,
                timestamp,
                system_id,
                (user_raw_input or "")[: TRUNC_RULES["raw_input"]],
                (ai_analysis or "")[: TRUNC_RULES["ai_analysis"]],
            ),
        )

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """获取单条会话记录"""
        rows = self.db.query_local(
            f"SELECT * FROM {TABLE_CONVERSATIONS} WHERE conversation_id = ?",
            (conversation_id,),
        )
        return dict(rows[0]) if rows else None

    def get_conversation_meta(self, conversation_id: str) -> dict[str, Any]:
        """获取会话元数据（部分字段）"""
        rows = self.db.query_local(
            f"SELECT topic, system_id, client, user_raw_input, self_reflection, "
            f"task_type, complexity, ai_analysis "
            f"FROM {TABLE_CONVERSATIONS} WHERE conversation_id = ?",
            (conversation_id,),
        )
        return dict(rows[0]) if rows else {}

    def list_conversations(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str = "",
        task_type: str = "",
        keyword: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        """分页列出会话历史（支持状态/类型/关键词筛选）

        返回 (rows, total_count)
        """
        where = ["1 = 1"]
        params: list = []
        if status:
            where.append("status = ?")
            params.append(status)
        if task_type:
            where.append("task_type = ?")
            params.append(task_type)
        if keyword:
            where.append("(topic LIKE ? OR user_intent LIKE ? OR conversation_id LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
        where_sql = " AND ".join(where)

        total_row = self.db.query_local(
            f"SELECT COUNT(*) as cnt FROM {TABLE_CONVERSATIONS} WHERE {where_sql}",
            tuple(params),
        )[0]
        total = total_row["cnt"] or 0

        rows = self.db.query_local(
            f"SELECT conversation_id, timestamp, client, topic, task_type, "
            f"user_intent, status, total_steps, completed_steps, created_at, "
            f"updated_at, complexity, system_id "
            f"FROM {TABLE_CONVERSATIONS} WHERE {where_sql} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
        return rows or [], total

    def check_conversation_exists(self, conversation_id: str) -> bool:
        """检查会话是否存在"""
        rows = self.db.query_local(
            f"SELECT id FROM {TABLE_CONVERSATIONS} WHERE conversation_id = ?",
            (conversation_id,),
        )
        return len(rows) > 0

    def ensure_conversation_exists(
        self,
        conversation_id: str,
        client: str = DEFAULT_CLIENT,
        topic: str = "",
    ) -> bool:
        """FK 自保护 — 确保会话父记录存在，不存在则创建"""
        try:
            if self.check_conversation_exists(conversation_id):
                return True
            ts = datetime.now().isoformat()
            self.db.query_local(
                f"INSERT INTO {TABLE_CONVERSATIONS} ("
                "conversation_id, timestamp, client, topic, task_type,"
                "status, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (conversation_id, ts, client, topic, DEFAULT_TASK_TYPE, ts, ts),
            )
            logger.info(f"ensure_conversation_exists: 创建会话 {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"ensure_conversation_exists 失败: {e}")
            return False

    def update_self_reflection(self, conversation_id: str, ai_summary: str, now: str) -> None:
        """更新 self_reflection 字段"""
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATIONS} SET self_reflection = ?, updated_at = ? "
            f"WHERE conversation_id = ?",
            (ai_summary[: TRUNC_RULES["ai_summary"]], now, conversation_id),
        )

    def mark_conversation_completed(self, conversation_id: str, now: str) -> None:
        """标记会话为完成"""
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATIONS} SET "
            f"status = 'completed', analyzed = 1, summary_generated = 1, "
            f"updated_at = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )

    def fail_conversation(self, conversation_id: str, error: str) -> None:
        """标记会话失败"""
        now = datetime.now().isoformat()
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATIONS} SET "
            f"status = 'failed', updated_at = ?, self_reflection = ? "
            f"WHERE conversation_id = ? AND status NOT IN ('completed', 'failed')",
            (now, error, conversation_id),
        )

    def count_daily_conversations(self, target_date: str) -> tuple[int, int]:
        """统计指定日期的会话数（total, analyzed）"""
        row = self.db.query_local(
            f"SELECT COUNT(*) as total, "
            f"SUM(CASE WHEN analyzed = 1 THEN 1 ELSE 0 END) as analyzed "
            f"FROM {TABLE_CONVERSATIONS} "
            f"WHERE DATE(created_at) = ?",
            (target_date,),
        )[0]
        return row["total"] or 0, row["analyzed"] or 0

    def update_project_description(self, system_id: str, new_desc: str) -> None:
        """更新项目描述"""
        self.db.update_project_description(system_id, new_desc)

    # ══════════════════════════════════════════════════════════
    # 步骤操作
    # ══════════════════════════════════════════════════════════

    def get_steps(self, conversation_id: str) -> list[dict[str, Any]]:
        """获取会话所有步骤"""
        return self.db.query_local(
            f"SELECT * FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ? ORDER BY step_order ASC",
            (conversation_id,),
        )

    def get_step(self, step_id: str) -> dict[str, Any] | None:
        """获取单个步骤"""
        rows = self.db.query_local(
            f"SELECT * FROM {TABLE_CONVERSATION_STEPS} WHERE step_id = ?",
            (step_id,),
        )
        return rows[0] if rows else None

    def check_duplicate_step(self, conversation_id: str, client_request_id: str) -> str | None:
        """并发检测 — 查找重复步骤"""
        existing = self.db.query_local(
            f"SELECT step_id FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ? AND input_data LIKE ? LIMIT 1",
            (conversation_id, f"%{client_request_id}%"),
        )
        return existing[0]["step_id"] if existing else None

    def insert_step(
        self,
        step_id: str,
        conversation_id: str,
        step_name: str,
        step_input: dict,
    ) -> None:
        """写入 conversation_steps 表"""
        actual_step_type = (
            step_input.get("step_type", "general") if isinstance(step_input, dict) else "general"
        )
        now = datetime.now().isoformat()
        self.db.query_local(
            f"INSERT INTO {TABLE_CONVERSATION_STEPS} ("
            "step_id, conversation_id, step_order, step_type,"
            "step_name, status, input_data, max_retries, priority, created_at"
            ") VALUES (?, ?, "
            f"(SELECT COALESCE(MAX(step_order), 0) + 1 FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ?), "
            "?, ?, 'pending', ?, 3, 5, ?)",
            (
                step_id,
                conversation_id,
                conversation_id,
                actual_step_type,
                step_name,
                json.dumps(step_input, ensure_ascii=False),
                now,
            ),
        )
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATION_STEPS} SET started_at = ? WHERE step_id = ?",
            (now, step_id),
        )

    def sync_step_counts(self, conversation_id: str) -> tuple[int, int]:
        """同步 conversation 的 total_steps/completed_steps 计数"""
        completed = self.db.query_local(
            f"SELECT COUNT(*) as cnt FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ? AND status = 'completed'",
            (conversation_id,),
        )[0]["cnt"]
        total = self.db.query_local(
            f"SELECT COUNT(*) as cnt FROM {TABLE_CONVERSATION_STEPS} WHERE conversation_id = ?",
            (conversation_id,),
        )[0]["cnt"]
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATIONS} SET "
            f"completed_steps = ?, total_steps = ?, updated_at = ? "
            f"WHERE conversation_id = ?",
            (completed, total, datetime.now().isoformat(), conversation_id),
        )
        return total, completed

    def get_step_completion_stats(self, conversation_id: str) -> tuple[int, int, int]:
        """获取步骤完成统计（completed, total, failed）"""
        row = self.db.query_local(
            f"SELECT "
            f"(SELECT COUNT(*) FROM {TABLE_CONVERSATION_STEPS} "
            f" WHERE conversation_id = ? AND status = 'completed') as completed, "
            f"(SELECT COUNT(*) FROM {TABLE_CONVERSATION_STEPS} "
            f" WHERE conversation_id = ?) as total, "
            f"(SELECT COUNT(*) FROM {TABLE_CONVERSATION_STEPS} "
            f" WHERE conversation_id = ? AND status = 'failed') as failed",
            (conversation_id, conversation_id, conversation_id),
        )[0]
        return row["completed"] or 0, row["total"] or 0, row["failed"] or 0

    def update_step_status(
        self,
        step_id: str,
        status: str,
        output_data: dict | None = None,
        error_message: str | None = None,
        completed_at: str | None = None,
        duration_ms: int | None = None,
        retry_count: int | None = None,
    ) -> None:
        """更新步骤状态"""
        sets = ["status = ?"]
        params: list = [status]
        if output_data is not None:
            sets.append("output_data = ?")
            params.append(json.dumps(output_data, ensure_ascii=False))
        if error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        if completed_at is not None:
            sets.append("completed_at = ?")
            params.append(completed_at)
        if duration_ms is not None:
            sets.append("duration_ms = ?")
            params.append(duration_ms)
        if retry_count is not None:
            sets.append("retry_count = ?")
            params.append(retry_count)
        params.append(step_id)
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATION_STEPS} SET {', '.join(sets)} WHERE step_id = ?",
            tuple(params),
        )

    def mark_step_pending_retry(self, step_id: str, reason: str) -> None:
        """标记步骤为 pending_retry"""
        self.db.query_local(
            f"UPDATE {TABLE_CONVERSATION_STEPS} SET "
            f"status = 'pending_retry', error_message = ?, retry_count = 0 "
            f"WHERE step_id = ?",
            (reason, step_id),
        )

    def get_steps_with_input_data(self, conversation_id: str) -> list[dict[str, Any]]:
        """获取会话步骤（含 input_data/output_data）"""
        return self.db.query_local(
            f"SELECT step_name, step_type, status, input_data, output_data, created_at "
            f"FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ? ORDER BY step_order",
            (conversation_id,),
        )

    def get_steps_input_data_only(self, conversation_id: str) -> list[dict[str, Any]]:
        """获取步骤 input_data（用于 files_changed 提取等）"""
        return self.db.query_local(
            f"SELECT input_data FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ? ORDER BY step_order",
            (conversation_id,),
        )

    def get_steps_with_user_traits(self, conversation_id: str) -> list[dict[str, Any]]:
        """获取含 user_traits 的步骤"""
        return self.db.query_local(
            f"SELECT input_data FROM {TABLE_CONVERSATION_STEPS} "
            f"WHERE conversation_id = ? AND input_data LIKE '%user_traits%' "
            f"ORDER BY step_order",
            (conversation_id,),
        )

    # ══════════════════════════════════════════════════════════
    # FK 自修复
    # ══════════════════════════════════════════════════════════

    def fk_repair_create_index(self) -> None:
        """创建 conversations 唯一索引"""
        cursor = self.db._local_conn.cursor()
        cursor.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique "
            f"ON {TABLE_CONVERSATIONS}(conversation_id)"
        )

    def fk_repair_check_exists(self, conversation_id: str) -> bool:
        """FK 修复 — 检查会话是否存在"""
        cursor = self.db._local_conn.cursor()
        exists = cursor.execute(
            f"SELECT id FROM {TABLE_CONVERSATIONS} WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return exists is not None

    def fk_repair_create_conversation(self, conversation_id: str, topic: str) -> None:
        """FK 修复 — 自动创建会话记录"""
        ts = datetime.now().isoformat()
        cursor = self.db._local_conn.cursor()
        cursor.execute(
            f"INSERT INTO {TABLE_CONVERSATIONS} ("
            "conversation_id, timestamp, client, topic, task_type, status, created_at, updated_at"
            f") VALUES (?, ?, '{DEFAULT_CLIENT}', ?, '{DEFAULT_TASK_TYPE}', 'active', ?, ?)",
            (conversation_id, ts, topic[: TRUNC_RULES["topic"]] if topic else "自动创建", ts, ts),
        )
        self.db._local_conn.commit()

    # ══════════════════════════════════════════════════════════
    # 系统注册
    # ══════════════════════════════════════════════════════════

    def ensure_system_registered(self, system_id: str, client: str, timestamp: str) -> None:
        """确保对接系统已注册到 connected_systems 表

        v10(T4): 新注册时一并写入
          - client_name：承接原 client/IDE 名（入参 client 为空时取 'unknown'）
          - system_type：启发式默认 'backend_service'（企业软件大类枚举，待确认）
          - system_type_confirmed：0（标记未确认，待人工/LLM 复核）
        不再写入已删除的 project_path。
        """
        try:
            existing = self.db.query_local(
                f"SELECT system_id, display_name FROM {TABLE_CONNECTED_SYSTEMS} "
                f"WHERE system_id = ?",
                (system_id,),
            )
            if existing:
                old_display = existing[0].get("display_name", "")
                if old_display and old_display != system_id:
                    self.db.query_local(
                        f"UPDATE {TABLE_CONNECTED_SYSTEMS} SET "
                        f"display_name = ?, last_active = ?, "
                        f"conversation_count = conversation_count + 1 "
                        f"WHERE system_id = ?",
                        (system_id, timestamp, system_id),
                    )
                else:
                    self.db.query_local(
                        f"UPDATE {TABLE_CONNECTED_SYSTEMS} SET "
                        f"last_active = ?, conversation_count = conversation_count + 1 "
                        f"WHERE system_id = ?",
                        (timestamp, system_id),
                    )
            else:
                # client_name 承接原 client/IDE 名；system_type 启发式默认 backend_service
                client_name = client or "unknown"
                self.db.query_local(
                    f"INSERT INTO {TABLE_CONNECTED_SYSTEMS} "
                    "(system_id, client_name, system_type, system_type_confirmed, "
                    "display_name, first_connected, last_active, conversation_count) "
                    "VALUES (?, ?, 'backend_service', 0, ?, ?, ?, 1)",
                    (system_id, client_name, system_id, timestamp, timestamp),
                )
        except Exception as e:
            logger.warning(f"系统注册失败（非致命）: {e}")

    # ══════════════════════════════════════════════════════════
    # 项目上下文
    # ══════════════════════════════════════════════════════════

    def get_system_context(self, system_id: str) -> str:
        """从 connected_systems 读取项目上下文（自然语言描述）

        v10(T4): 已移除对删除列 project_path 的 SELECT 与派生逻辑，
        改用 system_id / display_name 作为项目标识。
        """
        if system_id == DEFAULT_SYSTEM_ID:
            return ""
        try:
            rows = self.db.query_local(
                f"SELECT project_description, tech_stack, architecture, "
                f"business_domains, maturity, display_name "
                f"FROM {TABLE_CONNECTED_SYSTEMS} WHERE system_id = ?",
                (system_id,),
            )
            if not rows:
                return ""
            row = rows[0]
            parts = []
            pd = (row.get("project_description") or "").strip()
            if pd:
                parts.append(f"项目描述: {pd}")
            disp = (row.get("display_name") or "").strip()
            if disp and disp != system_id:
                parts.append(f"项目名: {disp}")
            mat = (row.get("maturity") or "").strip()
            if mat and mat != "unknown":
                parts.append(f"项目成熟度: {mat}")
            try:
                ts = json.loads(row.get("tech_stack") or "[]")
                if ts:
                    parts.append(f"技术栈: {', '.join(str(t) for t in ts[:8])}")
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                bd = json.loads(row.get("business_domains") or "[]")
                if bd:
                    parts.append(f"业务领域: {', '.join(str(b) for b in bd[:5])}")
            except (json.JSONDecodeError, TypeError):
                pass
            return " | ".join(parts) if parts else ""
        except Exception as e:
            logger.warning(f"读取项目上下文失败（非致命）: {e}")
            return ""

    def get_system_row(self, system_id: str) -> dict[str, Any] | None:
        """获取系统完整记录"""
        rows = self.db.query_local(
            f"SELECT * FROM {TABLE_CONNECTED_SYSTEMS} WHERE system_id = ?",
            (system_id,),
        )
        return dict(rows[0]) if rows else None

    def get_project_description(self, system_id: str) -> str:
        """获取项目描述"""
        rows = self.db.query_local(
            f"SELECT project_description FROM {TABLE_CONNECTED_SYSTEMS} WHERE system_id = ?",
            (system_id,),
        )
        return (rows[0].get("project_description", "") or "") if rows else ""

    # ══════════════════════════════════════════════════════════
    # System Context Fragments
    # ══════════════════════════════════════════════════════════

    def insert_system_context_fragment(
        self,
        conversation_id: str,
        system_id: str,
        tech_signals: list,
        architecture_signals: list,
        business_signals: list,
        new_discoveries: list,
        confidence: float,
        now: str,
    ) -> None:
        """写入 system_context_fragments"""
        self.db.query_local(
            f"INSERT INTO {TABLE_SYSTEM_CONTEXT_FRAGMENTS} ("
            "conversation_id, system_id, tech_signals, architecture_signals,"
            "business_signals, new_discoveries, confidence, observed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                system_id,
                json.dumps(tech_signals, ensure_ascii=False),
                json.dumps(architecture_signals, ensure_ascii=False),
                json.dumps(business_signals, ensure_ascii=False),
                json.dumps(new_discoveries, ensure_ascii=False),
                confidence,
                now,
            ),
        )

    def _connected_system_columns(self) -> set:
        """返回 connected_systems 当前列名集合（容错缺失列）。

        注意：query_local 仅以 SELECT 前缀判定读操作，PRAGMA 会被误判为写，
        故此处使用原始连接（与 fk_repair_* 一致）。
        """
        try:
            cur = self.db._local_conn.cursor()
            cur.execute(f"PRAGMA table_info({TABLE_CONNECTED_SYSTEMS})")
            return {row[1] for row in cur.fetchall()}
        except Exception:
            logger.warning(
                "ConversationDAO._connected_system_columns: 未预期的异常被静默捕获（P-17 收口）",
                exc_info=True,
            )
            return set()

    def update_connected_system(
        self,
        system_id: str,
        architecture: str = "",
        tech_stack: list = None,
        business_domains: list = None,
        business_modules: list = None,
        client_name: str = "",
        system_type: str = "",
        system_type_confirmed: int = None,
        now: str = "",
    ) -> None:
        """更新 connected_systems 表

        v10(T4): 扩展支持 business_modules / client_name / system_type /
        system_type_confirmed。对缺失列容错（仅更新存在的列），避免旧库报错。
        仅当对应参数非空 / 非 None 时才写入该字段，避免误覆盖已有值。
        """
        ts = tech_stack or []
        bd = business_domains or []
        ts_json = json.dumps(ts, ensure_ascii=False) if ts else ""
        bd_json = json.dumps(bd, ensure_ascii=False) if bd else ""
        bm_json = ""
        if business_modules is not None:
            bm_json = (
                json.dumps(business_modules, ensure_ascii=False)
                if business_modules
                else "[]"
            )

        cols = self._connected_system_columns()
        set_clauses: list = []
        params: list = []

        if "architecture" in cols and architecture:
            set_clauses.append("architecture = COALESCE(NULLIF(?, ''), architecture)")
            params.append(architecture)
        if "tech_stack" in cols and ts_json:
            set_clauses.append("tech_stack = ?")
            params.append(ts_json)
        if "business_domains" in cols and bd_json:
            set_clauses.append("business_domains = ?")
            params.append(bd_json)
        if "business_modules" in cols and bm_json:
            set_clauses.append("business_modules = ?")
            params.append(bm_json)
        if "client_name" in cols and client_name:
            set_clauses.append("client_name = COALESCE(NULLIF(?, ''), client_name)")
            params.append(client_name)
        if "system_type" in cols and system_type:
            set_clauses.append("system_type = COALESCE(NULLIF(?, ''), system_type)")
            params.append(system_type)
        if "system_type_confirmed" in cols and system_type_confirmed is not None:
            set_clauses.append("system_type_confirmed = ?")
            params.append(int(system_type_confirmed))
        if "last_seen_at" in cols and now:
            set_clauses.append("last_seen_at = ?")
            params.append(now)

        if not set_clauses:
            return

        params.append(system_id)
        self.db.query_local(
            f"UPDATE {TABLE_CONNECTED_SYSTEMS} SET {', '.join(set_clauses)} "
            f"WHERE system_id = ?",
            tuple(params),
        )

    # ══════════════════════════════════════════════════════════
    # User Profile
    # ══════════════════════════════════════════════════════════

    def upsert_user_profile_dimension(
        self,
        dim_key: str,
        dim_value: str,
        confidence: float,
        evidence: str,
        now: str,
    ) -> None:
        """写入/更新 user_profile 维度"""
        existing = self.db.query_local(
            f"SELECT id, observation_count FROM {TABLE_USER_PROFILE} WHERE dimension = ?",
            (dim_key,),
        )
        if existing:
            row = existing[0]
            new_count = (row.get("observation_count", 1) or 1) + 1
            self.db.query_local(
                f"UPDATE {TABLE_USER_PROFILE} SET "
                "value = ?, confidence = ?, evidence = ?, "
                "last_observed = ?, observation_count = ?, "
                "trend = CASE WHEN ? >= confidence THEN 'rising' ELSE 'stable' END, "
                "updated_at = ? WHERE dimension = ?",
                (dim_value, confidence, evidence, now, new_count, confidence, now, dim_key),
            )
        else:
            self.db.query_local(
                f"INSERT INTO {TABLE_USER_PROFILE} (dimension, value, confidence, evidence, "
                "first_observed, last_observed, observation_count, trend, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 'stable', ?)",
                (dim_key, dim_value, confidence, evidence, now, now, now),
            )

    # ══════════════════════════════════════════════════════════
    # User Skills
    # ══════════════════════════════════════════════════════════

    def merge_user_skill(
        self,
        skill_name: str,
        skill_domain: str,
        conversation_id: str,
        profile: dict,
        now: str,
    ) -> None:
        """合并技能到 user_skills 表"""
        existing = self.db.query_user_skill(skill_name, skill_domain=skill_domain)
        if existing and isinstance(existing, dict):
            self.db.update_user_skill(
                skill_name,
                {
                    "skill_domain": skill_domain,
                    "skill_name": skill_name,
                    "skill_level": profile.get("skill_level", "intermediate"),
                    "evidence": f"llm_user_profile_v9.8: conv={conversation_id}",
                    "confidence": min((existing.get("confidence", 0.5) or 0.5) + 0.1, 1.0),
                    "last_seen": now,
                    "evidence_count": (existing.get("evidence_count", 1) or 1) + 1,
                    "growth_trend": "growing",
                },
                skill_domain=skill_domain,
            )
        else:
            self.db.insert_user_skill(
                {
                    "skill_name": skill_name,
                    "skill_domain": skill_domain,
                    "skill_level": "intermediate",
                    "evidence": f"llm_user_profile_v9.8: conv={conversation_id}",
                    "conversation_ids": conversation_id,
                    "confidence": 0.5,
                    "first_seen": now,
                    "last_seen": now,
                    "evidence_count": 1,
                    "hours_spent": 0.5,
                    "growth_trend": "stable",
                }
            )

    def set_skill_plan(self, domain: str, goal: str, target_level: str = "intermediate") -> None:
        """设置学习计划"""
        self.db.set_skill_plan(domain=domain, goal=goal, target_level=target_level)

    # ══════════════════════════════════════════════════════════
    # Knowledge Points
    # ══════════════════════════════════════════════════════════

    def insert_knowledge_point(
        self,
        title: str,
        content: str,
        category: str,
        domain: str,
        tags: list,
        source_id: str = "",
    ) -> str | None:
        """创建知识点"""
        return self.db.insert_knowledge_point(
            title=title,
            content=content,
            category=category,
            domain=domain,
            tags=tags,
            source_id=source_id,
        )

    def get_known_domains_from_kp(self) -> dict[str, list]:
        """从 knowledge_points 表获取已知领域"""
        rows = self.db.query_local(
            f"SELECT DISTINCT domain, tags FROM {TABLE_KNOWLEDGE_POINTS} "
            f"WHERE domain != '' AND type = 'skill'"
        )
        domains = {}
        for row in rows or []:
            domain = row.get("domain", "")
            tags = row.get("tags", "[]")
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except (json.JSONDecodeError, TypeError):
                    tags = [tags]
            if domain and domain not in domains:
                domains[domain] = tags if isinstance(tags, list) else []
        return domains

    def get_known_domains_from_skills(self) -> dict[str, list]:
        """从 user_skills 表推断领域"""
        rows = self.db.query_local(f"SELECT DISTINCT skill_name FROM {TABLE_USER_SKILLS} LIMIT 20")
        domains = {}
        for row in rows or []:
            name = row.get("skill_name", "")
            if name:
                domains[name] = [name.lower()]
        return domains

    # ══════════════════════════════════════════════════════════
    # Task Queue 查询
    # ══════════════════════════════════════════════════════════

    def check_finalize_sub_task_status(self, task_type: str, conversation_id: str) -> str | None:
        """查询 finalize 子任务状态"""
        rows = self.db.query_local(
            f"SELECT status FROM {TABLE_TASK_QUEUE} "
            f"WHERE task_type = ? AND json_extract(payload, '$.conversation_id') = ? "
            f"AND is_deleted = 0 "
            f"ORDER BY queued_at DESC LIMIT 1",
            (task_type, conversation_id),
        )
        return rows[0].get("status", "") if rows else None

    def check_daily_summary_exists(self, target_date: str) -> bool:
        """检查是否已有 daily_summary 任务"""
        existing = self.db.query_local(
            f"SELECT task_id, status FROM {TABLE_TASK_QUEUE} "
            f"WHERE task_type = 'daily_summary' "
            f"AND is_deleted = 0 "
            f"AND json_extract(payload, '$.target_date') = ? "
            f"AND status NOT IN ('cancelled', 'duplicate_discarded')",
            (target_date,),
        )
        return len(existing) > 0

    # ══════════════════════════════════════════════════════════
    # 系统健康
    # ══════════════════════════════════════════════════════════

    def get_system_health(self) -> dict:
        """获取系统健康状态"""
        return {
            "active_conversations": 0,
            "running_tasks": 0,
            "concurrency_limit": 3,
            "estimated_memory_usage_mb": 0.0,
            "max_memory_limit_mb": 2048.0,
            "memory_utilization_percent": 0.0,
        }
