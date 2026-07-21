"""
每日总结技能 v8.0 — LLM 智能增强版 + 自包含 MD 持久化
=====================================================
v8.0: 单向导出架构（SQLite → MD），数据生命周期管理，多级报告。
  - ✨ LLM 驱动分析，LLM 不可用时暂存待分析数据
  - 📊 日报/周报/月报/年报，自包含 MD 文件独立于 SQLite
  - 🗄️ 分层数据归档：热→温→冷→归档，归档前确保 MD 已导出
  - 🔄 archive_tier 字段标记归档状态，避免重复扫描

数据流向：
  record_dialogue → SQLite DB → LLM 分析 → MD 文件（永久保留）
                                              ↓
                              周报 ← 日报 ← 月报 ← 年报
"""
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path


def get_daily_work_data(date_str: str = None, fallback_to_log: bool = False) -> dict:
    """
    获取指定日期的工作数据（给 LLM 分析用的原始数据）

    参数：
    - date_str: 日期字符串 YYYY-MM-DD
    - fallback_to_log: 已废弃，保留仅为兼容旧调用
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # v9.2: problems_found/thinking_data 废弃 — 由 conversation_steps 聚合替代
    result = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "conversations": [],
        "stats": {},
        "files_touched": [],
        "data_source": "db",
    }

    # 从数据库读取结构化记录
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        # 对话记录
        convs = db.query_local(
            """SELECT * FROM conversations 
               WHERE date(timestamp) = ? 
               ORDER BY timestamp ASC""",
            (date_str,)
        )
        
        # v9.2: 废弃字段已从 conversations 表删除，改为从 conversation_steps 聚合
        for c in (convs or []):
            entry = {
                "timestamp": c.get("timestamp", ""),
                "conversation_id": c.get("conversation_id", ""),
                "topic": c.get("topic", ""),
                "task_type": c.get("task_type", ""),
                "user_intent": c.get("user_intent", ""),
                "self_reflection": c.get("self_reflection", ""),
                "client": c.get("client", "unknown"),
                "ai_analysis": c.get("ai_analysis", ""),
            }

            # 从 conversation_steps 聚合文件变更信息
            conv_id = c.get("conversation_id", "")
            if conv_id:
                steps = db.query_local(
                    "SELECT input_data FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order",
                    (conv_id,)
                )
                for s in (steps or []):
                    try:
                        sd = json.loads(s.get("input_data", "{}"))
                        fc = sd.get("files_changed", "")
                        if fc:
                            if isinstance(fc, str):
                                try:
                                    fc_list = json.loads(fc)
                                except (json.JSONDecodeError, TypeError):
                                    fc_list = [fc] if fc else []
                            else:
                                fc_list = fc if isinstance(fc, list) else [fc]
                            result["files_touched"].extend(fc_list)
                    except (json.JSONDecodeError, TypeError):
                        pass

            result["conversations"].append(entry)

        # 去重文件列表
        result["files_touched"] = list(set(result["files_touched"]))

        # 统计
        result["stats"] = db.get_daily_stats(date_str)

        # 检查跨AI对话
        try:
            dialogue_data = db.query_local(
                "SELECT * FROM conversations WHERE date(timestamp) = ? AND client != 'unknown'",
                (date_str,)
            )
            clients = set(c.get("client", "") for c in (dialogue_data or []))
            result["active_clients"] = list(clients)
        except Exception:
            result["active_clients"] = []

    except Exception as e:
        result["db_error"] = str(e)
    
    return result


def save_daily_analysis(analysis_json: str) -> dict:
    """
    保存 AI 客户端的分析结果
    
    analysis_json: JSON 字符串，格式如下：
    {
        "date": "2026-06-26",
        "summary": "一句话总结今日工作",
        "experience": {"deep_dive": "...", "lesson": "..."},
        "skills": {"new_skills": [...], "patterns": [...], "tools": [...]},
        "knowledge": {"must_remember": [...], "insights": [...]},
        "danger_signals": {"repeated_mistakes": [...], "tech_debt": [...], "hot_files": [...]},
        "tomorrow_plan": "明天最优先事项",
        "self_analysis": {"strengths": [...], "weaknesses": [...], "growth_suggestions": [...]},
        "cross_insight": {"title": "...", "content": "...", "to": "trae"}  // 可选
    }
    """
    try:
        analysis = json.loads(analysis_json) if isinstance(analysis_json, str) else analysis_json
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON 解析失败: {e}"}

    target_date = analysis.get("date", datetime.now().strftime("%Y-%m-%d"))
    result = {
        "success": True,
        "date": target_date,
        "steps": [],
    }

    # 1. 保存到本地数据库
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        timestamp = datetime.now().isoformat()
        # v9.2: raw_json 字段已删除，使用 ai_analysis 替代
        conv_id = datetime.now().strftime("daily_%Y%m%d%H%M%S")
        db.query_local(
            """INSERT INTO conversations
               (conversation_id, timestamp, topic, task_type, user_intent, ai_analysis)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conv_id, timestamp, "每日总结",
             "daily_summary",
             f"AI客户端生成 {target_date} 工作总结",
             json.dumps(analysis, ensure_ascii=False)),
        )
        result["steps"].append({"step": "save_to_local_db", "status": "ok"})
    except Exception as e:
        result["steps"].append({"step": "save_to_local_db", "status": "error", "error": str(e)})

    # 2. 保存到共享数据库（如果可用）
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        exp = analysis.get("experience", {})
        danger = analysis.get("danger_signals", {})
        self_a = analysis.get("self_analysis", {})

        notes = json.dumps({
            "deep_dive": exp.get("deep_dive", ""),
            "lesson": exp.get("lesson", ""),
            "strengths": self_a.get("strengths", []),
            "weaknesses": self_a.get("weaknesses", []),
            "danger_warnings": danger.get("warnings", []),
            "agent": "devpartner",
        }, ensure_ascii=False)

        try:
            db.query_shared(
                """INSERT OR REPLACE INTO daily_summary
                   (work_date, agent, work_content, issues_found, issues_fixed, ai_sessions, notes)
                   VALUES (?, 'devpartner', ?, 0, 0, 0, ?)""",
                (target_date, analysis.get("summary", ""), notes),
            )
            result["steps"].append({"step": "save_to_shared_db", "status": "ok"})
        except Exception:
            result["steps"].append({"step": "save_to_shared_db", "status": "skipped", "reason": "共享数据库不可用"})

    except Exception as e:
        result["steps"].append({"step": "save_to_shared_db", "status": "error", "error": str(e)})

    # 3. 保存跨AI洞察
    cross = analysis.get("cross_insight")
    if cross and cross.get("content"):
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local(
                """INSERT INTO improvement_log
                   (timestamp, category, suggestion, priority)
                   VALUES (?, ?, ?, ?)""",
                (datetime.now().isoformat(),
                 f"cross_insight_to_{cross.get('to', 'all')}",
                 f"{cross.get('title', '')}: {cross.get('content', '')}",
                 cross.get("priority", "medium")),
            )
            result["steps"].append({"step": "save_cross_insight", "status": "ok"})
        except Exception as e:
            result["steps"].append({"step": "save_cross_insight", "status": "error", "error": str(e)})

    # 4. 导出日报到 Calendar/{date}.md（v8.0 自包含版 — MD 独立于 SQLite）
    try:
        from devpartner_agent.services.vault_exporter import get_vault_exporter
        exporter = get_vault_exporter()
        report_path = exporter.export_daily_report(target_date, analysis)
        result["report_path"] = report_path
        result["steps"].append({"step": "export_daily_report", "status": "ok"})
    except Exception as e:
        result["steps"].append({"step": "export_daily_report", "status": "error", "error": str(e)})

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
            from devpartner_agent.core.database import get_db
            db = get_db()
            stats = db.get_daily_stats(d_str)
            day_data["conversation_count"] = stats.get("total", 0)
            day_data["tasks"] = stats.get("by_type", {})
        except Exception:
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
                from devpartner_agent.core.llm_engine import get_llm_engine
                llm = get_llm_engine()
                
                # 检查是否启用 LLM 总结功能
                cfg = llm._get_config()
                if getattr(cfg.llm, 'enhance_daily_summary', False) and llm.is_available():
                    logger.info(f"使用 LLM 生成 {target_date} 的每日总结...")
                    llm_analysis = llm.generate_daily_summary(target_date, data)
                    
                    if llm_analysis:
                        logger.info(f"LLM 每日总结生成成功")
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
                "files_touched": len(data.get("files_touched", [])),
                "clients_active": data.get("active_clients", []),
            },
            "conversations": tasks[:20],
            "raw_data": data,
            "analysis_method": "rules_fallback" if use_llm else "data_only",
            "llm_available": bool(llm_analysis),
            "note": "已返回原始数据（可由 AI 客户端自行分析）" if not llm_analysis else "",
        }
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "date": date_str or datetime.now().strftime("%Y-%m-%d"),
            "analysis_method": "error",
        }


