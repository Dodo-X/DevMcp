"""
每日总结技能 v9.10.0 — 日报生成 + 数据查询 + 归档
==================================================
v9.10.0: 多级报告（周报/月报/年报）拆分到 reports.py
v9.9.1: output_data 精简 — 只提取 4 个关键字段
v9.8.2: 职责精简 — 日报仅做 LLM 日历日记 + MD 导出

数据流向：
  record_dialogue → SQLite DB → LLM 分析 → MD 文件（永久保留）
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def get_daily_work_data(date_str: str = None, fallback_to_log: bool = False) -> dict:
    """
    获取指定日期的工作数据（给 LLM 分析用的原始数据）

    v9.8.3 重构：以 conversation 为单位组织数据
    - conversation 级别：topic, task_type, system_id, self_reflection, user_raw_input
    - step 级别：仅 output_data（step_analysis 的分析结果，不含 step_id/knowledge_points_created/files_indexed）
    - 知识点等精细数据由 DB 直读，不传给 LLM 总结

    参数：
    - date_str: 日期字符串 YYYY-MM-DD
    - fallback_to_log: 已废弃，保留仅为兼容旧调用
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    result = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "conversations": [],
        "stats": {},
        "systems": [],
        "data_source": "db",
    }

    try:
        from backend.core.database.base_conn import get_db

        db = get_db()

        convs = db.query_local(
            """SELECT conversation_id, topic, task_type,
                      system_id, self_reflection, user_raw_input
               FROM conversations
               WHERE date(timestamp) = ?
               ORDER BY timestamp ASC""",
            (date_str,),
        )

        seen_systems = set()

        for c in convs or []:
            conv_id = c.get("conversation_id", "")
            system_id = c.get("system_id", "")

            if system_id:
                seen_systems.add(system_id)

            entry = {
                "topic": c.get("topic", "") or "",
                "task_type": c.get("task_type", "") or "",
                "system_id": system_id or "",
                "self_reflection": (c.get("self_reflection", "") or "")[:3000],
                "user_raw_input": (c.get("user_raw_input", "") or "")[:3000],
                "conversation_steps": [],
            }

            # 只取 output_data（step_analysis 分析结果）
            if conv_id:
                steps = db.query_local(
                    """SELECT output_data
                       FROM conversation_steps
                       WHERE conversation_id = ?
                       ORDER BY step_order""",
                    (conv_id,),
                )
                for s in steps or []:
                    raw = s.get("output_data", "")
                    if not raw:
                        continue
                    try:
                        parsed = json.loads(raw) if isinstance(raw, str) else raw
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(parsed, dict):
                        continue

                    # v9.9.1: 只提取4个关键字段传给 daily_summary，避免 output_data 过大导致 Ollama 截断
                    # output_data 完整 JSON 包含 ~15 个字段（knowledge_points 数组、commands_used 数组等），
                    # 每个 step 可能 2-5KB，一天 10+ steps × 15 convs = 300KB+ 数据传给 LLM 直接炸裂
                    clean = {}
                    for field in (
                        "step_summary",
                        "problem_solving_pattern",
                        "key_insights",
                        "improvement_suggestions",
                    ):
                        if field in parsed:
                            clean[field] = parsed[field]
                    if clean:
                        entry["conversation_steps"].append({"output_data": clean})

            result["conversations"].append(entry)

        result["systems"] = sorted(seen_systems)

        result["stats"] = db.get_daily_stats(date_str)

    except Exception as e:
        logger.warning("get_daily_work_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        result["db_error"] = str(e)

    return result


def get_weekly_work_data() -> dict:
    """获取最近7天的工作数据概览"""
    today = date.today()
    days = []

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        day_data = {"date": d_str, "conversation_count": 0, "tasks": []}

        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            stats = db.get_daily_stats(d_str)
            day_data["conversation_count"] = stats.get("total", 0)
            day_data["tasks"] = stats.get("by_type", {})
        except Exception:
            logger.warning(
                "get_weekly_work_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            pass

        days.append(day_data)

    return {
        "generated_at": datetime.now().isoformat(),
        "week_start": days[0]["date"] if days else "",
        "week_end": days[-1]["date"] if days else "",
        "days": days,
        "total_conversations": sum(d["conversation_count"] for d in days),
    }


# ============================================================
# 公共入口函数
# ============================================================


def generate_daily_summary(date_str: str = "", use_llm: bool = True) -> dict:
    """
    生成每日工作总结（v5.0 - LLM 增强版）

    被 server.py 调用，封装 get_daily_work_data + 可选 LLM 智能分析。

    Args:
        date_str: 日期字符串（YYYY-MM-DD），默认今天
        use_llm: 是否使用 LLM 生成智能总结（默认 True）

    Returns:
        dict: 每日工作总结（含 LLM 分析结果或原始数据）
    """
    try:
        # Step 1: 获取原始工作数据
        data = get_daily_work_data(date_str, fallback_to_log=True)

        if not data.get("conversations") and not data.get("stats"):
            # 空数据返回
            return {
                "success": True,
                "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                "summary": {"message": "今日暂无工作记录"},
                "analysis_method": "none",
                "llm_available": False,
            }

        target_date = date_str or datetime.now().strftime("%Y-%m-%d")

        # Step 2: 尝试使用 LLM 智能生成
        llm_analysis = None
        if use_llm:
            try:
                from backend.core.llm_kernel.base_client import get_llm_engine

                llm = get_llm_engine()

                # 检查是否启用 LLM 总结功能
                cfg = llm._get_config()
                if getattr(cfg.llm, "enhance_daily_summary", False) and llm.is_available():
                    logger.info(f"使用 LLM 生成 {target_date} 的每日总结...")
                    llm_analysis = llm.generate_daily_summary(target_date, data)

                    if llm_analysis:
                        logger.info("LLM 每日总结生成成功")
                        return {
                            "success": True,
                            "date": target_date,
                            **llm_analysis,
                            "raw_data": data,
                            "analysis_method": "llm",
                            "llm_available": True,
                        }
            except Exception as e:
                logger.warning(f"LLM 每日总结生成失败，回退到原始数据: {e}")

        # Step 3: LLM 不可用或失败，返回结构化原始数据
        tasks = data.get("conversations", [])
        stats = data.get("stats", {})

        result = {
            "success": True,
            "date": target_date,
            "summary": {
                "total_conversations": len(tasks),
                "task_types": stats.get("by_type", {}),
                "systems_active": data.get("systems", []),
            },
            "conversations": tasks[:20],
            "raw_data": data,
            "analysis_method": "rules_fallback" if use_llm else "data_only",
            "llm_available": bool(llm_analysis),
            "note": "已返回原始数据（可由 AI 客户端自行分析）" if not llm_analysis else "",
        }

        return result

    except Exception as e:
        logger.warning("generate_daily_summary: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "date": date_str or datetime.now().strftime("%Y-%m-%d"),
            "analysis_method": "error",
        }


def _check_llm_available(feature_flag: str = "enhance_daily_summary") -> tuple:
    """检查 LLM 是否可用，返回 (available: bool, reason: str)

    Args:
        feature_flag: 要检查的配置开关名（enhance_daily_summary / enhance_profile_merge / enhance_weekly_report）
    """
    try:
        from backend.core.llm_kernel.base_client import get_llm_engine

        llm = get_llm_engine()
        if not llm.is_available():
            return False, "LLM 引擎未加载或服务不可用"
        cfg = llm._get_config()
        if not getattr(cfg.llm, feature_flag, False):
            return False, f"feature flag {feature_flag} 未开启"
        return True, ""
    except Exception as e:
        logger.warning("_check_llm_available: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return False, f"LLM 检查异常: {e}"


def _write_pending_analysis(
    db,
    analysis_type: str,
    source_date: str,
    raw_data: dict,
    missing_dimensions: list,
    system_id: str = "default",
    error_message: str = "",
):
    """将未完成的分析数据写入 pending_analyses 表"""
    now_str = datetime.now().isoformat()
    db.query_local(
        """
        INSERT INTO pending_analyses (
            analysis_type, source_date, system_id, raw_data,
            missing_dimensions, retry_count, created_at, last_attempted_at, status, error_message
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'pending', ?)
    """,
        (
            analysis_type,
            source_date,
            system_id,
            json.dumps(raw_data, ensure_ascii=False)[:50000],
            json.dumps(missing_dimensions, ensure_ascii=False),
            now_str,
            now_str,
            error_message,
        ),
    )
    logger.warning(
        f"⚠️ LLM 不可用，数据已暂存 pending_analyses: type={analysis_type}, date={source_date}, 缺失维度={missing_dimensions}"
    )


def process_pending_analyses() -> dict:
    """
    清算历史待分析数据（v8.0）

    优先处理 pending_analyses 表中 status='pending' 的记录，
    按创建时间从早到晚依次重试。LLM 仍不可用则跳过，不改变状态。

    Returns:
        {"processed": N, "still_pending": N, "details": [...]}
    """
    result = {"processed": 0, "still_pending": 0, "details": []}

    try:
        from backend.core.database.base_conn import get_db

        db = get_db()

        pending_rows = db.query_local(
            "SELECT id, analysis_type, source_date, system_id, raw_data, "
            "missing_dimensions, retry_count, created_at "
            "FROM pending_analyses WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT 50"
        )

        if not pending_rows:
            result["note"] = "无待分析数据"
            return result

        llm_ok, llm_reason = _check_llm_available()
        if not llm_ok:
            result["still_pending"] = len(pending_rows)
            result["note"] = f"LLM 仍不可用: {llm_reason}，跳过清算"
            logger.warning(f"⏸️ 清算跳过: LLM 不可用 ({llm_reason})，{len(pending_rows)} 条待分析")
            return result

        for row in pending_rows:
            try:
                raw_data = row["raw_data"]
                if isinstance(raw_data, str):
                    raw_data = json.loads(raw_data)
                missing_dims = row["missing_dimensions"]
                if isinstance(missing_dims, str):
                    missing_dims = json.loads(missing_dims)

                analysis_type = row["analysis_type"]
                source_date = row["source_date"]
                row.get("system_id", "default")

                # v9.8.2: daily_profile_merge / daily_system_merge 已废弃
                # 用户画像/业务知识由 finalize 子任务实时处理，pending 中的旧数据直接标记为 deprecated
                if analysis_type in ("daily_profile_merge", "daily_system_merge"):
                    sub_result = {
                        "success": True,
                        "deprecated": True,
                        "note": f"{analysis_type} 已废弃，由 finalize 子任务替代",
                    }
                else:
                    sub_result = {"success": False, "error": f"未知分析类型: {analysis_type}"}

                if sub_result.get("success"):
                    db.query_local(
                        "UPDATE pending_analyses SET status = 'completed', last_attempted_at = ? WHERE id = ?",
                        (datetime.now().isoformat(), row["id"]),
                    )
                    result["processed"] += 1
                    result["details"].append(
                        {
                            "id": row["id"],
                            "type": analysis_type,
                            "date": source_date,
                            "status": "completed",
                        }
                    )
                else:
                    db.query_local(
                        "UPDATE pending_analyses SET retry_count = retry_count + 1, "
                        "last_attempted_at = ?, error_message = ? WHERE id = ?",
                        (datetime.now().isoformat(), sub_result.get("error", "unknown"), row["id"]),
                    )
                    result["details"].append(
                        {
                            "id": row["id"],
                            "type": analysis_type,
                            "date": source_date,
                            "status": "retry_failed",
                        }
                    )

            except Exception as e:
                logger.error(f"清算待分析数据失败 [id={row['id']}]: {e}")
                result["details"].append(
                    {
                        "id": row["id"],
                        "type": row.get("analysis_type", ""),
                        "date": row.get("source_date", ""),
                        "status": "error",
                        "error": str(e),
                    }
                )

        result["still_pending"] = len(
            db.query_local("SELECT id FROM pending_analyses WHERE status = 'pending'") or []
        )

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"清算待分析数据异常: {e}", exc_info=True)

    return result


# ============================================================
# v9.8.2: _execute_profile_merge_llm / _execute_system_merge_llm 已删除
# 用户画像/业务知识由 finalize 子任务实时处理，不再需要每日二次 LLM 合并
# ============================================================

# ============================================================
# v8.0: 数据生命周期管理 — 分层归档 + 清理
# ============================================================


def archive_and_cleanup_data() -> dict:
    """
    数据生命周期管理：分层归档 + 清理（v8.0）

    执行顺序：
    1. 清理 pending_analyses 中超过最大重试次数的记录
    2. 温数据归档：30-180天的对话，压缩 steps 详情
    3. 冷数据归档：超过180天的对话，标记 archive_tier='archived'
    4. 深度清理：超过365天，直接删除（MD为唯一数据源）
    5. 清理过期的 improvement_log / evolution_log

    数据生命周期：
    ┌─────────────┬──────────────────────┬──────────────────────┐
    │ 阶段        │ SQLite 存储          │ MD 文件              │
    ├─────────────┼──────────────────────┼──────────────────────┤
    │ 热数据(0-30)│ 完整保留             │ 实时导出             │
    │ 温数据(30-  │ 保留摘要+信号        │ 已导出（不变）       │
    │   180)      │ 清理steps详情        │                      │
    │ 冷数据(180- │ 仅archived_conv摘要  │ 唯一完整数据源       │
    │   365)      │ 删除原始conversations│                      │
    │ 归档(>365)  │ 删除archived_conv    │ 唯一数据源           │
    └─────────────┴──────────────────────┴──────────────────────┘

    SQL 优化：
    - 使用 archive_tier 字段标记归档状态（hot/warm/cold/archived）
    - 查询条件增加 archive_tier 过滤，避免重复扫描已处理记录
    - 处理完成后更新 archive_tier，确保幂等性

    数据提炼保障：
    - 温数据归档前：校验日报 MD 是否已导出（Calendar/{date}.md 存在）
    - 冷数据归档前：校验日报 MD + 知识卡片 MD 均已导出
    - 校验失败则跳过该记录，下次归档时重试

    Returns:
        {"warm_archived": N, "cold_archived": N, "deep_cleaned": N, ...}
    """
    result = {
        "warm_archived": 0,
        "cold_archived": 0,
        "deep_cleaned": 0,
        "pending_failed": 0,
        "logs_cleaned": 0,
        "errors": [],
    }

    try:
        from foundation.config.app_settings import get_config

        from backend.core.database.base_conn import get_db

        db = get_db()
        cfg = get_config()
        lc = cfg.data_lifecycle

        now = datetime.now()

        # ── 1. 清理 pending_analyses 超过最大重试次数的记录 ──
        try:
            max_retry = getattr(lc, "pending_analyses_max_retry", 10)
            failed_rows = db.query_local(
                "SELECT id FROM pending_analyses WHERE retry_count >= ? AND status = 'pending'",
                (max_retry,),
            )
            if failed_rows:
                for row in failed_rows:
                    db.query_local(
                        "UPDATE pending_analyses SET status = 'failed', error_message = ? WHERE id = ?",
                        (f"超过最大重试次数({max_retry})", row["id"]),
                    )
                result["pending_failed"] = len(failed_rows)
                logger.info(
                    f"📋 标记 {len(failed_rows)} 条 pending_analyses 为 failed（超过最大重试次数）"
                )
        except Exception as e:
            logger.warning(
                "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["errors"].append(f"pending清理失败: {e}")

        # ── 2. 温数据归档：30-180天，压缩 steps 详情 ──
        try:
            warm_days = getattr(lc, "conversation_warm_days", 180)
            hot_days = getattr(lc, "conversation_hot_days", 30)
            warm_cutoff = (now - timedelta(days=warm_days)).strftime("%Y-%m-%d")
            hot_cutoff = (now - timedelta(days=hot_days)).strftime("%Y-%m-%d")

            warm_convs = db.query_local(
                "SELECT conversation_id, id, timestamp FROM conversations "
                "WHERE date(timestamp) < ? AND date(timestamp) >= ? "
                "AND archive_tier = 'hot' AND analyzed = 1",
                (hot_cutoff, warm_cutoff),
            )

            if warm_convs:
                from backend.business.vault_export.vault_exporter import get_vault_exporter

                exporter = get_vault_exporter()
                calendar_dir = exporter._calendar_dir
                archived_count = 0
                skipped_count = 0

                for conv in warm_convs:
                    try:
                        conv_date = conv.get("timestamp", "")[:10]
                        md_path = calendar_dir / f"{conv_date}.md"

                        if not md_path.exists():
                            skipped_count += 1
                            continue

                        db.query_local(
                            "UPDATE conversation_steps SET input_data = NULL, output_data = NULL "
                            "WHERE conversation_id = ?",
                            (conv["conversation_id"],),
                        )
                        db.query_local(
                            "UPDATE conversations SET archive_tier = 'warm' WHERE conversation_id = ?",
                            (conv["conversation_id"],),
                        )
                        archived_count += 1
                    except Exception:
                        logger.warning(
                            "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）",
                            exc_info=True,
                        )
                        pass

                result["warm_archived"] = archived_count
                result["warm_skipped"] = skipped_count
                if archived_count > 0 or skipped_count > 0:
                    logger.info(
                        f"📦 温数据归档完成: {archived_count} 个对话已压缩, {skipped_count} 个跳过（MD未导出）"
                    )
        except Exception as e:
            logger.warning(
                "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["errors"].append(f"温数据归档失败: {e}")

        # ── 3. 冷数据归档：超过180天，标记为 'archived'（v9.2: 不再使用 archived_conversations 表）──
        try:
            cold_days = getattr(lc, "conversation_warm_days", 180)
            cold_cutoff = (now - timedelta(days=cold_days)).strftime("%Y-%m-%d")

            cold_rows = db.query_local(
                "SELECT COUNT(*) as cnt FROM conversations WHERE date(timestamp) < ? "
                "AND archive_tier IN ('hot', 'warm') AND analyzed = 1",
                (cold_cutoff,),
            )
            cold_count = cold_rows[0]["cnt"] if cold_rows else 0
            if cold_count > 0:
                db.query_local(
                    "UPDATE conversations SET archive_tier = 'archived', updated_at = ? "
                    "WHERE date(timestamp) < ? AND archive_tier IN ('hot', 'warm') AND analyzed = 1",
                    (now.isoformat(), cold_cutoff),
                )
                result["cold_archived"] = cold_count
                logger.info(f"🗄️ 冷数据归档完成: {cold_count} 个对话标记为 'archived'")
        except Exception as e:
            logger.warning(
                "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["errors"].append(f"冷数据归档失败: {e}")

        # ── 4. 深度清理：超过365天，直接删除（v9.2: MD 为唯一完整数据源）──
        try:
            deep_days = getattr(lc, "conversation_cold_days", 365)
            deep_cutoff = (now - timedelta(days=deep_days)).strftime("%Y-%m-%d")

            deep_rows = db.query_local(
                "SELECT id FROM conversations WHERE date(timestamp) < ? AND archive_tier = 'archived'",
                (deep_cutoff,),
            )
            if deep_rows:
                # v9.5.3: conversations_id 列已删除，通过 conversation_id (TEXT FK) 关联删除
                for r in deep_rows:
                    db.query_local(
                        "DELETE FROM conversation_steps WHERE conversation_id = (SELECT conversation_id FROM conversations WHERE id = ?)",
                        (r["id"],),
                    )
                db.query_local(
                    "DELETE FROM conversations WHERE date(timestamp) < ? AND archive_tier = 'archived'",
                    (deep_cutoff,),
                )
                result["deep_cleaned"] = len(deep_rows)
                logger.info(f"🗑️ 深度清理完成: {len(deep_rows)} 条对话已删除（MD为唯一数据源）")
        except Exception as e:
            logger.warning(
                "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["errors"].append(f"深度清理失败: {e}")

        # ── 5. 清理过期的 improvement_log / evolution_log ──
        try:
            log_days = getattr(lc, "log_retention_days", 90)
            log_cutoff = (now - timedelta(days=log_days)).strftime("%Y-%m-%d")

            il_count = 0
            try:
                il_rows = db.query_local(
                    "SELECT COUNT(*) as cnt FROM improvement_log WHERE date(timestamp) < ?",
                    (log_cutoff,),
                )
                il_count = il_rows[0]["cnt"] if il_rows else 0
                if il_count > 0:
                    db.query_local(
                        "DELETE FROM improvement_log WHERE date(timestamp) < ? AND status != 'pending'",
                        (log_cutoff,),
                    )
            except Exception:
                logger.warning(
                    "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            el_count = 0
            try:
                el_rows = db.query_local(
                    "SELECT COUNT(*) as cnt FROM evolution_log WHERE date(timestamp) < ?",
                    (log_cutoff,),
                )
                el_count = el_rows[0]["cnt"] if el_rows else 0
                if el_count > 0:
                    db.query_local(
                        "DELETE FROM evolution_log WHERE date(timestamp) < ?",
                        (log_cutoff,),
                    )
            except Exception:
                logger.warning(
                    "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

            result["logs_cleaned"] = il_count + el_count
            if il_count + el_count > 0:
                logger.info(
                    f"🧹 日志清理完成: improvement_log {il_count}条, evolution_log {el_count}条"
                )
        except Exception as e:
            logger.warning(
                "archive_and_cleanup_data: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            result["errors"].append(f"日志清理失败: {e}")

    except Exception as e:
        result["errors"].append(f"归档流程异常: {e}")
        logger.error(f"数据归档流程异常: {e}", exc_info=True)

    return result


# ============================================================
# v8.0: 周报 / 月报 / 年报 生成
# ============================================================


def _get_user_profile_snapshot(db) -> str:
    """获取当前用户画像快照（用于报告 prompt 输入）"""
    try:
        rows = db.query_local("SELECT dimension, value, confidence, trend FROM user_profile")
        if not rows:
            return "暂无用户画像数据"
        parts = []
        for row in rows or []:
            parts.append(
                f"- {row['dimension']}: {row['value']} (置信度={row.get('confidence', 0.5)}, 趋势={row.get('trend', 'stable')})"
            )
        return "\n".join(parts)
    except Exception:
        logger.warning(
            "_get_user_profile_snapshot: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return "用户画像获取失败"


def _get_project_profile_snapshot(db) -> str:
    """获取当前项目画像快照（用于报告 prompt 输入）"""
    try:
        rows = db.query_local(
            "SELECT system_id, tech_stack, architecture, business_domains, maturity FROM connected_systems"
        )
        if not rows:
            return "暂无项目画像数据"
        parts = []
        for row in rows or []:
            parts.append(f"### {row['system_id']}")
            parts.append(f"- 技术栈: {row.get('tech_stack', '[]')}")
            parts.append(f"- 架构: {row.get('architecture', '{}')}")
            parts.append(f"- 业务领域: {row.get('business_domains', '[]')}")
            parts.append(f"- 成熟度: {row.get('maturity', 'unknown')}")
        return "\n".join(parts)
    except Exception:
        logger.warning(
            "_get_project_profile_snapshot: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return "项目画像获取失败"


def _read_md_reports(
    directory: Path, limit: int = 10, date_from: str = None, date_to: str = None
) -> list:
    """
    读取指定目录下最近的 MD 报告内容（v8.0 — 从 MD 文件读取，不依赖 SQLite）

    支持按日期范围过滤，实现文件名强关联：
    - 日报文件名格式: {YYYY-MM-DD}.md
    - 周报文件名格式: {YYYY-WXX}.md
    - 月报文件名格式: {YYYY-MM}.md

    Args:
        directory: 报告目录
        limit: 最大读取数量
        date_from: 起始日期（含），格式 YYYY-MM-DD，None 则不限
        date_to: 结束日期（含），格式 YYYY-MM-DD，None 则不限
    """
    reports = []
    if not directory.exists():
        return reports

    md_files = sorted(directory.glob("*.md"), reverse=True)

    for f in md_files:
        stem = f.stem

        if date_from or date_to:
            file_date = None
            if re.match(r"\d{4}-\d{2}-\d{2}", stem) or re.match(r"\d{4}-W\d{2}", stem):
                file_date = stem
            elif re.match(r"\d{4}-\d{2}", stem):
                file_date = stem + "-01"

            if file_date:
                if date_from and file_date < date_from:
                    continue
                if date_to and file_date > date_to:
                    continue

        try:
            content = f.read_text(encoding="utf-8", errors="replace")[:2000]
            reports.append({"file": f.name, "content": content})
        except Exception:
            logger.warning("_read_md_reports: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
            pass

        if len(reports) >= limit:
            break

    return reports


# ══════════════════════════════════════════════════════════
# v9.10.0: 多级报告（周报/月报/年报）已拆分到 reports.py
# 以下为向后兼容的重导出（延迟导入，规避 daily_summary ↔ reports 循环导入）


def generate_weekly_report(*args, **kwargs):
    """向后兼容重导出：委托 reports.generate_weekly_report（延迟导入规避循环导入）。"""
    from backend.business.task_handlers.reports import generate_weekly_report as _impl

    return _impl(*args, **kwargs)


def generate_monthly_report(*args, **kwargs):
    """向后兼容重导出：委托 reports.generate_monthly_report（延迟导入规避循环导入）。"""
    from backend.business.task_handlers.reports import generate_monthly_report as _impl

    return _impl(*args, **kwargs)


def generate_annual_report(*args, **kwargs):
    """向后兼容重导出：委托 reports.generate_annual_report（延迟导入规避循环导入）。"""
    from backend.business.task_handlers.reports import generate_annual_report as _impl

    return _impl(*args, **kwargs)


# ══════════════════════════════════════════════════════════
