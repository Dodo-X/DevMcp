"""
统一任务恢复流水线 (v9.10.0)
=============================
v9.10.0: 从 services/ 迁移到 core/，与 task_queue 同属核心调度层
v9.6.3: 原始版本

设计哲学："一个房间，两扇门，两阶段（仅对话链路）"

房间里边是统一的任务恢复流水线（TaskRecoveryPipeline），不管是从哪扇门进来的
（启动扫描 or 定时扫描），都走同一套流程：

  第一阶段：主线恢复（先跑已有的）
    1. 扫描 task_queue 表中未完成的数据
    2. 按 task_type 分组
    3. 去重（基于每种 type 的唯一标识）
    4. 按依赖关系排序（step_analysis → conversation_finalize → ...）
    5. 装配入队 → 让 worker 逐个执行

  第二阶段：逐级兜底扫描（仅对话链路，不处理报告类）
    6. 扫描 conversation_steps 表 — step 全完成但 task_queue 中没有 finalize → 补交

两扇门：
  - 门A（启动门）：TaskQueue 初始化时调用，恢复上次中断的任务
  - 门B（定时门）：PeriodicScan 定时触发，补充扫描遗漏的数据
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RecoverySource(str, Enum):
    """恢复触发源 — 两扇门"""

    STARTUP = "startup"  # 门A：启动时恢复
    PERIODIC = "periodic"  # 门B：定时扫描


# ─────────────────────────────────────────────
# 去重规则定义
# ─────────────────────────────────────────────

# 每种 task_type 的去重依据字段（payload 中的 key）
DEDUP_KEYS: dict[str, str] = {
    "step_analysis": "step_id",
    "conversation_finalize": "conversation_id",
    "conversation_analysis": "conversation_id",
    "profile_update": "conversation_id",
    "knowledge_extraction": "conversation_id",
    "system_optimization": "conversation_id",
    "behavior_signals_extraction": "conversation_id",
    "daily_summary": "target_date",
    "daily_export": "target_date",
    # vault_export 系列：各自按唯一标识去重
    "vault_export_batch": "conversation_id",
    "vault_export_all": "__singleton__",  # 全局只有一个
    "vault_export_profile": "conversation_id",
    "vault_export_project": "system_id",
    "vault_export_weekly": "target_date",
    "vault_export_monthly": "target_date",
    "vault_export_annual": "target_date",
    "vault_export_daily": "target_date",
}

# 依赖层级（数字越小越先执行，同层级无依赖可并行）
DEPENDENCY_LEVEL: dict[str, int] = {
    "step_analysis": 0,
    "conversation_analysis": 1,
    "conversation_finalize": 1,
    "profile_update": 2,
    "knowledge_extraction": 2,
    "system_optimization": 2,
    "behavior_signals_extraction": 2,
    "daily_summary": 3,
    "daily_export": 3,
    "vault_export_daily": 4,
    "vault_export_weekly": 4,
    "vault_export_monthly": 4,
    "vault_export_annual": 4,
    "vault_export_batch": 4,
    "vault_export_all": 4,
    "vault_export_profile": 4,
    "vault_export_project": 4,
    "cleanup_force": 99,
    "cleanup_vacuum": 99,
    "cleanup_full": 99,
}


@dataclass
class RecoveryStats:
    """恢复流水线统计"""

    source: RecoverySource = RecoverySource.STARTUP
    scanned_total: int = 0
    after_dedup: int = 0
    duplicates_discarded: int = 0
    already_completed: int = 0
    enqueued: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    duplicate_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_recovery_pipeline(source: RecoverySource = RecoverySource.STARTUP) -> RecoveryStats:
    """
    统一任务恢复流水线 — "房间"的核心入口。

    两扇门（启动 / 定时）都调用这个函数。

    两阶段执行：
      第一阶段（主线）：扫描 task_queue → 分组去重排序 → 入队，先把已创建的任务跑完
      第二阶段（兜底）：扫描 conversation_steps，补充缺失的 finalize 任务（仅对话链路）
      daily_summary 兜底已移至 ProfileScheduler 日报定时任务

    Args:
        source: 触发来源（startup 或 periodic）

    Returns:
        RecoveryStats: 流水线执行统计
    """
    stats = RecoveryStats(source=source)
    stats.errors = []

    try:
        from backend.core.database.base_conn import get_db

        db = get_db()
        if not db.is_local_initialized():
            logger.debug("DB 未初始化，跳过恢复流水线")
            return stats

        # ════════════════════════════════════════════════
        # 第一阶段：主线恢复 — 把已有任务跑完
        # ════════════════════════════════════════════════
        raw_tasks = _scan_unfinished_tasks(db)
        stats.scanned_total = len(raw_tasks)
        logger.info(f"[恢复流水线:{source.value}] 阶段1 扫描: {stats.scanned_total} 个未完成任务")

        if raw_tasks:
            # ── 分组 ──
            grouped = _group_by_type(raw_tasks)

            # ── 去重 + 标记废弃 ──
            deduped, dup_count, dup_ids = _dedup_tasks(db, grouped)
            stats.after_dedup = sum(len(v) for v in deduped.values())
            stats.duplicates_discarded = dup_count
            stats.duplicate_ids = dup_ids

            logger.info(
                f"[恢复流水线:{source.value}] 阶段1 分组去重: "
                f"{stats.scanned_total} → {stats.after_dedup} (去重 {dup_count} 个)"
            )

            # ── 排序（按依赖层级 + 同类型内按时间序） ──
            ordered = _order_by_dependency(deduped)

            # ── 装配入队 ──
            enqueued_count = _enqueue_ordered_tasks(ordered, stats)
            stats.enqueued = enqueued_count

            # 统计每种类型的入队数量
            by_type = defaultdict(int)
            for t in ordered:
                by_type[t["task_type"]] += 1
            stats.by_type = dict(by_type)

            logger.info(
                f"[恢复流水线:{source.value}] 阶段1 排序入队: "
                f"入队 {enqueued_count} 个 | 类型分布: {dict(by_type)}"
            )
        else:
            logger.info(f"[恢复流水线:{source.value}] 阶段1 无未完成任务")

        # ════════════════════════════════════════════════
        # 第二阶段：逐级兜底扫描 — 补缺失的任务（仅对话链路）
        # ════════════════════════════════════════════════
        cascade_finalize = _cascade_scan_conversation_steps(db)

        if cascade_finalize > 0:
            logger.info(f"[恢复流水线:{source.value}] 阶段2 兜底: 补交 finalize={cascade_finalize}")
            stats.by_type["conversation_finalize_cascade"] = (
                stats.by_type.get("conversation_finalize_cascade", 0) + cascade_finalize
            )

    except Exception as e:
        logger.error(f"[恢复流水线:{source.value}] 执行异常: {e}", exc_info=True)
        stats.errors.append(str(e))

    return stats


# ══════════════════════════════════════════════════════════
# 阶段1：扫描 task_queue 未完成任务
# ══════════════════════════════════════════════════════════


def _scan_unfinished_tasks(db) -> list[dict[str, Any]]:
    """扫描 task_queue 中所有未完成（非 completed/cancelled）的任务。

    从 DB 加载完整记录到内存，后续阶段在内存中完成分组、去重、排序。
    不直接修改 DB，最后装配入队时才写回。

    注意：同时把 status='running' 且心跳超时的僵尸任务重置为 pending。
    """
    # 1. 先处理僵尸 running 任务（心跳超时 3h → 标记 timeout + 重置 pending）
    _handle_zombie_running_tasks(db)

    # 2. 扫描所有未完成的任务
    rows = db.query_local("""
        SELECT task_id, task_type, payload, status, priority, retry_count,
               max_retries, error_message, timeout_seconds, estimated_memory_mb,
               next_retry_at, sort_order
        FROM task_queue
        WHERE status IN ('pending', 'queued', 'running', 'failed', 'timeout')
          AND is_deleted = 0
        ORDER BY sort_order, queued_at
    """)

    tasks = []
    for row in rows or []:
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                logger.warning(
                    "_scan_unfinished_tasks: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                payload = {}
        tasks.append(
            {
                "task_id": row["task_id"],
                "task_type": row["task_type"],
                "payload": payload or {},
                "status": row["status"],
                "priority": row.get("priority", 5),
                "retry_count": row.get("retry_count", 0),
                "max_retries": row.get("max_retries", 3),
                "error_message": row.get("error_message", ""),
                "timeout_seconds": row.get("timeout_seconds", 10800),
                "estimated_memory_mb": row.get("estimated_memory_mb", 100),
                "sort_order": row.get("sort_order", 0),
            }
        )

    return tasks


def _handle_zombie_running_tasks(db):
    """处理僵尸 running 任务：心跳超过 3h 标记为 timeout。

    task_queue 自身的 _auto_cleanup_zombies 每 60s 也会做这件事，
    但恢复流水线在做扫描之前先处理一次，确保扫描到的数据是干净的。
    """
    try:
        now = datetime.now()
        cutoff = (now - timedelta(hours=3)).isoformat()

        zombie_rows = db.query_local(
            """
            SELECT task_id FROM task_queue
            WHERE status = 'running'
              AND (
                  (last_heartbeat IS NOT NULL AND last_heartbeat < ?)
                  OR
                  (last_heartbeat IS NULL AND started_at IS NOT NULL AND started_at < ?)
              )
              AND is_deleted = 0
        """,
            (cutoff, cutoff),
        )

        if zombie_rows:
            ids = [r["task_id"] for r in zombie_rows]
            placeholders = ",".join(["?"] * len(ids))
            db.query_local(
                f"UPDATE task_queue SET status = 'timeout', "
                f"error_message = 'Zombie timeout (recovery pipeline)', "
                f"completed_at = ? WHERE task_id IN ({placeholders})",
                (now.isoformat(), *ids),
            )
            logger.info(f"[恢复流水线] 标记 {len(ids)} 个僵尸任务为 timeout")

            # 同时重置为 pending 以便重试（如果 retry_count 未超限）
            db.query_local(
                f"UPDATE task_queue SET status = 'pending', "
                f"error_message = error_message || ' | Recovered by pipeline' "
                f"WHERE task_id IN ({placeholders}) AND retry_count < max_retries",
                tuple(ids),
            )
    except Exception as e:
        logger.warning(f"[恢复流水线] 僵尸清理失败（非致命）: {e}")


# ══════════════════════════════════════════════════════════
# 第二阶段：逐级兜底扫描 — 仅对话链路，不处理报告类
# ══════════════════════════════════════════════════════════


def _cascade_scan_conversation_steps(db) -> int:
    """
    v9.6.3: 第二阶段兜底 — 扫描 conversation_steps 表，发现"step 已全部完成
    但 task_queue 中没有对应 conversation_finalize 任务"的情况，
    自动补交 finalize。

    这是恢复流水线的兜底机制：主线任务跑完后，回头检查是否有
    遗漏的环节（step 完成了但 finalize 没创建）。

    Returns:
        补交的 conversation_finalize 任务数量
    """
    cascade_count = 0
    try:
        # 1. 找到所有"step 已全部完成"的 conversation
        #    排除已有 failed step 的 conversation（不触发 finalize）
        rows = db.query_local("""
            SELECT
                s.conversation_id,
                COUNT(*) as total_steps,
                SUM(CASE WHEN s.status = 'completed' THEN 1 ELSE 0 END) as completed_steps,
                SUM(CASE WHEN s.status = 'failed' THEN 1 ELSE 0 END) as failed_steps
            FROM conversation_steps s
            GROUP BY s.conversation_id
            HAVING completed_steps = total_steps
               AND failed_steps = 0
               AND total_steps > 0
        """)

        if not rows:
            return 0

        for row in rows:
            conv_id = row["conversation_id"]

            # 2. 检查 conversations 表状态 — 跳过已分析的
            conv_status = db.query_local(
                "SELECT status, analyzed FROM conversations WHERE conversation_id = ?", (conv_id,)
            )
            if not conv_status:
                continue
            if conv_status[0].get("analyzed") == 1:
                logger.debug(f"[兜底扫描] {conv_id}: 已分析，跳过")
                continue

            # 3. 检查 task_queue 中是否已有 finalize 任务
            existing = db.query_local(
                """
                SELECT task_id FROM task_queue
                WHERE task_type IN ('conversation_finalize', 'conversation_analysis')
                  AND is_deleted = 0
                  AND json_extract(payload, '$.conversation_id') = ?
                  AND status NOT IN ('cancelled', 'duplicate_discarded')
            """,
                (conv_id,),
            )

            if existing:
                logger.debug(
                    f"[兜底扫描] {conv_id}: 已有 finalize 任务 ({existing[0]['task_id']})，跳过"
                )
                continue

            # 4. 补交 conversation_finalize
            conv = db.query_local(
                "SELECT topic, system_id, client, user_raw_input, "
                "ai_analysis, self_reflection "
                "FROM conversations WHERE conversation_id = ?",
                (conv_id,),
            )
            if not conv:
                continue
            conv = conv[0]

            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()

            # v9.7.1: handler 未注册时跳过（避免创建注定失败的任务）
            if "conversation_finalize" not in tq._handlers:
                logger.warning(
                    f"[兜底扫描] {conv_id}: conversation_finalize handler 未注册，跳过补交"
                )
                continue

            task_id = tq.submit(
                task_type="conversation_finalize",
                payload={
                    "conversation_id": conv_id,
                    "topic": conv.get("topic", ""),
                    "system_id": conv.get("system_id", ""),
                    "client": conv.get("client", ""),
                    "user_raw_input": conv.get("user_raw_input", ""),
                    "ai_analysis": conv.get("ai_analysis", ""),
                    "ai_summary": conv.get("self_reflection", ""),
                    "_trigger_source": "recovery_cascade",
                },
                priority="medium",
            )

            logger.info(
                f"[兜底扫描] {conv_id}: step 全部完成({row['completed_steps']}/{row['total_steps']})，"
                f"补交 conversation_finalize → {task_id}"
            )
            cascade_count += 1

    except Exception as e:
        logger.warning(f"[兜底扫描] 异常（非致命）: {e}")

    return cascade_count


def _cascade_scan_daily_summary(db) -> int:
    """
    v9.6.3: 日报兜底扫描 — 已从恢复流水线第二阶段移除，改为由
    ProfileScheduler._execute_daily_summary 在每日 17:30 调用。

    检查是否有"当日所有 conversation 都已完成 finalize
    但 task_queue 中没有对应 daily_summary 任务"的情况，自动补交。

    Returns:
        补交的 daily_summary 任务数量
    """
    cascade_count = 0
    try:
        # 1. 找到所有有 conversation 的日期
        rows = db.query_local("""
            SELECT
                DATE(created_at) as target_date,
                COUNT(*) as total,
                SUM(CASE WHEN analyzed = 1 THEN 1 ELSE 0 END) as analyzed
            FROM conversations
            WHERE is_deleted = 0
            GROUP BY DATE(created_at)
            HAVING analyzed = total AND total > 0
        """)

        if not rows:
            return 0

        for row in rows:
            target_date = row["target_date"]
            if not target_date:
                continue

            # 2. 检查 task_queue 中是否已有该日期的 daily_summary
            existing = db.query_local(
                """
                SELECT task_id FROM task_queue
                WHERE task_type = 'daily_summary'
                  AND is_deleted = 0
                  AND json_extract(payload, '$.target_date') = ?
                  AND status NOT IN ('cancelled', 'duplicate_discarded')
            """,
                (target_date,),
            )

            if existing:
                logger.debug(
                    f"[级联扫描-daily] {target_date}: 已有 daily_summary "
                    f"({existing[0]['task_id']})，跳过"
                )
                continue

            # 3. 补交 daily_summary
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()

            # v9.7.1: handler 未注册时跳过
            if "daily_summary" not in tq._handlers:
                logger.warning(
                    f"[级联扫描-daily] {target_date}: daily_summary handler 未注册，跳过补交"
                )
                continue

            task_id = tq.submit(
                task_type="daily_summary",
                payload={
                    "target_date": target_date,
                    "_trigger_source": "recovery_cascade",
                },
                priority="medium",
            )
            logger.info(
                f"[级联扫描-daily] {target_date}: 所有 conversation finalize 完成"
                f"({row['analyzed']}/{row['total']})，补交 daily_summary → {task_id}"
            )
            cascade_count += 1

    except Exception as e:
        logger.warning(f"[级联扫描-daily] 异常（非致命）: {e}")

    return cascade_count


# ══════════════════════════════════════════════════════════
# 阶段2：按 task_type 分组
# ══════════════════════════════════════════════════════════


def _group_by_type(tasks: list[dict]) -> dict[str, list[dict]]:
    """按 task_type 分组，每组内保持原始顺序（sort_order）。"""
    grouped = defaultdict(list)
    for t in tasks:
        grouped[t["task_type"]].append(t)
    return dict(grouped)


# ══════════════════════════════════════════════════════════
# 阶段3：去重
# ══════════════════════════════════════════════════════════


def _dedup_tasks(
    db, grouped: dict[str, list[dict]]
) -> tuple[dict[str, list[dict]], int, list[str]]:
    """
    每组内按去重 key 去重。

    去重策略：
    - 找到每组内最早的（sort_order 最小 / queued_at 最早）那条保留
    - 其余重复记录标记为 'duplicate_discarded'，error_message = '重复废弃'
    - __singleton__ 类型全局只保留一条

    Returns:
        (deduped_grouped, duplicate_count, duplicate_task_ids)
    """
    deduped = {}
    duplicate_count = 0
    duplicate_ids = []

    for task_type, task_list in grouped.items():
        dedup_key = DEDUP_KEYS.get(task_type)
        if not dedup_key:
            # 未定义去重规则的类型，全部保留
            deduped[task_type] = task_list
            continue

        if dedup_key == "__singleton__":
            # 全局单例：只保留最早的一条
            task_list.sort(key=lambda t: t.get("sort_order", 0))
            deduped[task_type] = [task_list[0]]
            if len(task_list) > 1:
                for t in task_list[1:]:
                    _mark_duplicate(db, t["task_id"], task_type, "singleton")
                    duplicate_ids.append(t["task_id"])
                duplicate_count += len(task_list) - 1
            continue

        # 按去重 key 分组
        seen: dict[str, list[dict]] = defaultdict(list)
        for t in task_list:
            val = t["payload"].get(dedup_key, "")
            if not val:
                # 没有去重 key 值的，保留但不参与去重（可能是异常数据）
                val = f"__no_key__{t['task_id']}"
            seen[str(val)].append(t)

        unique_tasks = []
        for key_val, dup_list in seen.items():
            if key_val.startswith("__no_key__"):
                unique_tasks.extend(dup_list)
                continue

            # 按 sort_order 排序，最早优先
            dup_list.sort(key=lambda t: t.get("sort_order", 0))
            # 保留第一条（最早）
            unique_tasks.append(dup_list[0])
            # 其余标记废弃
            if len(dup_list) > 1:
                for t in dup_list[1:]:
                    _mark_duplicate(
                        db,
                        t["task_id"],
                        task_type,
                        f"duplicate of {dup_list[0]['task_id']} (key: {dedup_key}={key_val})",
                    )
                    duplicate_ids.append(t["task_id"])
                duplicate_count += len(dup_list) - 1

        deduped[task_type] = unique_tasks

    return deduped, duplicate_count, duplicate_ids


def _mark_duplicate(db, task_id: str, task_type: str, reason: str):
    """标记重复任务为废弃状态"""
    try:
        db.query_local(
            "UPDATE task_queue SET status = 'duplicate_discarded', "
            "error_message = ?, completed_at = ? WHERE task_id = ?",
            (f"重复废弃: {reason}", datetime.now().isoformat(), task_id),
        )
        logger.debug(f"[去重] {task_id} ({task_type}) → duplicate_discarded: {reason}")
    except Exception as e:
        logger.warning(f"[去重] 标记失败: {task_id} | {e}")


# ══════════════════════════════════════════════════════════
# 阶段4：依赖排序
# ══════════════════════════════════════════════════════════


def _order_by_dependency(grouped: dict[str, list[dict]]) -> list[dict]:
    """
    按依赖层级排序。

    规则：
    1. 全局按 DEPENDENCY_LEVEL 升序（数字小的先执行）
    2. 同层级内按 sort_order 升序
    3. step_analysis 同层级内按 step_id 中的时间戳排序
    """
    all_tasks = []
    for task_type, task_list in grouped.items():
        for t in task_list:
            all_tasks.append(t)

    def _sort_key(task: dict) -> tuple[int, int, str]:
        task_type = task["task_type"]
        level = DEPENDENCY_LEVEL.get(task_type, 50)

        if task_type == "step_analysis":
            step_id = task["payload"].get("step_id", "")
            ts = _extract_step_timestamp(step_id)
            return (level, 0, ts)

        return (level, task.get("sort_order", 0), "")

    all_tasks.sort(key=_sort_key)
    return all_tasks


def _extract_step_timestamp(step_id: str) -> str:
    """从 step_id 提取时间戳用于排序。
    step_id 格式: {conv_id}_step_{HHMMSSffffff}
    """
    if not step_id:
        return "99999999999999"
    parts = step_id.rsplit("_step_", 1)
    if len(parts) == 2:
        return parts[1]
    return step_id


# ══════════════════════════════════════════════════════════
# 阶段5：装配入队
# ══════════════════════════════════════════════════════════


def _enqueue_ordered_tasks(ordered_tasks: list[dict], stats: RecoveryStats) -> int:
    """将排好序的任务逐个提交到 task_queue。"""
    try:
        from backend.core.task_queue_kernel.queue_client import get_task_queue

        tq = get_task_queue()
    except Exception as e:
        logger.error(f"[恢复流水线] 获取 task_queue 失败: {e}")
        return 0

    enqueued = 0

    for task in ordered_tasks:
        task_id = task["task_id"]
        task_type = task["task_type"]
        payload = task["payload"]
        status = task.get("status", "pending")

        if status in ("completed", "cancelled", "duplicate_discarded"):
            continue

        if task.get("retry_count", 0) >= task.get("max_retries", 3):
            continue

        if task_id in tq._task_map:
            existing = tq._task_map[task_id]
            if existing.get("status") not in ("pending", "queued", "failed", "timeout"):
                continue

        try:
            _enqueue_single(tq, task_id, task_type, payload, task)
            enqueued += 1
        except Exception as e:
            logger.error(f"[恢复流水线] 入队失败: {task_id} | {e}")
            stats.errors.append(f"enqueue_failed:{task_id}:{e}")

    return enqueued


def _enqueue_single(tq, task_id: str, task_type: str, payload: dict, task_meta: dict):
    """将单个任务加入 task_queue 内存队列。"""
    from backend.core.database.base_conn import get_db

    try:
        db = get_db()
        db.query_local(
            "UPDATE task_queue SET status = 'pending', started_at = NULL, "
            "worker_id = NULL WHERE task_id = ? AND status != 'running'",
            (task_id,),
        )
    except Exception:
        logger.warning("_enqueue_single: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        pass

    meta = {
        "task_id": task_id,
        "task_type": task_type,
        "payload": payload,
        "status": "pending",
        "priority": task_meta.get("priority", 5),
        "max_retries": task_meta.get("max_retries", 3),
        "retry_count": task_meta.get("retry_count", 0),
        "timeout_seconds": task_meta.get("timeout_seconds", 10800),
        "estimated_memory_mb": task_meta.get("estimated_memory_mb", 100),
        "error_message": task_meta.get("error_message", ""),
    }

    tq._task_map[task_id] = meta

    from backend.core.task_queue_kernel.queue_client import QueuedTask

    with tq._queue_lock:
        tq._task_queue.append(QueuedTask(task_id, meta))

    logger.debug(f"[恢复流水线] 入队: {task_id} ({task_type})")


# ══════════════════════════════════════════════════════════
# 两扇门的调用入口
# ══════════════════════════════════════════════════════════


def recover_on_startup() -> RecoveryStats:
    """门A：启动时恢复中断任务。"""
    return run_recovery_pipeline(source=RecoverySource.STARTUP)


def recover_on_periodic() -> RecoveryStats:
    """门B：定时扫描补充。"""
    return run_recovery_pipeline(source=RecoverySource.PERIODIC)


def get_pipeline_stats() -> dict[str, Any]:
    """获取恢复流水线的运行状态（供 Dashboard 查询）。"""
    try:
        from backend.core.database.base_conn import get_db

        db = get_db()
        rows = db.query_local("""
            SELECT status, task_type, COUNT(*) as cnt
            FROM task_queue
            WHERE status IN ('pending', 'queued', 'running', 'failed', 'timeout', 'duplicate_discarded')
              AND is_deleted = 0
            GROUP BY status, task_type
            ORDER BY status, task_type
        """)
        breakdown = {}
        for r in rows or []:
            key = f"{r['status']}:{r['task_type']}"
            breakdown[key] = r["cnt"]

        return {
            "total_unfinished": sum(breakdown.values()),
            "breakdown": breakdown,
            "dedup_keys": DEDUP_KEYS,
            "dependency_levels": DEPENDENCY_LEVEL,
        }
    except Exception as e:
        logger.warning("get_pipeline_stats: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return {"error": str(e)}