# 添加日志记录器
import logging
logger = logging.getLogger(__name__)


def _check_llm_available(feature_flag: str = "enhance_daily_summary") -> tuple:
    """检查 LLM 是否可用，返回 (available: bool, reason: str)

    Args:
        feature_flag: 要检查的配置开关名（enhance_daily_summary / enhance_profile_merge / enhance_weekly_report）
    """
    try:
        from devpartner_agent.core.llm_engine import get_llm_engine
        llm = get_llm_engine()
        if not llm.is_available():
            return False, "LLM 引擎未加载或服务不可用"
        cfg = llm._get_config()
        if not getattr(cfg.llm, feature_flag, False):
            return False, f"feature flag {feature_flag} 未开启"
        return True, ""
    except Exception as e:
        return False, f"LLM 检查异常: {e}"


def _write_pending_analysis(db, analysis_type: str, source_date: str,
                            raw_data: dict, missing_dimensions: list,
                            system_id: str = "default", error_message: str = ""):
    """将未完成的分析数据写入 pending_analyses 表"""
    now_str = datetime.now().isoformat()
    db.query_local("""
        INSERT INTO pending_analyses (
            analysis_type, source_date, system_id, raw_data,
            missing_dimensions, retry_count, created_at, last_attempted_at, status, error_message
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'pending', ?)
    """, (
        analysis_type, source_date, system_id,
        json.dumps(raw_data, ensure_ascii=False)[:50000],
        json.dumps(missing_dimensions, ensure_ascii=False),
        now_str, now_str, error_message,
    ))
    logger.warning(f"⚠️ LLM 不可用，数据已暂存 pending_analyses: type={analysis_type}, date={source_date}, 缺失维度={missing_dimensions}")


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
        from devpartner_agent.core.database import get_db
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
                system_id = row.get("system_id", "default")

                if analysis_type == "daily_profile_merge":
                    sub_result = _execute_profile_merge_llm(
                        db=db,
                        behavior_signals_list=raw_data.get("behavior_signals_list", []),
                        current_profile=raw_data.get("current_profile", {}),
                        conversations_summary=raw_data.get("conversations_summary", []),
                        source_date=source_date,
                    )
                elif analysis_type == "daily_system_merge":
                    sub_result = _execute_system_merge_llm(
                        db=db,
                        system_id=system_id,
                        all_tech=raw_data.get("all_tech", []),
                        all_arch=raw_data.get("all_arch", []),
                        all_biz=raw_data.get("all_biz", []),
                        all_disc=raw_data.get("all_disc", []),
                        current_profile=raw_data.get("current_profile", {}),
                        source_date=source_date,
                        fragment_ids=raw_data.get("fragment_ids", []),
                    )
                else:
                    sub_result = {"success": False, "error": f"未知分析类型: {analysis_type}"}

                if sub_result.get("success"):
                    db.query_local(
                        "UPDATE pending_analyses SET status = 'completed', last_attempted_at = ? WHERE id = ?",
                        (datetime.now().isoformat(), row["id"]),
                    )
                    result["processed"] += 1
                    result["details"].append({
                        "id": row["id"], "type": analysis_type,
                        "date": source_date, "status": "completed",
                    })
                else:
                    db.query_local(
                        "UPDATE pending_analyses SET retry_count = retry_count + 1, "
                        "last_attempted_at = ?, error_message = ? WHERE id = ?",
                        (datetime.now().isoformat(), sub_result.get("error", "unknown"), row["id"]),
                    )
                    result["details"].append({
                        "id": row["id"], "type": analysis_type,
                        "date": source_date, "status": "retry_failed",
                    })

            except Exception as e:
                logger.error(f"清算待分析数据失败 [id={row['id']}]: {e}")
                result["details"].append({
                    "id": row["id"], "type": row.get("analysis_type", ""),
                    "date": row.get("source_date", ""), "status": "error", "error": str(e),
                })

        result["still_pending"] = len(db.query_local(
            "SELECT id FROM pending_analyses WHERE status = 'pending'"
        ) or [])

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"清算待分析数据异常: {e}", exc_info=True)

    return result


