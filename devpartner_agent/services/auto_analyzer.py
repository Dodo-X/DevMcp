"""
自动分析引擎 (v4.2)
===================
核心功能：
1. 批量分析未处理的 conversation_archive → 回写 skill_domains/complexity 到 conversations 表
2. 自动填充 conversations 表的 skill_domains / feedback_type / complexity 字段
3. 分析完成后标记 archive.analyzed = 1
4. 自动写入 optimization_feedback 表（基于分析结果）
5. 自动更新 user_skills 用户画像
6. 检测到用户反馈信号时写入 improvement_log（绑定 conversations_id）

触发条件：每积累 10 条未分析存档 → record_dialogue 中自动触发
"""

import json
from datetime import datetime


def analyze_pending_conversations(db, limit: int = 10):
    """
    批量分析未处理的对话存档

    流程：
    1. 取未分析的 archive 记录（带关联的 conversations 数据）
    2. 对每条记录进行技能领域/复杂度/反馈分析
    3. 回写 conversations.skill_domains / complexity / feedback_type
    4. 标记 archive.analyzed = 1
    5. 写入 optimization_feedback / user_skills / improvement_log

    Args:
        db: Database 实例
        limit: 每次最多分析条数
    """
    from devpartner_agent.services.conversation_analyzer import get_analyzer

    analyzer = get_analyzer()
    archives = db.get_unanalyzed_conversations(limit=limit)

    analyzed_count = 0
    feedback_count = 0

    for arch in archives:
        archive_id = arch.get("id")
        conv_id = arch.get("conversations_id")  # conversations 表的主键
        raw_content = arch.get("raw_content", "")
        conv_topic = arch.get("conv_topic", "")
        conv_task_type = arch.get("conv_task_type", "")

        if not raw_content:
            # 空内容直接标记已分析
            db.mark_conversation_analyzed(archive_id, "[]", "simple")
            analyzed_count += 1
            continue

        try:
            # 1. 分析对话内容
            analysis = analyzer.analyze(raw_content)

            skill_domains = analysis.get("skill_domains", [])
            complexity = analysis.get("complexity", "simple")
            user_feedback = analysis.get("user_feedback", {})
            tool_gap = analysis.get("tool_gap", {})
            optimization_suggestions = analysis.get("optimization_suggestions", [])

            skill_domains_str = json.dumps(skill_domains, ensure_ascii=False)

            # 2. 回写 conversations 表（问题3修复：skill_domains/feedback_type/complexity 填充）
            if conv_id:
                feedback_type_str = json.dumps(user_feedback.get("types", []), ensure_ascii=False)
                db.query_local(
                    "UPDATE conversations SET skill_domains = ?, complexity = ?, "
                    "feedback_type = ? WHERE id = ?",
                    (skill_domains_str, complexity, feedback_type_str, conv_id),
                )

            # 3. 标记 archive 已分析（问题2修复：analyzed 字段激活）
            db.mark_conversation_analyzed(archive_id, skill_domains_str, complexity)
            analyzed_count += 1

            # 4. 写入 optimization_feedback（问题5修复：完整生命周期）
            for suggestion in optimization_suggestions:
                try:
                    db.insert_optimization_feedback({
                        "source": "auto_analyzer",
                        "feedback_type": suggestion.get("type", "unknown"),
                        "target_tool": suggestion.get("target_tool", ""),
                        "target_rule": suggestion.get("target_rule", ""),
                        "description": suggestion.get("description", ""),
                        "suggestion": suggestion.get("suggestion", ""),
                        "priority": suggestion.get("priority", "medium"),
                        "status": "pending",
                        "conversation_id": arch.get("conversation_id", ""),
                        "conversations_id": conv_id,
                    })
                    feedback_count += 1
                except Exception:
                    pass

            # 5. 写入 improvement_log（v4.2: 绑定 conversations_id）
            if user_feedback.get("has_feedback") and user_feedback.get("severity") in ("high", "medium"):
                try:
                    db.insert_improvement(
                        category="user_feedback_signal",
                        suggestion=f"对话 [{conv_topic or arch.get('summary', '')}] 检测到用户反馈信号: "
                                   f"{user_feedback.get('types', [])} (严重度: {user_feedback.get('severity', '')})",
                        priority="high" if user_feedback.get("severity") == "high" else "medium",
                        conversations_id=conv_id,
                    )
                except Exception:
                    pass

            # 6. 更新用户技能画像
            for domain_info in skill_domains:
                domain = domain_info.get("domain", "")
                sub_skills = domain_info.get("sub_skills", [])
                if domain:
                    try:
                        db.upsert_user_skills(domain, {
                            "skill_level": "intermediate" if complexity in ("complex", "multi_step") else "beginner",
                            "sub_skills": ", ".join(sub_skills) if sub_skills else "",
                            "evidence": f"auto_analyzer: {conv_topic or arch.get('summary', '')[:100]}",
                            "conversation_ids": arch.get("conversation_id", ""),
                            "hours_spent": 0.2 if complexity == "simple" else 0.5 if complexity == "multi_step" else 1.0,
                            "growth_trend": "stable",
                        })
                    except Exception:
                        pass

            # 7. LLM 用户画像落地（本地 LLM 增强时）
            user_traits = analysis.get("user_traits")
            if user_traits and isinstance(user_traits, dict):
                try:
                    from devpartner_agent.services.user_profile_service import apply_user_traits
                    apply_user_traits(user_traits, "auto_analyzer:llm", conv_id)
                except Exception:
                    pass

        except Exception as e:
            # 分析失败也标记，避免反复重试
            db.mark_conversation_analyzed(archive_id, "[]", "simple")
            analyzed_count += 1
            try:
                db.insert_improvement(
                    category="auto_analyzer_error",
                    suggestion=f"自动分析 archive#{archive_id} 失败: {str(e)[:300]}",
                    priority="low",
                )
            except Exception:
                pass

    # 7. 写入 evolution_log（v4.2: 记录分析事件，不绑定单个 conversations_id 因为是批量操作）
    if analyzed_count > 0:
        try:
            db.log_evolution(
                change_type="auto_analyze",
                description=f"自动分析完成: {analyzed_count} 条存档已分析, "
                            f"{feedback_count} 条优化反馈已生成",
                files_changed="conversations,conversation_archive,optimization_feedback,user_skills",
                version="7.2.0",
            )
        except Exception:
            pass

    return {
        "analyzed": analyzed_count,
        "feedbacks_generated": feedback_count,
        "timestamp": datetime.now().isoformat(),
    }


def analyze_single_conversation(db, conversations_id: int):
    """
    分析单条对话（供 record_conversation 工具调用）

    Args:
        db: Database 实例
        conversations_id: conversations 表主键 ID
    """
    conv_data = db.get_conversation_with_relations(conversations_id)
    if not conv_data:
        return {"error": f"conversations#{conversations_id} 不存在"}

    archive = conv_data.get("archive")
    if not archive:
        return {"error": f"conversations#{conversations_id} 没有关联的 archive 记录"}

    # 直接用批量分析的单条逻辑
    return analyze_pending_conversations(db, limit=1)