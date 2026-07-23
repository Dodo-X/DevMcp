"""
DevPartner Growth Analytics Tools
双向成长分析工具集 - 提供 Dashboard 所需的聚合数据

包含 5 个核心工具：
  1. get_user_growth_overview     - 用户成长总览（知识点数、领域覆盖、学习效率等）
  2. get_system_evolution_stats   - 系统进化统计（自迭代次数、引擎分布、采纳率）
  3. get_user_skill_radar         - 用户知识领域雷达图数据
  4. get_learning_timeline        - 融合时间线（知识点+系统事件交织）
  5. get_user_activity_heatmap    - 用户学习热力图（近4周活动强度）

设计原则：
  - 聚合计算：从多个表提取并计算衍生指标
  - 性能优化：使用 SQL 聚合函数减少数据传输
  - 缓存友好：返回结构化 JSON，适合前端缓存
  - v9.7.1: 数据源从 user_skills 切换到 knowledge_points（客观知识点提取，非 LLM 总结的用户画像）
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_user_growth_overview() -> str:
    """
    获取用户成长总览数据

    返回字段：
      - total_skills: 总知识点数
      - avg_mastery: 平均置信度 (0-100)
      - this_week_new: 本周新增知识点数
      - streak_days: 连续学习天数
      - learning_efficiency: 学习效率 (0-1)
      - top_domain: 当前最专注领域
      - skills_by_domain: 各领域知识点分布

    v9.7.1: 数据源从 user_skills 切换到 knowledge_points。
    knowledge_points 是 step_analysis 的客观提取结果，比 LLM 总结的 user_skills 更实时。
    数据来源：
      - knowledge_points 表：知识点列表和置信度
      - conversations 表：学习活动记录
    """
    try:
        from backend.core.database.base_conn import get_db

        db = get_db()

        # 1. 总知识点数和平均置信度
        # confidence 范围 0-1，映射到 0-100
        skills_result = db.query_local("""
            SELECT 
                COUNT(*) as total_skills,
                AVG(COALESCE(confidence, 0.5)) * 100 as avg_mastery,
                MAX(created_at) as last_updated
            FROM knowledge_points
            WHERE type = 'skill'
        """)

        total_skills = skills_result[0]["total_skills"] if skills_result else 0
        avg_mastery = (
            round(skills_result[0]["avg_mastery"], 1)
            if skills_result and skills_result[0]["avg_mastery"]
            else 0
        )

        # 2. 本周新增知识点（7天内，基于 created_at 列）
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        new_skills_result = db.query_local(
            """
            SELECT COUNT(*) as new_count
            FROM knowledge_points
            WHERE type = 'skill' AND created_at >= ?
        """,
            (week_ago,),
        )
        this_week_new = new_skills_result[0]["new_count"] if new_skills_result else 0

        # 3. 连续学习天数（基于conversations表）
        streak_days = _calculate_learning_streak(db)

        # 4. 学习效率（最近30天 vs 前30天的知识点增长率）
        learning_efficiency = _calculate_learning_efficiency(db)

        # 5. 当前最专注领域（知识点数量最多的 domain）
        top_domain_result = db.query_local("""
            SELECT domain, COUNT(*) as cnt
            FROM knowledge_points
            WHERE type = 'skill'
            GROUP BY domain
            ORDER BY cnt DESC
            LIMIT 1
        """)
        top_domain = top_domain_result[0]["domain"] if top_domain_result else "未分类"

        # 6. 各领域知识点分布（按 domain 聚合，展示平均置信度和难度分布）
        domain_dist_result = db.query_local("""
            SELECT 
                domain,
                COUNT(*) as count,
                AVG(COALESCE(confidence, 0.5)) * 100 as avg_mastery,
                SUM(CASE WHEN difficulty = 'easy' THEN 1 ELSE 0 END) as easy_count,
                SUM(CASE WHEN difficulty = 'medium' THEN 1 ELSE 0 END) as medium_count,
                SUM(CASE WHEN difficulty = 'hard' THEN 1 ELSE 0 END) as hard_count
            FROM knowledge_points
            WHERE type = 'skill'
            GROUP BY domain
            ORDER BY count DESC
        """)
        skills_by_domain = (
            [
                {
                    "domain": row["domain"] or "其他",
                    "count": row["count"],
                    "avg_mastery": round(row["avg_mastery"], 1) if row["avg_mastery"] else 0,
                    "difficulty_breakdown": {
                        "easy": row["easy_count"] or 0,
                        "medium": row["medium_count"] or 0,
                        "hard": row["hard_count"] or 0,
                    },
                }
                for row in domain_dist_result
            ]
            if domain_dist_result
            else []
        )

        result = {
            "total_skills": total_skills,
            "avg_mastery": avg_mastery,
            "this_week_new": this_week_new,
            "streak_days": streak_days,
            "learning_efficiency": learning_efficiency,
            "top_domain": top_domain,
            "skills_by_domain": skills_by_domain,
            "last_updated": datetime.now().isoformat(),
            "status": "success",
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning(
            "get_user_growth_overview: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return json.dumps(
            {
                "status": "error",
                "message": f"获取用户成长数据失败: {str(e)}",
                "total_skills": 0,
                "avg_mastery": 0,
                "this_week_new": 0,
                "streak_days": 0,
                "learning_efficiency": 0,
                "top_domain": "错误",
                "skills_by_domain": [],
            },
            ensure_ascii=False,
            indent=2,
        )


def get_system_evolution_stats() -> str:
    """
    获取系统进化统计数据

    返回字段：
      - total_iterations: 自我迭代总次数
      - recent_changes: 最近变更记录（最新5条）
      - llm_call_ratio: LLM调用占比 (0-100)
      - rules_engine_ratio: 规则引擎占比 (0-100)
      - knowledge_growth_rate: 知识库月增长率 (%)
      - suggestion_adoption_rate: 优化建议采纳率 (%)
      - last_iteration_time: 最后一次迭代时间

    数据来源：
      - evolution_log 表：系统变更记录
      - improvement_log 表：改进日志
      - conversations 表：LLM调用记录
    """
    try:
        from backend.core.database.base_conn import get_db

        db = get_db()

        # 1. 自我迭代总次数（evolution_log 记录数）
        iterations_result = db.query_local("""
            SELECT COUNT(*) as total,
                   MAX(timestamp) as last_time
            FROM evolution_log
            WHERE success = 1
        """)
        total_iterations = iterations_result[0]["total"] if iterations_result else 0
        last_iteration_time = (
            iterations_result[0]["last_time"]
            if iterations_result and iterations_result[0]["last_time"]
            else None
        )

        # 2. 最近变更记录（最新5条）
        recent_changes_result = db.query_local("""
            SELECT 
                id,
                version,
                change_type,
                description,
                timestamp,
                success
            FROM evolution_log
            ORDER BY timestamp DESC
            LIMIT 5
        """)
        recent_changes = (
            [
                {
                    "id": row["id"],
                    "version": row["version"],
                    "change_type": row["change_type"],
                    "description": row["description"],
                    "timestamp": row["timestamp"],
                    "success": bool(row["success"]),
                }
                for row in recent_changes_result
            ]
            if recent_changes_result
            else []
        )

        # 3. LLM 分析引擎统计（近30天 step_analysis + conversation_finalize 任务统计）
        llm_stats_result = db.query_local("""
            SELECT 
                SUM(CASE WHEN task_type = 'step_analysis' THEN 1 ELSE 0 END) as step_analyses,
                SUM(CASE WHEN task_type = 'conversation_finalize' THEN 1 ELSE 0 END) as conv_analyses,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                COUNT(*) as total_analyses
            FROM task_queue
            WHERE queued_at >= datetime('now', '-30 days')
              AND task_type IN ('step_analysis', 'conversation_finalize')
        """)
        step_analyses = llm_stats_result[0]["step_analyses"] if llm_stats_result else 0
        conv_analyses = llm_stats_result[0]["conv_analyses"] if llm_stats_result else 0
        completed_analyses = llm_stats_result[0]["completed"] if llm_stats_result else 0
        total_analyses = llm_stats_result[0]["total_analyses"] if llm_stats_result else 0

        # 分析成功率
        analysis_success_rate = (
            round((completed_analyses / total_analyses) * 100, 1) if total_analyses > 0 else 0.0
        )

        # v6.0 已全面转 LLM 分析，不再有规则引擎
        llm_call_ratio = 100.0 if total_analyses > 0 else 0.0
        rules_engine_ratio = 0.0

        # 4. 知识库月增长率（knowledge_points 的月度增长，基于 created_at）
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        current_skills = db.query_local(
            "SELECT COUNT(*) as cnt FROM knowledge_points WHERE type='skill'"
        )[0]["cnt"]
        past_skills_result = db.query_local(
            """
            SELECT COUNT(*) as cnt 
            FROM knowledge_points 
            WHERE type='skill' AND created_at < ?
        """,
            (month_ago,),
        )
        past_skills = past_skills_result[0]["cnt"] if past_skills_result else 0

        if past_skills > 0:
            knowledge_growth_rate = round(((current_skills - past_skills) / past_skills) * 100, 1)
        elif current_skills > 0:
            knowledge_growth_rate = 0.0
        else:
            knowledge_growth_rate = 0.0

        # 5. 优化建议采纳率（growth_analysis 表中 approved + applied_at 非空 的比例）
        #    注意：growth_analysis 取代了 optimization_feedback，是 v8.1.0+ 的官方优化建议表
        ninety_days_ago = (datetime.now() - timedelta(days=90)).isoformat()
        adoption_result = db.query_local(
            """
            SELECT 
                SUM(CASE WHEN status = 'approved' AND applied_at IS NOT NULL THEN 1 ELSE 0 END) as adopted,
                SUM(CASE WHEN status IN ('approved', 'rejected') THEN 1 ELSE 0 END) as reviewed,
                COUNT(*) as total
            FROM growth_analysis
            WHERE timestamp >= ?
        """,
            (ninety_days_ago,),
        )
        total_suggestions = adoption_result[0]["total"] if adoption_result else 0
        reviewed = adoption_result[0]["reviewed"] if adoption_result else 0
        adopted = adoption_result[0]["adopted"] if adoption_result else 0

        # 采纳率 = 已应用 / 已审核（而非 / 总数，避免 pending 拉低比例）
        suggestion_adoption_rate = round((adopted / reviewed) * 100, 1) if reviewed > 0 else 0.0

        # 6. 当前版本号（从最近一次 evolution_log 推导，空则回退到服务端 VERSION）
        current_version = recent_changes[0]["version"] if recent_changes else "6.0.0"

        # 7. 首次迭代时间（用于计算周迭代率）
        first_iteration = db.query_local("""
            SELECT MIN(timestamp) as first_time
            FROM evolution_log
            WHERE success = 1
        """)
        first_time = (
            first_iteration[0]["first_time"]
            if first_iteration and first_iteration[0]["first_time"]
            else None
        )
        days_since_first = 0
        if first_time and total_iterations > 1:
            try:
                first_dt = datetime.fromisoformat(first_time.replace("Z", "+00:00"))
                days_since_first = max(1, (datetime.now() - first_dt.replace(tzinfo=None)).days)
            except (ValueError, TypeError) as _e:
                logger.warning(f"首次迭代时间解析失败，回退默认天数: {_e}")
                days_since_first = 30

        # 8. 最近变更摘要（用于 latest_change）
        latest_change = None
        if recent_changes:
            latest = recent_changes[0]
            latest_change = {
                "title": latest["description"][:60] if latest.get("description") else "未知变更",
                "version": latest.get("version", ""),
                "change_type": latest.get("change_type", ""),
                "time_ago": latest.get("timestamp", ""),
                "timestamp": latest.get("timestamp", ""),
            }

        result = {
            "total_iterations": total_iterations,
            "recent_changes": recent_changes,
            # v6.0: 全部转为 LLM 分析引擎
            "llm_call_ratio": llm_call_ratio,
            "rules_engine_ratio": rules_engine_ratio,
            # 新增：LLM 分析引擎统计详情
            "llm_analysis_stats": {
                "total_analyses": total_analyses,
                "step_analyses": step_analyses,
                "conv_analyses": conv_analyses,
                "completed_analyses": completed_analyses,
                "success_rate": analysis_success_rate,
            },
            "knowledge_growth_rate": knowledge_growth_rate,
            "suggestion_adoption_rate": suggestion_adoption_rate,
            # v6.0.1: 前端兼容别名
            "knowledge_base_growth_rate": knowledge_growth_rate,
            "optimization_adoption_rate": suggestion_adoption_rate,
            "current_version": current_version,
            "latest_change": latest_change,
            "days_since_first_iteration": days_since_first,
            "iteration_rate_per_week": round(total_iterations / max(1, days_since_first / 7), 1)
            if days_since_first > 0
            else 0.0,
            # 原始字段
            "last_iteration_time": last_iteration_time,
            "pending_suggestions": max(0, total_suggestions - reviewed),
            "last_updated": datetime.now().isoformat(),
            "status": "success",
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning(
            "get_system_evolution_stats: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return json.dumps(
            {
                "status": "error",
                "message": f"获取系统进化数据失败: {str(e)}",
                "total_iterations": 0,
                "recent_changes": [],
                "llm_call_ratio": 100.0,
                "rules_engine_ratio": 0.0,
                "llm_analysis_stats": {
                    "total_analyses": 0,
                    "step_analyses": 0,
                    "conv_analyses": 0,
                    "completed_analyses": 0,
                    "success_rate": 0.0,
                },
                "knowledge_growth_rate": 0.0,
                "suggestion_adoption_rate": 0.0,
                "knowledge_base_growth_rate": 0.0,
                "optimization_adoption_rate": 0.0,
                "current_version": "6.0.0",
                "latest_change": None,
                "days_since_first_iteration": 30,
                "iteration_rate_per_week": 0.0,
                "pending_suggestions": 0,
            },
            ensure_ascii=False,
            indent=2,
        )


def get_user_skill_radar() -> str:
    """
    获取用户知识领域雷达图数据

    v9.7.1: 数据源从 user_skills 切换到 knowledge_points。
    不再硬编码固定领域，而是动态从 knowledge_points 表中取 top N 个 domain。

    每个维度评分范围 0-100（confidence * 100）
    返回当前掌握度和30天前对比。

    数据来源：
      - knowledge_points 表：按 domain 分组计算平均 confidence
    """
    try:
        from backend.core.database.base_conn import get_db

        db = get_db()

        now = datetime.now()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        # 动态获取 Top 7 个领域（按知识点数量排序）
        top_domains = db.query_local("""
            SELECT domain, COUNT(*) as cnt
            FROM knowledge_points
            WHERE type = 'skill'
            GROUP BY domain
            ORDER BY cnt DESC
            LIMIT 7
        """)

        if not top_domains:
            return json.dumps(
                {
                    "status": "success",
                    "dimensions": [],
                    "current_scores": [],
                    "historical_scores": [],
                    "overall_avg_current": 0,
                    "overall_avg_past": 0,
                    "improvement_vector": [],
                    "last_updated": datetime.now().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )

        radar_data = {"current": [], "thirty_days_ago": [], "labels": []}

        for row in top_domains:
            domain = row["domain"]
            label = domain  # 直接用 domain 作为标签

            # 当前平均置信度（confidence * 100）
            current_result = db.query_local(
                """
                SELECT AVG(COALESCE(confidence, 0.5)) * 100 as avg_mastery
                FROM knowledge_points
                WHERE type = 'skill' AND domain = ?
            """,
                (domain,),
            )
            current_score = (
                round(current_result[0]["avg_mastery"], 1)
                if current_result and current_result[0]["avg_mastery"]
                else 0
            )

            # 30天前的平均置信度（基于 created_at）
            historical_result = db.query_local(
                """
                SELECT AVG(COALESCE(confidence, 0.5)) * 100 as avg_mastery
                FROM knowledge_points
                WHERE type = 'skill' AND domain = ? AND created_at < ?
            """,
                (domain, thirty_days_ago),
            )
            historical_score = (
                round(historical_result[0]["avg_mastery"], 1)
                if historical_result and historical_result[0]["avg_mastery"]
                else 0
            )

            radar_data["current"].append(current_score)
            radar_data["thirty_days_ago"].append(historical_score)
            radar_data["labels"].append(label)

        n = len(radar_data["labels"])
        result = {
            "dimensions": radar_data["labels"],
            "current_scores": radar_data["current"],
            "historical_scores": radar_data["thirty_days_ago"],
            "thirty_days_ago_scores": radar_data["thirty_days_ago"],
            "overall_avg_current": round(sum(radar_data["current"]) / n, 1) if n > 0 else 0,
            "overall_avg_past": round(sum(radar_data["thirty_days_ago"]) / n, 1) if n > 0 else 0,
            "improvement_vector": [
                round(c - p, 1)
                for c, p in zip(radar_data["current"], radar_data["thirty_days_ago"])
            ]
            if n > 0
            else [],
            "last_updated": datetime.now().isoformat(),
            "status": "success",
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning("get_user_skill_radar: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return json.dumps(
            {
                "status": "error",
                "message": f"获取技能雷达数据失败: {str(e)}",
                "dimensions": [],
                "current_scores": [],
                "historical_scores": [],
                "thirty_days_ago_scores": [],
                "overall_avg_current": 0,
                "overall_avg_past": 0,
                "improvement_vector": [],
            },
            ensure_ascii=False,
            indent=2,
        )


def get_learning_timeline(limit: int = 20) -> str:
    """
    获取融合时间线数据（知识点事件 + 系统事件交织）

    参数：
      limit: 返回的事件数量限制（默认20条）

    事件类型：
      - user: 用户事件（新知识点提取）
      - system: 系统事件（自我迭代、规则更新、知识库优化）

    每条事件包含：
      - time: 时间戳
      - type: 事件类型 ('user' | 'system')
      - icon: 图标emoji
      - content: 事件描述
      - skill/impact: 相关技能或影响（可选）
      - delta: 变化量（可选）

    v9.7.1: 用户事件数据源从 user_skills 切换到 knowledge_points。
    数据来源：
      - knowledge_points: 知识点创建（用户事件）
      - conversations: 对话活动
      - evolution_log: 系统进化
    """
    try:
        from backend.core.database.base_conn import get_db

        db = get_db()
        events = []

        # 1. 用户事件：最近的知识点创建
        new_kps = db.query_local(
            """
            SELECT 
                domain,
                title,
                difficulty,
                confidence,
                created_at as time,
                'user' as type,
                '🧠' as icon
            FROM knowledge_points
            WHERE type = 'skill'
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (limit // 2,),
        )

        for kp in new_kps:
            events.append(
                {
                    "time": kp["time"],
                    "type": "user",
                    "icon": "🧠",
                    "content": f"{kp['title']}",
                    "skill": kp["domain"],
                    "delta": f"{kp['difficulty'] or 'medium'} | 置信度 {(kp['confidence'] or 0.5) * 100:.0f}%",
                }
            )

        # 2. 系统事件：最近的进化记录
        evolutions = db.query_local(
            """
            SELECT 
                description,
                change_type,
                version,
                timestamp as time,
                'system' as type,
                '🤖' as icon
            FROM evolution_log
            WHERE success = 1
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (limit // 2,),
        )

        for evo in evolutions:
            impact_text = ""
            if evo["change_type"] == "optimization":
                impact_text = "性能优化"
            elif evo["change_type"] == "feature":
                impact_text = "功能增强"
            elif evo["change_type"] == "bugfix":
                impact_text = "Bug修复"
            elif evo["change_type"] == "refactor":
                impact_text = "代码重构"

            events.append(
                {
                    "time": evo["time"],
                    "type": "system",
                    "icon": "🤖",
                    "content": f"{evo['description'][:50]}{'...' if len(evo['description']) > 50 else ''}",
                    "impact": f"{impact_text} (v{evo['version']})"
                    if impact_text
                    else f"v{evo['version']}",
                }
            )

        # 3. 按时间排序（最新的在前）
        events.sort(key=lambda x: x["time"], reverse=True)

        # 4. 截取指定数量
        events = events[:limit]

        result = {
            "events": events,
            "total_events": len(events),
            "user_event_count": sum(1 for e in events if e["type"] == "user"),
            "system_event_count": sum(1 for e in events if e["type"] == "system"),
            "time_range": {
                "latest": events[0]["time"] if events else None,
                "oldest": events[-1]["time"] if events else None,
            },
            "last_updated": datetime.now().isoformat(),
            "status": "success",
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning("get_learning_timeline: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return json.dumps(
            {
                "status": "error",
                "message": f"获取时间线数据失败: {str(e)}",
                "events": [],
                "total_events": 0,
            },
            ensure_ascii=False,
            indent=2,
        )


def get_user_activity_heatmap() -> str:
    """
    获取用户学习热力图数据（近4周每天的活动强度）

    返回格式：
      - dates: 日期数组 (YYYY-MM-DD 格式)
      - values: 活动强度数组 (0-10)
      - labels: 周几标签 ['日', '一', '二', ..., '六']

    活动强度计算依据：
      - 当天新增知识点数 (权重: 3)
      - 当天对话轮数 (权重: 2)
      - 当天知识点更新次数 (权重: 1)

    归一化到 0-10 范围

    v9.7.1: 数据源从 user_skills 切换到 knowledge_points。
    数据来源：
      - knowledge_points: 知识点创建时间
      - conversations: 对话时间戳
    """
    try:
        from backend.core.database.base_conn import get_db

        db = get_db()

        # 计算28天（4周）的数据
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=28)

        heatmap_data = []
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.isoformat()
            next_day = (current_date + timedelta(days=1)).isoformat()

            # 当天新增知识点数
            new_kps = db.query_local(
                """
                SELECT COUNT(*) as cnt
                FROM knowledge_points
                WHERE type = 'skill' AND created_at >= ? AND created_at < ?
            """,
                (date_str, next_day),
            )
            skill_count = new_kps[0]["cnt"] if new_kps else 0

            # 当天对话数
            convs = db.query_local(
                """
                SELECT COUNT(*) as cnt
                FROM conversations
                WHERE created_at >= ? AND created_at < ?
            """,
                (date_str, next_day),
            )
            conv_count = convs[0]["cnt"] if convs else 0

            # 当天知识点更新数（排除新建，按 created_at 判断，update 用 conversations 数代替）
            # knowledge_points 没有 last_seen 字段，用 conversations 数作为更新代理
            update_count = 0

            # 计算原始强度分数
            raw_intensity = (skill_count * 3) + (conv_count * 2) + (update_count * 1)

            # 归一化到 0-10
            intensity = min(10, raw_intensity * 2 / 3)

            heatmap_data.append(
                {
                    "date": date_str,
                    "day_of_week": current_date.weekday(),  # 0=周一, 6=周日
                    "value": round(intensity, 1),
                    "breakdown": {
                        "new_skills": skill_count,
                        "conversations": conv_count,
                        "skill_updates": update_count,
                    },
                }
            )

            current_date += timedelta(days=1)

        # 提取用于图表的数据
        dates = [d["date"] for d in heatmap_data]
        values = [d["value"] for d in heatmap_data]

        result = {
            "dates": dates,
            "values": values,
            "daily_data": [{"date": d["date"], "intensity": d["value"]} for d in heatmap_data],
            "labels": ["一", "二", "三", "四", "五", "六", "日"],
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": 28},
            "active_days": sum(1 for v in values if v > 0),
            "peak_intensity": max(values) if values else 0,
            "avg_intensity": round(sum(values) / len(values), 1) if values else 0,
            "statistics": {
                "max_intensity": max(values) if values else 0,
                "min_intensity": min(values) if values else 0,
                "avg_intensity": round(sum(values) / len(values), 1) if values else 0,
                "active_days": sum(1 for v in values if v > 0),
                "peak_days": sorted(heatmap_data, key=lambda x: x["value"], reverse=True)[:3],
            },
            "detailed_data": heatmap_data,
            "last_updated": datetime.now().isoformat(),
            "status": "success",
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning(
            "get_user_activity_heatmap: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return json.dumps(
            {
                "status": "error",
                "message": f"获取热力图数据失败: {str(e)}",
                "dates": [],
                "values": [],
                "labels": ["一", "二", "三", "四", "五", "六", "日"],
            },
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# 辅助函数
# ============================================================


def _calculate_learning_streak(db) -> int:
    """计算连续学习天数"""
    try:
        result = db.query_local("""
            SELECT DISTINCT DATE(created_at) as activity_date
            FROM conversations
            WHERE created_at >= datetime('now', '-90 days')
            ORDER BY activity_date DESC
        """)

        if not result:
            return 0

        dates = [row["activity_date"] for row in result]
        streak = 0
        today = datetime.now().date()

        for i, date_str in enumerate(dates):
            activity_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            expected_date = today - timedelta(days=i)

            if activity_date == expected_date:
                streak += 1
            else:
                break

        return streak

    except Exception:
        logger.warning(
            "_calculate_learning_streak: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return 0


def _calculate_learning_efficiency(db) -> float:
    """计算学习效率（近30天 vs 前30天的知识点增长率）
    v9.7.1: 数据源从 user_skills 切换到 knowledge_points"""
    try:
        now = datetime.now()
        recent_start = (now - timedelta(days=30)).isoformat()
        older_start = (now - timedelta(days=60)).isoformat()

        # 近30天的新增知识点数
        recent = db.query_local(
            """
            SELECT COUNT(*) as cnt
            FROM knowledge_points
            WHERE type = 'skill' AND created_at >= ?
        """,
            (recent_start,),
        )
        recent_count = recent[0]["cnt"] if recent else 0

        # 前30天的数据
        older = db.query_local(
            """
            SELECT COUNT(*) as cnt
            FROM knowledge_points
            WHERE type = 'skill' AND created_at >= ? AND created_at < ?
        """,
            (older_start, recent_start),
        )
        older_count = older[0]["cnt"] if older else 0

        if older_count > 0:
            efficiency = min(1.0, recent_count / (older_count * 2))  # 归一化到0-1
            return round(efficiency, 2)
        else:
            return 0.5 if recent_count > 0 else 0.0

    except Exception:
        logger.warning(
            "_calculate_learning_efficiency: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
        )
        return 0.0


def register_growth_analytics_tools(mcp):
    """注册成长分析工具到 MCP"""

    @mcp.tool()
    def get_user_growth_overview_tool() -> str:
        """获取用户成长概览。"""
        return get_user_growth_overview()

    @mcp.tool()
    def get_system_evolution_stats_tool() -> str:
        """获取系统进化统计。"""
        return get_system_evolution_stats()

    @mcp.tool()
    def get_user_skill_radar_tool() -> str:
        """获取用户技能雷达图数据。"""
        return get_user_skill_radar()

    @mcp.tool()
    def get_learning_timeline_tool(limit: int = 20) -> str:
        """获取学习时间线。"""
        return get_learning_timeline(limit)

    @mcp.tool()
    def get_user_activity_heatmap_tool() -> str:
        """获取用户活跃度热力图数据。"""
        return get_user_activity_heatmap()