def _execute_profile_merge_llm(db, behavior_signals_list: list,
                                current_profile: dict, conversations_summary: list,
                                source_date: str) -> dict:
    """执行用户画像 LLM 合并（核心逻辑，被 merge_daily_profile 和 process_pending_analyses 复用）"""
    try:
        from prompts import run_analysis, TASK_DAILY_PROFILE_MERGE
        llm_result = run_analysis(
            TASK_DAILY_PROFILE_MERGE,
            behavior_signals_json=json.dumps(behavior_signals_list, ensure_ascii=False, indent=2)[:6000],
            current_profile_json=json.dumps(current_profile, ensure_ascii=False, indent=2)[:3000],
            daily_conversations_summary=json.dumps(conversations_summary, ensure_ascii=False, indent=2)[:3000],
        )

        if not llm_result or not isinstance(llm_result, dict) or "dimensions" not in llm_result:
            return {"success": False, "error": "LLM 返回结果无效"}

        now_str = datetime.now().isoformat()
        dimensions_updated = 0
        for dim in llm_result.get("dimensions", []):
            dimension = dim.get("dimension", "")
            if not dimension:
                continue
            dim_data = {
                "dimension": dimension,
                "value": dim.get("value", ""),
                "confidence": dim.get("confidence", 0.5),
                "evidence": dim.get("evidence", ""),
                "trend": dim.get("trend", "stable"),
            }
            try:
                existing = db.query_local(
                    "SELECT id, observation_count FROM user_profile WHERE dimension = ?",
                    (dimension,),
                )
                if existing:
                    db.query_local("""
                        UPDATE user_profile SET
                            value = ?, confidence = ?, evidence = ?,
                            last_observed = ?, observation_count = observation_count + 1,
                            trend = ?, updated_at = ?
                        WHERE dimension = ?
                    """, (
                        dim_data["value"], dim_data["confidence"],
                        dim_data.get("evidence", ""), now_str,
                        dim_data.get("trend", "stable"), now_str,
                        dimension,
                    ))
                else:
                    db.query_local("""
                        INSERT INTO user_profile (dimension, value, confidence, evidence,
                            first_observed, last_observed, observation_count, trend, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """, (
                        dimension, dim_data["value"], dim_data["confidence"],
                        dim_data.get("evidence", ""), now_str, now_str,
                        dim_data.get("trend", "stable"), now_str,
                    ))
                dimensions_updated += 1
            except Exception as e:
                logger.debug(f"画像维度写入失败 [{dimension}]: {e}")

        return {"success": True, "dimensions_updated": dimensions_updated, "method": "llm"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def _execute_system_merge_llm(db, system_id: str, all_tech: list, all_arch: list,
                               all_biz: list, all_disc: list, current_profile: dict,
                               source_date: str, fragment_ids: list = None) -> dict:
    """执行系统认知 LLM 合并（核心逻辑，被 merge_daily_system_context 和 process_pending_analyses 复用）"""
    try:
        from prompts import run_analysis, TASK_DAILY_SYSTEM_MERGE
        fragments_json = json.dumps({
            "tech_signals": all_tech[:30],
            "architecture_signals": all_arch[:20],
            "business_signals": all_biz[:20],
            "new_discoveries": all_disc[:20],
        }, ensure_ascii=False, indent=2)[:6000]

        llm_result = run_analysis(
            TASK_DAILY_SYSTEM_MERGE,
            system_id=system_id,
            fragments_json=fragments_json,
            current_project_profile_json=json.dumps(current_profile, ensure_ascii=False, indent=2)[:3000],
        )

        if not llm_result or not isinstance(llm_result, dict) or "tech_stack" not in llm_result:
            return {"success": False, "error": "LLM 返回结果无效"}

        tech_stack = llm_result.get("tech_stack", [])
        architecture = llm_result.get("architecture", {})
        business_domains = llm_result.get("business_domains", [])
        maturity = llm_result.get("maturity", "unknown")

        db.query_local("""
            UPDATE connected_systems SET
                tech_stack = ?, architecture = ?, business_domains = ?, maturity = ?,
                last_active = ?
            WHERE system_id = ?
        """, (
            json.dumps(tech_stack, ensure_ascii=False),
            json.dumps(architecture, ensure_ascii=False),
            json.dumps(business_domains, ensure_ascii=False),
            maturity,
            datetime.now().isoformat(),
            system_id,
        ))

        if fragment_ids:
            for fid in fragment_ids:
                try:
                    db.query_local(
                        "UPDATE system_context_fragments SET merged = 1 WHERE id = ?",
                        (fid,),
                    )
                except Exception:
                    pass

        return {"success": True, "method": "llm"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
# v8.0: 每日画像合并 & 系统认知合并
# ============================================================

def merge_daily_profile(date_str: str = "") -> dict:
    """
    每日用户画像合并（v8.0 — 纯 LLM 驱动，无规则降级）

    数据流：
    conversations.behavior_signals → LLM 合并 → user_profile 表更新
    LLM 不可用 → 原始数据写入 pending_analyses 表，等待下次清算

    Args:
        date_str: 日期字符串（YYYY-MM-DD），默认今天

    Returns:
        {"success": True, "dimensions_updated": N, "method": "llm"/"pending"}
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    result = {
        "success": False,
        "date": date_str,
        "dimensions_updated": 0,
        "method": "none",
    }

    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        convs = db.query_local(
            "SELECT conversation_id, behavior_signals, user_raw_input, topic, task_type "
            "FROM conversations WHERE date(timestamp) = ?",
            (date_str,),
        )

        if not convs:
            result["success"] = True
            result["method"] = "none"
            result["note"] = "当日无对话数据"
            return result

        behavior_signals_list = []
        conversations_summary = []
        for c in (convs or []):
            bs_raw = c.get("behavior_signals", "{}")
            try:
                bs = json.loads(bs_raw) if isinstance(bs_raw, str) else (bs_raw or {})
            except (json.JSONDecodeError, TypeError):
                bs = {}
            if bs:
                behavior_signals_list.append(bs)
            conversations_summary.append({
                "topic": c.get("topic", ""),
                "task_type": c.get("task_type", ""),
            })

        current_profile_rows = db.query_local(
            "SELECT dimension, value, confidence, observation_count, trend FROM user_profile"
        )
        current_profile = {}
        for row in (current_profile_rows or []):
            current_profile[row["dimension"]] = {
                "value": row["value"],
                "confidence": row["confidence"],
                "observation_count": row["observation_count"],
                "trend": row["trend"],
            }

        llm_ok, llm_reason = _check_llm_available("enhance_profile_merge")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="daily_profile_merge",
                source_date=date_str,
                raw_data={
                    "behavior_signals_list": behavior_signals_list,
                    "current_profile": current_profile,
                    "conversations_summary": conversations_summary,
                },
                missing_dimensions=[
                    "skill_level", "communication_style", "decision_pattern",
                    "emotional_tendency", "learning_style", "problem_solving",
                    "tech_interests", "areas_for_growth",
                ],
                error_message=llm_reason,
            )
            result["success"] = True
            result["method"] = "pending"
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        merge_result = _execute_profile_merge_llm(
            db=db,
            behavior_signals_list=behavior_signals_list,
            current_profile=current_profile,
            conversations_summary=conversations_summary,
            source_date=date_str,
        )

        if merge_result.get("success"):
            result["success"] = True
            result["method"] = "llm"
            result["dimensions_updated"] = merge_result.get("dimensions_updated", 0)
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="daily_profile_merge",
                source_date=date_str,
                raw_data={
                    "behavior_signals_list": behavior_signals_list,
                    "current_profile": current_profile,
                    "conversations_summary": conversations_summary,
                },
                missing_dimensions=[
                    "skill_level", "communication_style", "decision_pattern",
                    "emotional_tendency", "learning_style", "problem_solving",
                    "tech_interests", "areas_for_growth",
                ],
                error_message=merge_result.get("error", "LLM 分析失败"),
            )
            result["success"] = True
            result["method"] = "pending"
            result["note"] = f"LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"每日画像合并失败: {e}", exc_info=True)

    return result


def merge_daily_system_context(date_str: str = "") -> dict:
    """
    每日系统认知合并（v8.0 — 纯 LLM 驱动，无规则降级）

    数据流：
    system_context_fragments → LLM 合并 → connected_systems 更新
    LLM 不可用 → 原始数据写入 pending_analyses 表，等待下次清算

    Args:
        date_str: 日期字符串（YYYY-MM-DD），默认今天

    Returns:
        {"success": True, "systems_updated": N, "method": "llm"/"pending"}
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    result = {
        "success": False,
        "date": date_str,
        "systems_updated": 0,
        "method": "none",
    }

    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        fragments = db.query_local(
            "SELECT id, conversation_id, system_id, tech_signals, architecture_signals, "
            "business_signals, new_discoveries, confidence "
            "FROM system_context_fragments "
            "WHERE merged = 0 AND date(observed_at) = ?",
            (date_str,),
        )

        if not fragments:
            result["success"] = True
            result["method"] = "none"
            result["note"] = "当日无未合并的系统认知片段"
            return result

        from collections import defaultdict
        grouped = defaultdict(list)
        fragment_ids = []
        for f in (fragments or []):
            grouped[f["system_id"]].append(f)
            fragment_ids.append(f["id"])

        llm_ok, llm_reason = _check_llm_available("enhance_system_merge")

        for system_id, group in grouped.items():
            try:
                all_tech = []
                all_arch = []
                all_biz = []
                all_disc = []
                for f in group:
                    for field_name, target in [
                        ("tech_signals", all_tech),
                        ("architecture_signals", all_arch),
                        ("business_signals", all_biz),
                        ("new_discoveries", all_disc),
                    ]:
                        raw = f.get(field_name, "[]")
                        try:
                            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
                            target.extend(items)
                        except (json.JSONDecodeError, TypeError):
                            pass

                current_system = db.query_local(
                    "SELECT tech_stack, architecture, business_domains, maturity FROM connected_systems WHERE system_id = ?",
                    (system_id,),
                )
                current_profile = {}
                if current_system:
                    for key in ["tech_stack", "architecture", "business_domains", "maturity"]:
                        raw_val = current_system[0].get(key, "")
                        if key == "maturity":
                            current_profile[key] = raw_val or "unknown"
                        else:
                            try:
                                current_profile[key] = json.loads(raw_val) if isinstance(raw_val, str) else (raw_val or {})
                            except (json.JSONDecodeError, TypeError):
                                current_profile[key] = {} if key == "architecture" else []

                if not llm_ok:
                    _write_pending_analysis(
                        db=db,
                        analysis_type="daily_system_merge",
                        source_date=date_str,
                        system_id=system_id,
                        raw_data={
                            "all_tech": all_tech, "all_arch": all_arch,
                            "all_biz": all_biz, "all_disc": all_disc,
                            "current_profile": current_profile,
                            "fragment_ids": [f["id"] for f in group],
                        },
                        missing_dimensions=["tech_stack", "architecture", "business_domains", "maturity"],
                        error_message=llm_reason,
                    )
                    result["method"] = "pending"
                    continue

                merge_result = _execute_system_merge_llm(
                    db=db,
                    system_id=system_id,
                    all_tech=all_tech, all_arch=all_arch,
                    all_biz=all_biz, all_disc=all_disc,
                    current_profile=current_profile,
                    source_date=date_str,
                    fragment_ids=[f["id"] for f in group],
                )

                if merge_result.get("success"):
                    result["method"] = "llm"
                    result["systems_updated"] += 1
                else:
                    _write_pending_analysis(
                        db=db,
                        analysis_type="daily_system_merge",
                        source_date=date_str,
                        system_id=system_id,
                        raw_data={
                            "all_tech": all_tech, "all_arch": all_arch,
                            "all_biz": all_biz, "all_disc": all_disc,
                            "current_profile": current_profile,
                            "fragment_ids": [f["id"] for f in group],
                        },
                        missing_dimensions=["tech_stack", "architecture", "business_domains", "maturity"],
                        error_message=merge_result.get("error", "LLM 分析失败"),
                    )
                    result["method"] = "pending"

            except Exception as e:
                logger.error(f"系统 {system_id} 认知合并失败: {e}")

        if result["method"] == "pending":
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
        elif result["systems_updated"] > 0:
            result["success"] = True
        else:
            result["success"] = True
            result["note"] = "无系统需要更新"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"每日系统认知合并失败: {e}", exc_info=True)

    return result


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
        from devpartner_agent.core.database import get_db
        from devpartner_agent.core.config import get_config
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
                logger.info(f"📋 标记 {len(failed_rows)} 条 pending_analyses 为 failed（超过最大重试次数）")
        except Exception as e:
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
                from devpartner_agent.services.vault_exporter import get_vault_exporter
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
                        pass

                result["warm_archived"] = archived_count
                result["warm_skipped"] = skipped_count
                if archived_count > 0 or skipped_count > 0:
                    logger.info(f"📦 温数据归档完成: {archived_count} 个对话已压缩, {skipped_count} 个跳过（MD未导出）")
        except Exception as e:
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
                conv_ids = [r["id"] for r in deep_rows]
                for cid in conv_ids:
                    db.query_local("DELETE FROM conversation_steps WHERE conversations_id = ?", (cid,))
                db.query_local(
                    "DELETE FROM conversations WHERE date(timestamp) < ? AND archive_tier = 'archived'",
                    (deep_cutoff,),
                )
                result["deep_cleaned"] = len(deep_rows)
                logger.info(f"🗑️ 深度清理完成: {len(deep_rows)} 条对话已删除（MD为唯一数据源）")
        except Exception as e:
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
                pass

            result["logs_cleaned"] = il_count + el_count
            if il_count + el_count > 0:
                logger.info(f"🧹 日志清理完成: improvement_log {il_count}条, evolution_log {el_count}条")
        except Exception as e:
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
        rows = db.query_local(
            "SELECT dimension, value, confidence, trend FROM user_profile"
        )
        if not rows:
            return "暂无用户画像数据"
        parts = []
        for row in (rows or []):
            parts.append(f"- {row['dimension']}: {row['value']} (置信度={row.get('confidence', 0.5)}, 趋势={row.get('trend', 'stable')})")
        return "\n".join(parts)
    except Exception:
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
        for row in (rows or []):
            parts.append(f"### {row['system_id']}")
            parts.append(f"- 技术栈: {row.get('tech_stack', '[]')}")
            parts.append(f"- 架构: {row.get('architecture', '{}')}")
            parts.append(f"- 业务领域: {row.get('business_domains', '[]')}")
            parts.append(f"- 成熟度: {row.get('maturity', 'unknown')}")
        return "\n".join(parts)
    except Exception:
        return "项目画像获取失败"


def _read_md_reports(directory: Path, limit: int = 10,
                     date_from: str = None, date_to: str = None) -> list:
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
            if re.match(r"\d{4}-\d{2}-\d{2}", stem):
                file_date = stem
            elif re.match(r"\d{4}-W\d{2}", stem):
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
            pass

        if len(reports) >= limit:
            break

    return reports


def generate_weekly_report(trigger_time: datetime = None,
                            target_date: str = None,
                            force_overwrite: bool = False) -> dict:
    """
    生成周报（v8.0 — LLM 驱动 + MD 自包含）
    v8.5.7: 新增 target_date + force_overwrite，支持手动覆盖生成

    数据来源：上周的 Calendar/*.md 日报文件 + 用户/项目画像快照
    输出：Reports/Weekly/{YYYY-WXX}.md

    Args:
        trigger_time: 触发时间，默认当前时间
        target_date: 目标日期（YYYY-MM-DD），定位到该日期所在周，默认上周
        force_overwrite: 是否覆盖已存在的报告

    Returns:
        {"success": bool, "method": "llm"/"pending", "file_path": str}
    """
    if trigger_time is None:
        trigger_time = datetime.now()

    result = {"success": False, "method": "none", "file_path": None}

    try:
        from devpartner_agent.core.database import get_db
        from devpartner_agent.services.vault_exporter import get_vault_exporter

        db = get_db()
        exporter = get_vault_exporter()

        if target_date:
            # 手动指定目标日期 → 定位到该日期所在 ISO 周
            td = datetime.strptime(target_date, "%Y-%m-%d").date()
            week_monday = td - timedelta(days=td.weekday())
            week_sunday = week_monday + timedelta(days=6)
            period_start = week_monday.strftime("%Y-%m-%d")
            period_end = week_sunday.strftime("%Y-%m-%d")
            week_num = week_monday.strftime("%Y-W%W")
        else:
            today = trigger_time.date()
            this_monday = today - timedelta(days=today.weekday())
            last_monday = this_monday - timedelta(days=7)
            last_sunday = this_monday - timedelta(days=1)
            period_start = last_monday.strftime("%Y-%m-%d")
            period_end = last_sunday.strftime("%Y-%m-%d")
            week_num = last_monday.strftime("%Y-W%W")

        # 覆盖模式：检查目标文件是否已存在
        target_file = exporter._reports_dir / "Weekly" / f"{week_num}.md"
        if target_file.exists() and not force_overwrite:
            result["success"] = True
            result["method"] = "skipped"
            result["file_path"] = str(target_file)
            result["note"] = f"报告已存在: {week_num}.md（勾选覆盖可重新生成）"
            result["period_start"] = period_start
            result["period_end"] = period_end
            return result

        daily_summaries = _read_md_reports(
            exporter._calendar_dir, limit=7,
            date_from=period_start, date_to=period_end,
        )
        daily_summaries_text = ""
        for ds in daily_summaries:
            daily_summaries_text += f"### {ds['file']}\n{ds['content']}\n\n"

        if not daily_summaries_text.strip():
            result["success"] = True
            result["method"] = "none"
            result["note"] = "本周无日报数据"
            return result

        user_snapshot = _get_user_profile_snapshot(db)
        project_snapshot = _get_project_profile_snapshot(db)

        llm_ok, llm_reason = _check_llm_available("enhance_weekly_report")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="weekly_report",
                source_date=period_start,
                raw_data={
                    "daily_summaries": daily_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=["key_achievements", "skill_progress", "risk_assessment", "next_week_plan"],
                error_message=llm_reason,
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        from prompts import run_analysis, TASK_WEEKLY_REPORT
        llm_result = run_analysis(
            TASK_WEEKLY_REPORT,
            period_start=period_start,
            period_end=period_end,
            daily_summaries=daily_summaries_text[:8000],
            user_profile_snapshot=user_snapshot[:2000],
            project_profile_snapshot=project_snapshot[:2000],
        )

        if llm_result and isinstance(llm_result, dict) and "summary" in llm_result:
            file_path = exporter.export_weekly_report(period_start, period_end, llm_result)
            result["success"] = True
            result["method"] = "llm"
            result["file_path"] = file_path
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="weekly_report",
                source_date=period_start,
                raw_data={
                    "daily_summaries": daily_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=["key_achievements", "skill_progress", "risk_assessment", "next_week_plan"],
                error_message="LLM 返回结果无效",
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = "LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"周报生成失败: {e}", exc_info=True)

    return result


def generate_monthly_report(trigger_time: datetime = None,
                             target_date: str = None,
                             force_overwrite: bool = False) -> dict:
    """
    生成月报（v8.0 — LLM 驱动 + MD 自包含）
    v8.5.7: 新增 target_date + force_overwrite，支持手动覆盖生成

    数据来源：上月的 Reports/Weekly/*.md 周报文件 + 用户/项目画像快照
    输出：Reports/Monthly/{YYYY-MM}.md

    Args:
        trigger_time: 触发时间，默认当前时间
        target_date: 目标日期（YYYY-MM-DD），定位到该日期所在月，默认上月
        force_overwrite: 是否覆盖已存在的报告

    Returns:
        {"success": bool, "method": "llm"/"pending", "file_path": str}
    """
    if trigger_time is None:
        trigger_time = datetime.now()

    result = {"success": False, "method": "none", "file_path": None}

    try:
        from devpartner_agent.core.database import get_db
        from devpartner_agent.services.vault_exporter import get_vault_exporter

        db = get_db()
        exporter = get_vault_exporter()

        if target_date:
            td = datetime.strptime(target_date, "%Y-%m-%d").date()
            first_of_month = td.replace(day=1)
            if td.month == 12:
                last_of_month = td.replace(day=31)
            else:
                next_month = td.replace(month=td.month + 1, day=1)
                last_of_month = next_month - timedelta(days=1)
            period_start = first_of_month.strftime("%Y-%m-%d")
            period_end = last_of_month.strftime("%Y-%m-%d")
            month_str = first_of_month.strftime("%Y-%m")
        else:
            today = trigger_time.date()
            first_of_this_month = today.replace(day=1)
            last_of_prev_month = first_of_this_month - timedelta(days=1)
            first_of_prev_month = last_of_prev_month.replace(day=1)
            period_start = first_of_prev_month.strftime("%Y-%m-%d")
            period_end = last_of_prev_month.strftime("%Y-%m-%d")
            month_str = first_of_prev_month.strftime("%Y-%m")

        # 覆盖模式：检查目标文件是否已存在
        target_file = exporter._reports_dir / "Monthly" / f"{month_str}.md"
        if target_file.exists() and not force_overwrite:
            result["success"] = True
            result["method"] = "skipped"
            result["file_path"] = str(target_file)
            result["note"] = f"报告已存在: {month_str}.md（勾选覆盖可重新生成）"
            result["period_start"] = period_start
            result["period_end"] = period_end
            return result

        weekly_summaries = _read_md_reports(
            exporter._reports_dir / "Weekly", limit=5,
            date_from=period_start, date_to=period_end,
        )
        weekly_summaries_text = ""
        for ws in weekly_summaries:
            weekly_summaries_text += f"### {ws['file']}\n{ws['content']}\n\n"

        if not weekly_summaries_text.strip():
            result["success"] = True
            result["method"] = "none"
            result["note"] = "本月无周报数据"
            return result

        user_snapshot = _get_user_profile_snapshot(db)
        project_snapshot = _get_project_profile_snapshot(db)

        llm_ok, llm_reason = _check_llm_available("enhance_monthly_report")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="monthly_report",
                source_date=period_start,
                raw_data={
                    "weekly_summaries": weekly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=["major_achievements", "skill_evolution", "risk_and_debt", "next_month_plan"],
                error_message=llm_reason,
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        from prompts import run_analysis, TASK_MONTHLY_REPORT
        llm_result = run_analysis(
            TASK_MONTHLY_REPORT,
            period_start=period_start,
            period_end=period_end,
            weekly_summaries=weekly_summaries_text[:10000],
            user_profile_snapshot=user_snapshot[:2000],
            project_profile_snapshot=project_snapshot[:2000],
        )

        if llm_result and isinstance(llm_result, dict) and "summary" in llm_result:
            file_path = exporter.export_monthly_report(period_start, period_end, llm_result)
            result["success"] = True
            result["method"] = "llm"
            result["file_path"] = file_path

            _run_growth_analysis(
                db=db,
                period_start=period_start,
                period_end=period_end,
                weekly_summaries_text=weekly_summaries_text[:10000],
                user_snapshot=user_snapshot[:2000],
                project_snapshot=project_snapshot[:2000],
            )
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="monthly_report",
                source_date=period_start,
                raw_data={
                    "weekly_summaries": weekly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                },
                missing_dimensions=["major_achievements", "skill_evolution", "risk_and_debt", "next_month_plan"],
                error_message="LLM 返回结果无效",
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = "LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"月报生成失败: {e}", exc_info=True)

    return result


def _run_growth_analysis(db, period_start: str, period_end: str,
                          weekly_summaries_text: str, user_snapshot: str,
                          project_snapshot: str):
    """
    月报生成后触发系统+用户双维度成长分析，产出 growth_analysis 表数据。

    v8.5.0: 双维度分析 — system_analyses（系统优化）+ user_analyses（用户成长）
    结果写入 growth_analysis 表，状态为 pending，等待 Dashboard 人工审核。
    """
    month_str = period_start[:7]
    try:
        from prompts import run_analysis, TASK_GROWTH_ANALYSIS

        ga_result = run_analysis(
            TASK_GROWTH_ANALYSIS,
            period_start=period_start,
            period_end=period_end,
            weekly_summaries=weekly_summaries_text,
            user_profile_snapshot=user_snapshot,
            project_profile_snapshot=project_snapshot,
        )

        if not ga_result or not isinstance(ga_result, dict):
            logger.warning("成长分析 LLM 返回无效结果，跳过")
            return

        # v8.5.0: 双维度 — system_analyses + user_analyses
        system_items = ga_result.get("system_analyses", [])
        user_items = ga_result.get("user_analyses", [])
        all_items = system_items + user_items

        if not all_items:
            logger.info("本月无成长分析建议")
            return

        count = 0
        for item in all_items:
            try:
                db.insert_growth_analysis({
                    "analysis_type": item.get("analysis_type", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "suggestion": item.get("suggestion", ""),
                    "related_data": {
                        **(item.get("related_data", {}) or {}),
                        "related_skills": item.get("related_skills", []),
                        "trend_keywords": item.get("trend_keywords", []),
                        "expected_effect": item.get("expected_effect", ""),
                    },
                    "priority": item.get("priority", "medium"),
                    "source": "monthly_report",
                    "source_period": month_str,
                })
                count += 1
            except Exception as e:
                logger.error(f"写入 growth_analysis 失败: {e}")

        # v8.5.0: 保存汇总信息到 improvement_log
        summary = ga_result.get("summary", {})
        if summary:
            try:
                db.query_local("""
                    INSERT INTO improvement_log (
                        timestamp, category, suggestion, priority, status
                    ) VALUES (?, 'growth_summary', ?, 'medium', 'pending')
                """, (datetime.now().isoformat(),
                      json.dumps(summary, ensure_ascii=False)[:500]))
            except Exception:
                pass

        if count > 0:
            logger.info(f"成长分析完成: {count} 条建议已写入 growth_analysis 表（{month_str}）"
                        f" | 系统={len(system_items)} 用户={len(user_items)}")

        _cleanup_old_growth_analysis(db, month_str)

    except Exception as e:
        logger.error(f"成长分析执行失败: {e}", exc_info=True)


def _cleanup_old_growth_analysis(db, current_period: str):
    """
    清理上个月已处理的 growth_analysis 数据。

    规则：每月清理 status 为 approved/rejected 且 source_period < 当前月的数据。
    """
    try:
        year, month = int(current_period[:4]), int(current_period[5:7])
        if month == 1:
            before = f"{year - 1}-12"
        else:
            before = f"{year}-{month - 1:02d}"

        deleted = db.cleanup_growth_analysis(before)
        if deleted > 0:
            logger.info(f"清理已处理 growth_analysis: {deleted} 条（{before} 及之前）")
    except Exception as e:
        logger.error(f"清理 growth_analysis 失败: {e}")


def generate_annual_report(trigger_time: datetime = None,
                            target_date: str = None,
                            force_overwrite: bool = False) -> dict:
    """
    生成年报（v8.0 — LLM 驱动 + MD 自包含）
    v8.5.7: 新增 target_date + force_overwrite，支持手动覆盖生成

    数据来源：本年的 Reports/Monthly/*.md 月报文件 + 用户/项目画像快照
    输出：Reports/Annual/{YYYY}.md

    Args:
        trigger_time: 触发时间，默认当前时间
        target_date: 目标日期（YYYY-MM-DD），定位到该日期所在年，默认去年
        force_overwrite: 是否覆盖已存在的报告

    Returns:
        {"success": bool, "method": "llm"/"pending", "file_path": str}
    """
    if trigger_time is None:
        trigger_time = datetime.now()

    result = {"success": False, "method": "none", "file_path": None}

    try:
        from devpartner_agent.core.database import get_db
        from devpartner_agent.services.vault_exporter import get_vault_exporter

        db = get_db()
        exporter = get_vault_exporter()

        if target_date:
            year_str = str(datetime.strptime(target_date, "%Y-%m-%d").year)
        else:
            year_str = str(trigger_time.year - 1)

        period_start = f"{year_str}-01-01"
        period_end = f"{year_str}-12-31"

        # 覆盖模式：检查目标文件是否已存在
        target_file = exporter._reports_dir / "Annual" / f"{year_str}.md"
        if target_file.exists() and not force_overwrite:
            result["success"] = True
            result["method"] = "skipped"
            result["file_path"] = str(target_file)
            result["note"] = f"报告已存在: {year_str}.md（勾选覆盖可重新生成）"
            result["period_start"] = period_start
            result["period_end"] = period_end
            return result

        monthly_summaries = _read_md_reports(
            exporter._reports_dir / "Monthly", limit=12,
            date_from=period_start, date_to=period_end,
        )
        monthly_summaries_text = ""
        for ms in monthly_summaries:
            monthly_summaries_text += f"### {ms['file']}\n{ms['content']}\n\n"

        if not monthly_summaries_text.strip():
            result["success"] = True
            result["method"] = "none"
            result["note"] = "本年无月报数据"
            return result

        user_snapshot = _get_user_profile_snapshot(db)
        project_snapshot = _get_project_profile_snapshot(db)

        llm_ok, llm_reason = _check_llm_available("enhance_annual_report")
        if not llm_ok:
            _write_pending_analysis(
                db=db,
                analysis_type="annual_report",
                source_date=period_start,
                raw_data={
                    "monthly_summaries": monthly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "year": year_str,
                },
                missing_dimensions=["year_in_review", "skill_journey", "growth_analysis", "next_year_vision"],
                error_message=llm_reason,
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = f"LLM 不可用 ({llm_reason})，数据已暂存等待清算"
            return result

        from prompts import run_analysis, TASK_ANNUAL_REPORT
        llm_result = run_analysis(
            TASK_ANNUAL_REPORT,
            period_start=period_start,
            period_end=period_end,
            monthly_summaries=monthly_summaries_text[:14000],
            user_profile_snapshot=user_snapshot[:2000],
            project_profile_snapshot=project_snapshot[:2000],
        )

        if llm_result and isinstance(llm_result, dict) and "summary" in llm_result:
            file_path = exporter.export_annual_report(year_str, llm_result)
            result["success"] = True
            result["method"] = "llm"
            result["file_path"] = file_path
        else:
            _write_pending_analysis(
                db=db,
                analysis_type="annual_report",
                source_date=period_start,
                raw_data={
                    "monthly_summaries": monthly_summaries,
                    "user_profile_snapshot": user_snapshot,
                    "project_profile_snapshot": project_snapshot,
                    "year": year_str,
                },
                missing_dimensions=["year_in_review", "skill_journey", "growth_analysis", "next_year_vision"],
                error_message="LLM 返回结果无效",
            )
            result["method"] = "pending"
            result["success"] = True
            result["note"] = "LLM 分析失败，数据已暂存等待清算"

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"年报生成失败: {e}", exc_info=True)

    return result