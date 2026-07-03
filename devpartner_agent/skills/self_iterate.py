"""
自我迭代技能 v4.1 — 双模式进化
======================================
v4.1 变更：
  - ✅ 新增"本地模式"：远程 MCP 分析 → 返回变更方案 → CodeBuddy 写本地文件
  - ✅ 自动检测模式：有 git → 全流程；无 git → 本地模式
  - ✅ 本地模式报告包含完整的文件路径和变更内容，可直接应用
v4.0 变更：
  - ❌ 移除"仅生成建议存DB"的旧模式
  - ✅ 进化流程改为：收集数据 → 生成改进 → 创建分支 → 应用变更 → 提交 PR 到 GitHub
  - ✅ 自动 git 操作：branch / add / commit / push / create PR
  - ✅ 通过 GitHub API 创建 Pull Request（需 GITHUB_TOKEN）
"""
import json
import os
import re
import shutil
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional


def _is_git_available(repo_path: str = ".") -> bool:
    """检测 git 是否可用且当前目录是 git 仓库"""
    try:
        r = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


async def execute_self_iterate(context: dict = None, mode: str = "auto") -> dict:
    """
    执行自我迭代流程

    Args:
        context: 上下文数据（可选）
        mode: 运行模式
            - "auto": 自动检测（Docker 环境强 → local，有 git → full，无 git → local）
            - "full": 完整 Git + PR 流程
            - "local": 仅分析 + 返回变更方案（适用于远程部署）
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "improvements_applied": [],
        "suggestions_generated": [],
        "pr_url": None,
        "branch_name": None,
    }

    # Step 1: 收集系统数据
    system_data = _collect_system_data()
    result["steps"].append({"step": "collect_data", "status": "ok"})
    result["system_data"] = system_data

    # Step 2: 生成数据驱动的改进建议（含可执行的代码变更）
    suggestions = []
    try:
        suggestions = _generate_data_driven_suggestions(system_data)
        result["suggestions_generated"] = suggestions

        # ── v4.1: 从 suggestions 中提取 mcp_tool_actions（可执行指令）──
        mcp_actions = []
        for s in suggestions:
            detail = s.get("detail", {})
            action = detail.get("action", "")
            if not action or action == "review":
                continue
            if s.get("category") == "mcp_tool_cleanup" and action in ("disable", "deprecate"):
                tool_names = detail.get("unused_sample_names", [])
                if tool_names:
                    mcp_actions.append({
                        "action": action,
                        "tool_names": tool_names,
                        "reason": s.get("suggestion", ""),
                    })
            elif s.get("category") == "mcp_tool_hotspot" and action == "enhance":
                tool_names = detail.get("hot_tool_names", [])
                if tool_names:
                    mcp_actions.append({
                        "action": "enhance",
                        "tool_names": tool_names,
                        "reason": s.get("suggestion", ""),
                    })
        result["mcp_tool_actions"] = mcp_actions

        # 保存建议到数据库（可追溯）
        for suggestion in suggestions:
            try:
                from devpartner_agent.core.database import get_db
                db = get_db()
                db.insert_improvement(
                    category=suggestion.get("category", "general"),
                    suggestion=suggestion.get("suggestion", ""),
                    priority=suggestion.get("priority", "medium"),
                )
            except Exception:
                pass

        result["steps"].append({"step": "generate_suggestions", "status": "ok",
                                 "count": len(suggestions)})
    except Exception as e:
        result["steps"].append({"step": "generate_suggestions", "status": "error",
                                 "error": str(e)})

    # Step 3: 识别可执行的代码变更
    code_changes = _identify_code_changes(suggestions, system_data)
    result["code_changes"] = code_changes

    if not code_changes:
        result["steps"].append({"step": "identify_changes", "status": "ok",
                                 "note": "无可自动执行的代码变更"})
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    result["steps"].append({"step": "identify_changes", "status": "ok",
                             "change_count": len(code_changes)})

    # ============================================================
    # 判断运行模式
    # ============================================================
    use_local_mode = False
    if mode == "local":
        use_local_mode = True
    elif mode == "auto":
        # Docker 部署（ModelScope）强制走本地模式，避免容器内误操作
        if os.environ.get("DEVPARTNER_MODE", "") == "local":
            use_local_mode = True
        else:
            use_local_mode = not _is_git_available()
    # mode == "full": use_local_mode = False

    if use_local_mode:
        # ---------- 本地模式：跳过 Git，返回变更方案 ----------
        result["mode"] = "local"
        result["steps"].append({"step": "mode_detection", "status": "ok",
                                 "note": "本地模式 — 变更方案已返回，请在本地项目手动应用"})
        # 生成可直接应用的代码变更（包含完整文件内容）
        result["file_changes"] = _prepare_local_changes(code_changes)
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # ============================================================
    # 完整模式：Git + PR 流程（需要本地有 git 仓库）
    # ============================================================
    result["mode"] = "full"

    # Step 4: 创建 Git 分支
    branch_name = f"devpartner-evolve-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    result["branch_name"] = branch_name

    try:
        _git_create_branch(branch_name)
        result["steps"].append({"step": "create_branch", "status": "ok",
                                 "branch": branch_name})
    except Exception as e:
        result["steps"].append({"step": "create_branch", "status": "error",
                                 "error": str(e)})
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # Step 5: 应用代码变更
    try:
        applied = _apply_code_changes(code_changes)
        result["improvements_applied"] = applied
        result["steps"].append({"step": "apply_changes", "status": "ok",
                                 "applied_count": len(applied)})
    except Exception as e:
        result["steps"].append({"step": "apply_changes", "status": "error",
                                 "error": str(e)})
        # 回滚分支
        _git_checkout_previous()
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # Step 6: Git add + commit + push
    commit_msg = _build_commit_message(suggestions, code_changes)
    try:
        _git_add_all()
        _git_commit(commit_msg)
        result["steps"].append({"step": "git_commit", "status": "ok",
                                 "message": commit_msg})
    except Exception as e:
        result["steps"].append({"step": "git_commit", "status": "error",
                                 "error": str(e)})
        _git_checkout_previous()
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    try:
        push_output = _git_push(branch_name)
        result["steps"].append({"step": "git_push", "status": "ok",
                                 "output": push_output[:500]})
    except Exception as e:
        result["steps"].append({"step": "git_push", "status": "error",
                                 "error": str(e)})
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # Step 7: 创建 GitHub Pull Request
    try:
        pr_result = _create_github_pr(branch_name, _get_base_branch(), commit_msg,
                                       suggestions)
        result["pr_url"] = pr_result.get("html_url", "")
        result["pr_number"] = pr_result.get("number")
        result["steps"].append({"step": "create_pr", "status": "ok",
                                 "pr_url": result["pr_url"],
                                 "pr_number": result["pr_number"]})
    except Exception as e:
        result["steps"].append({"step": "create_pr", "status": "error",
                                 "error": str(e)})

    # Step 8: 清理：切回原分支
    try:
        _git_checkout_previous()
    except Exception:
        pass

    # Step 9: 生成改进报告
    report = _generate_iteration_report(result)
    result["report"] = report

    return result


def _collect_system_data() -> dict:
    """
    收集系统当前状态数据（v4.0 增强版）

    新增维度：
    - 用户画像：技能领域、熟练度、投入时间
    - 技能评估：技能等级分布、成长趋势
    - MCP 工具使用统计：调用频率、零使用工具
    - 优化反馈统计：待处理反馈、反馈类型
    - 对话统计：有意义对话数 vs 简单工具调用
    - 系统反馈：用户纠正/不满/追问频率
    """
    data = {}

    # 配置信息
    try:
        from devpartner_agent.core.config import get_config
        cfg = get_config()
        data["config"] = {
            "version": cfg.version,
            "evolution_enabled": cfg.evolution.enabled,
            "max_changes_per_day": cfg.evolution.max_changes_per_day,
            "log_retention_days": cfg.data_lifecycle.log_retention_days,
        }
    except Exception:
        data["config"] = {"error": "配置加载失败"}

    # 规则统计
    try:
        from devpartner_agent.core.rule_engine import get_engine
        engine = get_engine()
        data["rules"] = {
            "total": len(engine.get_all()),
            "auto_triggers": len(engine.get_auto_triggers()),
            "names": list(engine.get_all().keys()),
        }
    except Exception:
        data["rules"] = {}

    # ── 数据库统计（增强）──
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        # 总对话数
        conversations = db.query_local("SELECT COUNT(*) as cnt FROM conversations")
        total_convs = conversations[0]["cnt"] if conversations else 0

        # 有意义对话数（排除工具调用记录）
        meaningful = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversations WHERE task_type != '工具调用'"
        )
        meaningful_count = meaningful[0]["cnt"] if meaningful else 0

        # 按任务类型统计
        task_types = db.query_local(
            "SELECT task_type, COUNT(*) as cnt FROM conversations "
            "GROUP BY task_type ORDER BY cnt DESC"
        )

        # 最近7天对话趋势
        weekly_trend = db.query_local("""
            SELECT date(timestamp) as dt, COUNT(*) as cnt
            FROM conversations
            WHERE timestamp >= date('now', '-7 days')
            GROUP BY dt ORDER BY dt
        """)

        # 待处理改进
        improvements = db.query_local(
            "SELECT COUNT(*) as cnt FROM improvement_log WHERE status='pending'"
        )
        pending_improvements = improvements[0]["cnt"] if improvements else 0

        # ── 用户画像数据 ──
        # 技能画像
        skill_profile = db.get_skill_profile()
        skill_summary = db.get_skill_summary()
        domain_stats = db.get_domain_stats()

        # 技能规划
        skill_plans = db.get_skill_plan()

        # ── MCP 工具使用统计 ──
        tool_stats = db.get_tool_stats()
        registered_tools = db.get_registered_tools()
        # 零使用工具
        unused_tools = [t for t in registered_tools if t.get("call_count", 0) == 0]
        # 高频工具（top 10）
        sorted_by_use = sorted(registered_tools,
                                key=lambda t: t.get("call_count", 0), reverse=True)
        hot_tools = sorted_by_use[:10]

        # ── 优化反馈统计 ──
        optimization_feedbacks = db.get_pending_optimizations(limit=100)
        feedback_by_type = {}
        for fb in optimization_feedbacks:
            ft = fb.get("feedback_type", "unknown")
            feedback_by_type[ft] = feedback_by_type.get(ft, 0) + 1

        # ── 版本历史 ──
        versions = db.get_version_history(limit=10)

        # ── 进化历史 ──
        evolution = db.get_evolution_history(limit=20)

        data["database"] = {
            "total_conversations": total_convs,
            "meaningful_conversations": meaningful_count,
            "task_type_distribution": {t["task_type"]: t["cnt"] for t in task_types},
            "weekly_trend": {t["dt"]: t["cnt"] for t in weekly_trend},
            "pending_improvements": pending_improvements,
        }

        data["user_profile"] = {
            "skill_profile": skill_profile,
            "skill_summary": skill_summary,
            "domain_stats": domain_stats,
            "skill_plans": skill_plans,
        }

        data["mcp_tools"] = {
            "total_registered": tool_stats.get("total_tools", 0),
            "total_calls": tool_stats.get("total_calls", 0),
            "unused_tools": [{"name": t["tool_name"], "module": t.get("module", "")}
                              for t in unused_tools],
            "unused_count": len(unused_tools),
            "hot_tools": [{"name": t["tool_name"], "calls": t.get("call_count", 0)}
                           for t in hot_tools],
        }

        data["optimization_feedback"] = {
            "total_pending": len(optimization_feedbacks),
            "by_type": feedback_by_type,
        }

        data["version_history"] = versions
        data["evolution_history"] = evolution

    except Exception as e:
        data["database"] = {"error": str(e)}
        data["user_profile"] = {}
        data["mcp_tools"] = {}
        data["optimization_feedback"] = {}
        data["version_history"] = []
        data["evolution_history"] = []

    # 服务发现统计（v6.0: discovery_service 已移除，MCP工具管理整合到tools层）
    # 原功能由 devpartner_tools.tools 自动发现替代
    try:
        data["mcp_servers"] = {"status": "deprecated", "note": "使用 devpartner_tools 替代"}
    except Exception:
        data["mcp_servers"] = {}

    # 跨AI对话统计
    try:
        from devpartner_agent.services.dialogue_service import get_dialogue
        dialogue = get_dialogue()
        data["dialogue"] = dialogue.get_statistics()
    except Exception:
        data["dialogue"] = {}

    # ── 对话计数器（有意义对话触发统计）──
    try:
        counter_file = Path(__file__).parent.parent.parent / "data" / ".conversation_counter.json"
        if counter_file.exists():
            import json
            with open(counter_file, "r", encoding="utf-8") as f:
                data["conversation_counter"] = json.load(f)
    except Exception:
        data["conversation_counter"] = {}

    # ── 优化状态 ──
    try:
        state_file = Path(__file__).parent.parent.parent / "data" / ".optimization_state.json"
        if state_file.exists():
            import json
            with open(state_file, "r", encoding="utf-8") as f:
                data["optimization_state"] = json.load(f)
    except Exception:
        data["optimization_state"] = {}

    return data


def _generate_data_driven_suggestions(system_data: dict) -> list[dict]:
    """
    基于系统数据生成改进建议（v5.0 - LLM 增强 + 数据驱动双引擎）
    
    策略：
    - ✨ 优先使用 LLM（Ollama/Qwen3.5）进行深度智能分析
    - 🔄 回退到数据驱动的规则引擎（LLM 不可用时）
    
    LLM 分析维度：
    1. 性能瓶颈识别
    2. 用户体验提升
    3. 功能缺口发现
    4. MCP 工具优化
    5. 代码质量改进
    
    规则引擎分析维度（回退方案）：
    1. 用户画像分析 — 技能强弱项、成长趋势、投入分布
    2. 技能评估 — 技能等级分布、短板识别、学习建议
    3. 批评指点 — 从优化反馈中提取用户不满/纠正信号
    4. 未来规划建议 — 基于技能规划的进度评估和目标调整
    5. MCP 工具优化 — 零使用工具精简、高频工具增强、新工具建议
    6. 系统健康度 — 数据库膨胀、规则健康、服务发现
    7. 系统反馈 — 用户反馈趋势、对话质量评估
    """
    
    # ═══════════════════════════════════════════════════════
    # 尝试使用 LLM 智能分析（优先）
    # ═══════════════════════════════════════════════════════
    try:
        from devpartner_agent.services.llm_service import get_llm_service
        llm = get_llm_service()
        
        # 检查是否启用 LLM 自我改进功能
        cfg = llm._get_config()
        if getattr(cfg, 'enhance_self_improvement', False) and llm.is_available():
            import logging
            logger = logging.getLogger(__name__)
            
            logger.info("使用 LLM 生成自我改进建议...")
            
            # 获取历史优化记录作为上下文
            improvement_history = []
            try:
                from devpartner_agent.core.database import get_db
                db = get_db()
                history = db.query_local(
                    "SELECT * FROM improvement_log ORDER BY timestamp DESC LIMIT 20"
                )
                improvement_history = [
                    {
                        "category": h.get("category", ""),
                        "suggestion": h.get("suggestion", "")[:200],
                        "timestamp": h.get("timestamp", ""),
                    }
                    for h in (history or [])
                ]
            except Exception as e:
                logger.debug(f"获取优化历史失败: {e}")
            
            # 调用 LLM 生成建议
            llm_suggestions = llm.generate_self_improvement_suggestions(
                system_data, 
                improvement_history
            )
            
            if llm_suggestions and len(llm_suggestions) > 0:
                logger.info(f"LLM 自我改进建议生成成功: {len(llm_suggestions)} 条")
                
                # 标记为 LLM 生成的建议
                for s in llm_suggestions:
                    s["source"] = "llm"
                    s["confidence"] = "high"
                    
                return llm_suggestions
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"LLM 自我改进建议生成失败，回退到规则引擎: {e}")
    
    # ═══════════════════════════════════════════════════════
    # 回退：使用数据驱动的规则引擎
    # ═══════════════════════════════════════════════════════
    suggestions = []

    # ═══════════════════════════════════════════════════════
    # 1. 用户画像分析
    # ═══════════════════════════════════════════════════════
    user_profile = system_data.get("user_profile", {})
    skill_summary = user_profile.get("skill_summary", {})
    domain_stats = user_profile.get("domain_stats", [])
    skill_profile = user_profile.get("skill_profile", [])

    total_hours = skill_summary.get("total_hours", 0)
    total_domains = skill_summary.get("total_domains", 0)
    domains_map = skill_summary.get("domains", {})

    # 识别强项和弱项
    strengths = []
    weaknesses = []
    for ds in domain_stats:
        domain = ds.get("skill_domain", "")
        hours = ds.get("total_hours", 0) or 0
        count = ds.get("cnt", 0)
        if hours >= 5:
            strengths.append({"domain": domain, "hours": hours, "conversations": count})
        elif hours < 1 and count > 0:
            weaknesses.append({"domain": domain, "hours": hours, "conversations": count})

    if strengths:
        suggestions.append({
            "category": "user_profile_strength",
            "suggestion": f"用户强项领域：{', '.join([s['domain'] for s in strengths[:5]])}",
            "detail": {"strengths": strengths, "total_hours": total_hours},
            "priority": "low",
        })

    if weaknesses:
        suggestions.append({
            "category": "user_profile_weakness",
            "suggestion": f"用户待加强领域：{', '.join([w['domain'] for w in weaknesses[:5]])}",
            "detail": {"weaknesses": weaknesses},
            "priority": "medium",
        })

    # 投入时间分布
    if total_domains > 0:
        suggestions.append({
            "category": "user_profile_summary",
            "suggestion": f"用户累计投入 {total_hours}h，覆盖 {total_domains} 个技术领域",
            "detail": {"total_hours": total_hours, "total_domains": total_domains,
                        "domains": domains_map},
            "priority": "low",
        })

    # ═══════════════════════════════════════════════════════
    # 2. 技能评估与学习建议
    # ═══════════════════════════════════════════════════════
    skill_plans = user_profile.get("skill_plans", [])
    for plan in skill_plans:
        status = plan.get("status", "active")
        progress = plan.get("current_progress", "")
        target_level = plan.get("target_level", "")
        domain = plan.get("skill_domain", "")
        if status == "active":
            suggestions.append({
                "category": "skill_plan_progress",
                "suggestion": f"技能规划 [{domain}]：目标 {target_level}，当前进度: {progress or '未记录'}",
                "detail": {"domain": domain, "target": target_level, "progress": progress},
                "priority": "medium",
            })

    # 学习建议
    if weaknesses and not skill_plans:
        suggestions.append({
            "category": "learning_suggestion",
            "suggestion": f"建议为薄弱领域创建技能规划：{', '.join([w['domain'] for w in weaknesses[:3]])}",
            "detail": {"weak_domains": [w["domain"] for w in weaknesses[:3]]},
            "priority": "high",
        })

    # ═══════════════════════════════════════════════════════
    # 3. 批评指点 — 从优化反馈中提取
    # ═══════════════════════════════════════════════════════
    opt_feedback = system_data.get("optimization_feedback", {})
    feedback_by_type = opt_feedback.get("by_type", {})
    total_pending_feedback = opt_feedback.get("total_pending", 0)

    if feedback_by_type.get("tool_logic_error", 0) > 0:
        suggestions.append({
            "category": "critique_tool_quality",
            "suggestion": f"检测到 {feedback_by_type['tool_logic_error']} 次工具返回结果不准确，"
                           f"建议系统性审查工具实现逻辑，添加结果验证",
            "detail": {"count": feedback_by_type["tool_logic_error"]},
            "priority": "high",
        })

    if feedback_by_type.get("tool_description_weak", 0) > 0:
        suggestions.append({
            "category": "critique_tool_description",
            "suggestion": f"检测到 {feedback_by_type['tool_description_weak']} 次工具描述不够清晰，"
                           f"AI 客户端未能识别应调用的工具。建议优化工具 description 和触发关键词",
            "detail": {"count": feedback_by_type["tool_description_weak"]},
            "priority": "high",
        })

    if feedback_by_type.get("rule_missing", 0) > 0:
        suggestions.append({
            "category": "critique_rule_gap",
            "suggestion": f"检测到 {feedback_by_type['rule_missing']} 次缺少自动触发规则，"
                           f"用户期望自动执行但需要手动操作",
            "detail": {"count": feedback_by_type["rule_missing"]},
            "priority": "medium",
        })

    if total_pending_feedback > 10:
        suggestions.append({
            "category": "critique_backlog",
            "suggestion": f"共有 {total_pending_feedback} 条待处理优化反馈，建议逐批处理，"
                           f"优先处理 high 和 critical 级别",
            "detail": {"total_pending": total_pending_feedback},
            "priority": "high" if total_pending_feedback > 30 else "medium",
        })

    # ═══════════════════════════════════════════════════════
    # 4. 未来规划建议
    # ═══════════════════════════════════════════════════════
    # 基于技能增长趋势
    for domain, info in domains_map.items():
        trend = info.get("trend", "stable")
        level = info.get("level", "beginner")
        hours = info.get("hours", 0)

        if trend == "growing" and level in ("beginner", "intermediate"):
            suggestions.append({
                "category": "future_plan_growth",
                "suggestion": f"[{domain}] 成长趋势良好（{trend}），已投入 {hours}h，"
                               f"当前等级 {level}。建议设定升级目标到 "
                               f"{'intermediate' if level == 'beginner' else 'advanced'}",
                "detail": {"domain": domain, "trend": trend, "level": level, "hours": hours},
                "priority": "medium",
            })

    # 版本演进建议
    version_history = system_data.get("version_history", [])
    if len(version_history) >= 3:
        latest = version_history[0] if version_history else {}
        suggestions.append({
            "category": "future_plan_version",
            "suggestion": f"当前版本 {latest.get('version', 'unknown')}，"
                           f"已有 {len(version_history)} 次版本迭代。"
                           f"建议规划下一版本的重点优化方向",
            "detail": {"current_version": latest.get("version", ""),
                        "version_count": len(version_history)},
            "priority": "low",
        })

    # ═══════════════════════════════════════════════════════
    # 5. MCP 工具优化（v4.1 增强：生成可执行操作指令）
    # ═══════════════════════════════════════════════════════
    mcp_tools = system_data.get("mcp_tools", {})
    unused_tools = mcp_tools.get("unused_tools", [])
    unused_count = mcp_tools.get("unused_count", 0)
    hot_tools = mcp_tools.get("hot_tools", [])

    # ── 零使用工具：生成 disable 指令 ──
    if unused_count > 0:
        unused_names = [t["name"] for t in unused_tools]
        # 安全白名单：这些工具永远不应被禁用
        _SAFE_TOOLS = {
            "check_optimization_needed", "mark_optimization_done",
            "self_iterate", "save_self_iterate_results",
            "record_dialogue", "record_conversation", "log_conversation",
            "get_tool_registry", "system_diagnose", "get_capabilities",
            "check_rule", "get_rules", "process_user_feedback",
        }
        # 排除安全白名单
        unsafe_unused = [n for n in unused_names if n not in _SAFE_TOOLS]

        if len(unsafe_unused) >= 3:
            # 生成 mcp_tool_actions（可执行指令）
            disable_targets = unsafe_unused[:10]  # 最多禁用 10 个
            suggestions.append({
                "category": "mcp_tool_cleanup",
                "suggestion": f"有 {unused_count} 个 MCP 工具从未被调用（{len(unsafe_unused)} 个可安全禁用），"
                               f"包括：{', '.join(unsafe_unused[:5])}... "
                               f"将自动禁用前 {len(disable_targets)} 个",
                "detail": {
                    "unused_count": unused_count,
                    "safe_to_disable": len(unsafe_unused),
                    "unused_sample": unsafe_unused[:5],
                    "action": "disable",
                    "unused_sample_names": disable_targets,
                },
                "priority": "high",
            })
        elif unused_count > 0:
            # 少量未使用，仅生成建议
            suggestions.append({
                "category": "mcp_tool_cleanup",
                "suggestion": f"有 {unused_count} 个 MCP 工具从未被调用，"
                               f"但数量较少或属于安全白名单，暂不自动禁用。请人工评估",
                "detail": {
                    "unused_count": unused_count,
                    "unused_sample": unused_names[:5],
                    "action": "review",
                },
                "priority": "low",
            })

    # ── 高频工具：生成 enhance 指令 ──
    if hot_tools:
        hot_names = [f"{t['name']}({t['calls']})" for t in hot_tools[:5]]
        hot_tool_names = [t["name"] for t in hot_tools[:5]]
        suggestions.append({
            "category": "mcp_tool_hotspot",
            "suggestion": f"高频使用工具：{', '.join(hot_names)}。"
                           f"建议重点优化这些工具的性能和稳定性",
            "detail": {
                "hot_tools": hot_tools[:5],
                "action": "enhance",
                "hot_tool_names": hot_tool_names,
            },
            "priority": "medium",
        })

    # 工具使用率分布
    total_registered = mcp_tools.get("total_registered", 0)
    total_calls = mcp_tools.get("total_calls", 0)
    if total_registered > 0 and total_calls > 0:
        avg_calls = total_calls / total_registered
        if avg_calls < 2:
            suggestions.append({
                "category": "mcp_tool_utilization",
                "suggestion": f"工具平均调用次数仅 {avg_calls:.1f} 次（{total_registered} 个工具，"
                               f"{total_calls} 次调用），利用率偏低。"
                               f"建议增强工具描述和触发条件，提高工具发现率",
                "detail": {"avg_calls": round(avg_calls, 1)},
                "priority": "medium",
            })

    # ═══════════════════════════════════════════════════════
    # 6. 系统健康度
    # ═══════════════════════════════════════════════════════
    db_data = system_data.get("database", {})
    total_convs = db_data.get("total_conversations", 0)
    meaningful_convs = db_data.get("meaningful_conversations", 0)

    if total_convs > 500:
        suggestions.append({
            "category": "database_health",
            "suggestion": f"数据库对话记录已达 {total_convs} 条（其中 {meaningful_convs} 条有意义对话），"
                           f"建议定期归档清理旧记录",
            "priority": "medium",
        })

    # 对话趋势
    weekly_trend = db_data.get("weekly_trend", {})
    if len(weekly_trend) >= 3:
        values = list(weekly_trend.values())
        if len(values) >= 2 and values[-1] > values[0] * 1.5:
            suggestions.append({
                "category": "system_growth",
                "suggestion": "最近7天对话量呈上升趋势，系统使用率正在增长",
                "detail": {"trend": weekly_trend},
                "priority": "low",
            })

    # 规则引擎
    rules = system_data.get("rules", {})
    if rules.get("total", 0) == 0:
        suggestions.append({
            "category": "rule_engine",
            "suggestion": "规则引擎中没有规则，建议添加至少一个自动触发规则",
            "priority": "high",
        })

    # 待处理改进
    pending_improvements = db_data.get("pending_improvements", 0)
    if pending_improvements > 20:
        suggestions.append({
            "category": "maintenance",
            "suggestion": f"有 {pending_improvements} 条待处理改进建议，建议逐步应用或清理",
            "priority": "high" if pending_improvements > 50 else "medium",
        })

    # MCP服务发现
    mcp = system_data.get("mcp_servers", {})
    known = mcp.get("known", 0)
    if known < 5:
        suggestions.append({
            "category": "mcp_discovery",
            "suggestion": f"已知 MCP 服务仅 {known} 个，建议运行 discover_mcp_servers 扩充服务库",
            "priority": "high" if known == 0 else "medium",
        })

    # 跨AI对话
    dialogue = system_data.get("dialogue", {})
    unread = dialogue.get("unread", 0)
    if unread > 5:
        suggestions.append({
            "category": "cross_dialogue",
            "suggestion": f"跨AI对话有 {unread} 条未读消息，建议及时查看和回复",
            "priority": "high",
        })

    # ═══════════════════════════════════════════════════════
    # 7. 系统反馈总结
    # ═══════════════════════════════════════════════════════
    optimization_state = system_data.get("optimization_state", {})
    conv_counter = system_data.get("conversation_counter", {})

    if optimization_state.get("optimization_pending"):
        last_opt = optimization_state.get("last_optimization_at", "从未")
        suggestions.append({
            "category": "system_feedback",
            "suggestion": f"系统有待处理的优化标记。上次优化时间: {last_opt}。"
                           f"当前有意义对话计数: {conv_counter.get('total_count', 0)}",
            "detail": {"last_optimization_at": last_opt,
                        "conversation_count": conv_counter.get("total_count", 0)},
            "priority": "medium",
        })

    return suggestions


def _identify_code_changes(suggestions: list[dict],
                            system_data: dict) -> list[dict]:
    """
    将改进建议转化为可执行的代码变更

    返回变更列表，每条包含：
    - file: 目标文件路径（相对项目根目录）
    - action: create / modify / delete
    - description: 变更描述
    - content: 新内容（create/modify 时）
    """
    changes = []

    rules = system_data.get("rules", {})
    rule_names = rules.get("names", [])

    # 1. 规则引擎为空 → 添加一个默认规则文件
    if rules.get("total", 0) == 0:
        default_rule = '''"""
devPartner 自动生成规则
由自我进化引擎生成，可自行修改
"""
from devpartner_agent.core.rule_engine import Rule


RULES = [
    Rule(
        name="daily_summary_reminder",
        description="每日下班前提醒记录工作总结",
        triggers=["总结", "今天做了什么", "下班", "工作总结", "daily summary"],
        priority="medium",
        auto_trigger=True,
        action="suggest_daily_summary",
    ),
    Rule(
        name="dependency_check",
        description="修改 requirements.txt 后提醒检查依赖",
        triggers=["pip install", "requirements", "依赖"],
        priority="low",
        auto_trigger=False,
        action="check_dependencies",
    ),
    Rule(
        name="git_commit_reminder",
        description="大量文件变更后提醒提交",
        triggers=["git commit", "提交", "更新了很多"],
        priority="high",
        auto_trigger=True,
        action="remind_git_commit",
    ),
]
'''
        existing_default = "default" in rule_names if rule_names else False
        if not existing_default:
            changes.append({
                "file": "rules/default_rules.py",
                "action": "create",
                "description": "添加默认自动触发规则（每日总结提醒 / 依赖检查 / Git提交提醒）",
                "content": default_rule,
            })

    # 2. MCP 服务太少 → 更新 config.yaml 自动补全已知服务列表
    mcp = system_data.get("mcp_servers", {})
    known = mcp.get("known", 0)
    if known < 5:
        # 读取配置文件，追加推荐的服务
        changes.append({
            "file": "config.yaml",
            "action": "modify",
            "description": f"自动扩充 known_mcp_servers（当前仅 {known} 个，推荐添加更多免费服务）",
            "merge_mcp_servers": [
                "@modelcontextprotocol/server-filesystem",
                "@modelcontextprotocol/server-github",
                "@modelcontextprotocol/server-sequential-thinking",
                "@modelcontextprotocol/server-fetch",
                "@modelcontextprotocol/server-sqlite",
                "@modelcontextprotocol/server-git",
                "@modelcontextprotocol/server-memory",
                "@upstash/context7-mcp",
                "@anthropic/mcp-server-brave-search",
                "@anthropic/mcp-server-playwright",
                "@modelcontextprotocol/server-postgres",
            ],
        })

    # 3. 数据库膨胀 → 添加归档脚本
    db_data = system_data.get("database", {})
    conv_count = db_data.get("total_conversations", 0)
    if conv_count > 1000:
        archive_script = '''"""
数据库归档脚本（由 devPartner 自我进化引擎生成）
用途：将超过 30 天的旧对话记录归档
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


def archive_old_conversations(db_path: str, days: int = 30):
    """归档旧对话记录到 archive 表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # 确保 archive 表存在
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations_archive (
            id INTEGER PRIMARY KEY,
            agent TEXT, topic TEXT, task_type TEXT,
            user_intent TEXT, actions TEXT,
            problems TEXT, solutions TEXT,
            decisions TEXT, timestamp TEXT,
            archived_at TEXT
        )
    """)

    # 移动旧记录
    cursor.execute("""
        INSERT INTO conversations_archive
        SELECT *, ? FROM conversations WHERE timestamp < ?
    """, (datetime.now().isoformat(), cutoff))

    moved = cursor.rowcount

    # 删除原表中的旧记录
    cursor.execute("DELETE FROM conversations WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()

    print(f"归档完成: {moved} 条记录已移至 conversations_archive")
    return moved


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "data/devpartner.db"
    archive_old_conversations(db)
'''
        changes.append({
            "file": "tools/db_archive.py",
            "action": "create",
            "description": f"数据库有 {conv_count} 条记录，添加归档脚本 tools/db_archive.py",
            "content": archive_script,
        })

    return changes


def _apply_code_changes(changes: list[dict]) -> list[dict]:
    """将代码变更实际写入文件系统"""
    applied = []
    project_root = Path(__file__).parent.parent

    for change in changes:
        action = change.get("action")
        file_path = project_root / change["file"]
        description = change.get("description", "")

        try:
            if action == "create":
                file_path.parent.mkdir(parents=True, exist_ok=True)
                if not file_path.exists():
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(change.get("content", ""))
                    applied.append({
                        "file": change["file"],
                        "action": "create",
                        "description": description,
                        "applied": True,
                    })

            elif action == "modify":
                if "merge_mcp_servers" in change:
                    # 特殊处理：合并 MCP 服务到 config.yaml
                    _merge_mcp_servers_to_config(file_path,
                                                  change["merge_mcp_servers"])
                    applied.append({
                        "file": change["file"],
                        "action": "modify",
                        "description": description,
                        "applied": True,
                    })
                elif "content" in change:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(change["content"])
                    applied.append({
                        "file": change["file"],
                        "action": "modify",
                        "description": description,
                        "applied": True,
                    })

            elif action == "delete":
                if file_path.exists():
                    file_path.unlink()
                    applied.append({
                        "file": change["file"],
                        "action": "delete",
                        "description": description,
                        "applied": True,
                    })

        except Exception as e:
            applied.append({
                "file": change["file"],
                "action": action,
                "description": description,
                "applied": False,
                "error": str(e),
            })

    return applied


def _merge_mcp_servers_to_config(config_path: Path, new_servers: list[str]):
    """向 config.yaml 合并新的 MCP 服务列表（去重追加）"""
    if not config_path.exists():
        return

    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 收集已有的服务器
    existing = set()
    in_servers = False
    result_lines = []
    indent = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("known_mcp_servers:"):
            in_servers = True
            # 获取缩进
            indent = line[:len(line) - len(line.lstrip())] + "  "
            result_lines.append(line)
            continue
        if in_servers:
            if stripped.startswith("- "):
                server = stripped[2:].strip().strip('"').strip("'")
                existing.add(server)
                result_lines.append(line)
                continue
            else:
                # known_mcp_servers 列表结束
                # 追加新服务
                for srv in new_servers:
                    if srv not in existing:
                        result_lines.append(f'{indent}- "{srv}"\n')
                in_servers = False
        result_lines.append(line)

    # 如果列表中一直到最后还在 in_servers
    if in_servers:
        for srv in new_servers:
            if srv not in existing:
                result_lines.append(f'{indent}- "{srv}"\n')

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(result_lines)


# ================================================================
# Git 操作
# ================================================================

_PREVIOUS_BRANCH = None


def _run_git(args: list, repo_path: str = ".") -> subprocess.CompletedProcess:
    """执行 git 命令"""
    result = subprocess.run(
        ["git", "-C", repo_path] + args,
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git 命令执行失败")
    return result


def _git_create_branch(branch_name: str, repo_path: str = "."):
    """创建并切换到新分支（记录原分支以便回滚）"""
    global _PREVIOUS_BRANCH
    # 记录当前分支
    r = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
    )
    _PREVIOUS_BRANCH = r.stdout.strip()
    _run_git(["checkout", "-b", branch_name], repo_path)


def _git_checkout_previous(repo_path: str = "."):
    """切回当前进化操作之前的原始分支"""
    global _PREVIOUS_BRANCH
    if _PREVIOUS_BRANCH:
        try:
            _run_git(["checkout", _PREVIOUS_BRANCH], repo_path)
        except RuntimeError:
            pass


def _git_add_all(repo_path: str = "."):
    """暂存所有变更"""
    _run_git(["add", "-A"], repo_path)


def _git_commit(message: str, repo_path: str = "."):
    """提交变更"""
    _run_git(["commit", "-m", message], repo_path)


def _git_push(branch_name: str, repo_path: str = "."):
    """推送分支到 origin"""
    result = _run_git(["push", "-u", "origin", branch_name], repo_path)
    return result.stdout + result.stderr


def _get_base_branch(repo_path: str = ".") -> str:
    """获取基础分支名（优先 master，其次 main）"""
    for name in ["master", "main"]:
        r = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", f"origin/{name}"],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
        )
        if r.returncode == 0:
            return name
    return "master"


def _get_github_repo(repo_path: str = ".") -> tuple:
    """从 git remote 解析 GitHub owner/repo"""
    r = subprocess.run(
        ["git", "-C", repo_path, "remote", "get-url", "origin"],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
    )
    url = r.stdout.strip()
    # 支持 https://github.com/owner/repo.git 和 git@github.com:owner/repo.git
    m = re.search(r'github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$', url)
    if not m:
        raise RuntimeError(f"无法从 remote URL 解析 GitHub 仓库: {url}")
    return m.group(1), m.group(2)


def _build_commit_message(suggestions: list[dict],
                           code_changes: list[dict]) -> str:
    """根据建议和变更生成提交信息"""
    categories = set(s.get("category", "") for s in suggestions)
    lines = ["🤖 devPartner 自我进化", ""]
    for change in code_changes:
        lines.append(f"- {change.get('action', 'modify')}: {change.get('description', change.get('file', ''))}")
    lines.append("")
    lines.append(f"分析维度: {', '.join(categories) if categories else '系统巡检'}")
    lines.append("Auto-generated by devPartner self-evolution engine")
    return "\n".join(lines)


# ================================================================
# GitHub API
# ================================================================

def _create_github_pr(branch_name: str, base_branch: str,
                       title: str, suggestions: list[dict]) -> dict:
    """通过 GitHub REST API 创建 Pull Request"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("请设置 GITHUB_TOKEN 环境变量 (https://github.com/settings/tokens)")

    owner, repo = _get_github_repo()

    # 构建 PR body
    body_lines = ["## 🤖 devPartner 自我进化 PR", "",
                   "本 PR 由 devPartner 自我进化引擎自动生成。", "",
                   "### 分析维度"]
    for s in suggestions:
        body_lines.append(f"- **{s.get('category', '')}**: {s.get('suggestion', '')}")

    body_lines.extend(["", "### 变更文件", ""])
    body_lines.append("详见 commit diff。")

    # 用 httpx 调用 GitHub API
    import httpx
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": title.split("\n")[0][:256],  # PR 标题用第一行
        "body": "\n".join(body_lines),
        "head": branch_name,
        "base": base_branch,
    }

    resp = httpx.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub API 返回 {resp.status_code}: {resp.text[:500]}")

    return resp.json()


# ================================================================
# 报告生成
# ================================================================

def _generate_iteration_report(result: dict) -> str:
    """生成自我迭代报告（v4.0 增强版 — 含用户画像/技能/批评/规划/MCP工具）"""
    is_local = result.get("mode") == "local"

    lines = [
        "# 🧬 devPartner 自我进化报告",
        f"**生成时间**: {result.get('timestamp', '')}",
        f"**运行模式**: {'📡 本地模式（远程分析 → 本地落地）' if is_local else '🌐 完整模式（Git + PR）'}",
        "",
    ]

    # PR 信息
    if result.get("pr_url"):
        lines.append(f"## 🔗 Pull Request")
        lines.append(f"- **PR**: [#{result.get('pr_number', '?')}]({result['pr_url']})")
        lines.append(f"- **分支**: `{result.get('branch_name', '')}`")
        lines.append("")
    elif result.get("branch_name"):
        lines.append(f"## 🌿 分支")
        lines.append(f"- **分支名**: `{result['branch_name']}`")
        lines.append(f"- **状态**: PR 创建失败或未推送")
        lines.append("")

    # ── v4.0 系统数据摘要 ──
    system_data = result.get("system_data", {})
    if system_data:
        lines.append("## 📊 系统概览")
        lines.append("")

        # 配置信息
        config = system_data.get("config", {})
        lines.append(f"- **版本**: {config.get('version', 'unknown')}")
        lines.append(f"- **进化引擎**: {'启用' if config.get('evolution_enabled') else '禁用'}")

        # 数据库
        db_data = system_data.get("database", {})
        lines.append(f"- **总对话数**: {db_data.get('total_conversations', 0)} "
                       f"（有意义: {db_data.get('meaningful_conversations', 0)}）")

        # 用户画像
        user_profile = system_data.get("user_profile", {})
        skill_summary = user_profile.get("skill_summary", {})
        lines.append(f"- **技能领域**: {skill_summary.get('total_domains', 0)} 个，"
                       f"累计 {skill_summary.get('total_hours', 0)}h")

        # MCP 工具
        mcp_tools = system_data.get("mcp_tools", {})
        lines.append(f"- **MCP 工具**: {mcp_tools.get('total_registered', 0)} 个注册，"
                       f"{mcp_tools.get('total_calls', 0)} 次调用，"
                       f"{mcp_tools.get('unused_count', 0)} 个零使用")

        # 优化反馈
        opt_fb = system_data.get("optimization_feedback", {})
        lines.append(f"- **待处理反馈**: {opt_fb.get('total_pending', 0)} 条")

        # 对话计数器
        conv_counter = system_data.get("conversation_counter", {})
        if conv_counter:
            lines.append(f"- **有意义对话计数**: {conv_counter.get('total_count', 0)} "
                           f"（上次优化后: {conv_counter.get('total_count', 0) - conv_counter.get('last_optimize_count', 0)}）")

        lines.append("")

    # ── 用户画像分析 ──
    if user_profile:
        lines.append("## 👤 用户画像")
        lines.append("")
        domain_stats = user_profile.get("domain_stats", [])
        if domain_stats:
            lines.append("| 领域 | 投入时间 | 对话数 |")
            lines.append("|------|---------|--------|")
            for ds in domain_stats[:10]:
                domain = ds.get("skill_domain", "")
                hours = ds.get("total_hours", 0) or 0
                count = ds.get("cnt", 0)
                lines.append(f"| {domain} | {hours}h | {count} |")
            lines.append("")

        skill_profile = user_profile.get("skill_profile", [])
        if skill_profile:
            lines.append("| 领域 | 等级 | 趋势 |")
            lines.append("|------|------|------|")
            for sp in skill_profile[:10]:
                lines.append(f"| {sp.get('skill_domain', '')} | {sp.get('skill_level', '')} "
                               f"| {sp.get('growth_trend', '')} |")
            lines.append("")

    # ── 技能规划 ──
    skill_plans = user_profile.get("skill_plans", [])
    if skill_plans:
        lines.append("## 🎯 技能规划")
        lines.append("")
        for plan in skill_plans:
            lines.append(f"- **{plan.get('skill_domain', '')}**: "
                           f"目标 {plan.get('target_level', '')} | "
                           f"进度: {plan.get('current_progress', '未记录')} | "
                           f"状态: {plan.get('status', '')}")
        lines.append("")

    # 执行步骤
    lines.append("## 📋 执行步骤")
    for step in result.get("steps", []):
        step_name = step.get("step", "")
        status = step.get("status", "")
        icon = "✅" if status == "ok" else "❌" if status == "error" else "⏭️"
        detail = ""
        if "branch" in step:
            detail = f" → `{step['branch']}`"
        elif "count" in step:
            detail = f" ({step['count']} 条)"
        elif "note" in step:
            detail = f" — {step['note']}"
        elif "error" in step:
            detail = f" — {step['error']}"
        elif "pr_url" in step:
            detail = f" → {step['pr_url']}"
        elif "message" in step:
            detail = f" → {step['message'][:80]}..."
        elif "data_points" in step:
            detail = f" (收集了 {step['data_points']} 个数据维度)"
        lines.append(f"- {icon} **{step_name}**{detail}")

    lines.append("")

    # 分析结果（按类别分组）
    lines.append("## 🔍 分析结果与建议")
    suggestions = result.get("suggestions_generated", [])
    if suggestions:
        # 按类别分组
        by_category = {}
        for s in suggestions:
            cat = s.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(s)

        category_labels = {
            "user_profile_strength": "💪 用户强项",
            "user_profile_weakness": "🎓 待加强领域",
            "user_profile_summary": "📊 画像摘要",
            "skill_plan_progress": "📈 技能规划进度",
            "learning_suggestion": "📚 学习建议",
            "critique_tool_quality": "⚠️ 工具质量问题",
            "critique_tool_description": "📝 工具描述优化",
            "critique_rule_gap": "🔧 规则缺失",
            "critique_backlog": "📋 待处理积压",
            "future_plan_growth": "🚀 成长规划",
            "future_plan_version": "🏷️ 版本规划",
            "mcp_tool_cleanup": "🧹 工具精简",
            "mcp_tool_hotspot": "🔥 高频工具",
            "mcp_tool_utilization": "📉 工具利用率",
            "database_health": "💾 数据库健康",
            "system_growth": "📈 系统增长",
            "rule_engine": "⚙️ 规则引擎",
            "maintenance": "🔧 维护建议",
            "mcp_discovery": "🔍 服务发现",
            "cross_dialogue": "💬 跨AI对话",
            "system_feedback": "🔄 系统反馈",
        }

        for cat, items in by_category.items():
            label = category_labels.get(cat, f"📌 {cat}")
            lines.append(f"### {label}")
            for s in items:
                pri = s.get("priority", "")
                pri_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(pri, "")
                lines.append(f"- {pri_icon} {s.get('suggestion', '')}")
            lines.append("")
    else:
        lines.append("- 系统运行正常，未发现需改进项")
        lines.append("")

    # MCP 工具详情
    mcp_tools = system_data.get("mcp_tools", {}) if system_data else {}
    unused_tools = mcp_tools.get("unused_tools", [])
    hot_tools = mcp_tools.get("hot_tools", [])
    if unused_tools or hot_tools:
        lines.append("## 🔧 MCP 工具分析")
        lines.append("")
        if hot_tools:
            lines.append("### 🔥 高频使用工具")
            for t in hot_tools[:5]:
                lines.append(f"- **{t.get('name', '')}**: {t.get('calls', 0)} 次调用")
            lines.append("")
        if unused_tools:
            lines.append(f"### 🧹 零使用工具（共 {len(unused_tools)} 个）")
            for t in unused_tools[:10]:
                lines.append(f"- `{t.get('name', '')}` ({t.get('module', '')})")
            lines.append("")

    # 代码变更
    lines.append("## 💻 代码变更")
    changes = result.get("code_changes", [])
    if changes:
        for ch in changes:
            lines.append(f"- `{ch.get('file', '?')}` ({ch.get('action', '')}): {ch.get('description', '')}")
    else:
        lines.append("- 本次无需代码变更")

    lines.append("")

    # 本地模式：显示可直接应用的文件变更
    if is_local:
        file_changes = result.get("file_changes", [])
        if file_changes:
            lines.append("## 📝 待应用到本地的文件变更")
            lines.append("> 以下是需要在本地项目中手动应用的变更：")
            lines.append("")
            for fc in file_changes:
                fpath = fc.get("file", "")
                faction = fc.get("action", "")
                fdesc = fc.get("description", "")
                fcontent = fc.get("content", "")
                lines.append(f"### {'🆕 新建' if faction == 'create' else '✏️ 修改'}: `{fpath}`")
                lines.append(f"**说明**: {fdesc}")
                lines.append("")
                if fcontent:
                    lines.append("```")
                    lines.append(fcontent[:5000])
                    if len(fcontent) > 5000:
                        lines.append(f"\n... (内容过长，已截断，完整长度 {len(fcontent)} 字符)")
                    lines.append("```")
                lines.append("")
        else:
            lines.append("- 本次无需要应用到本地的文件变更")
        lines.append("")

    # 应用结果（完整模式）
    if not is_local:
        lines.append("## ⚡ 应用结果")
        applied = result.get("improvements_applied", [])
        if applied:
            for imp in applied:
                status = "✅ 已应用" if imp.get("applied") else "❌ 失败"
                lines.append(f"- {status} - `{imp.get('file', '')}`: {imp.get('description', '')}")
                if imp.get("error"):
                    lines.append(f"  - 错误: {imp['error']}")
        else:
            lines.append("- 本次未应用代码变更")

    # 本地模式的下一步指引
    if is_local:
        lines.append("---")
        lines.append("")
        lines.append("## 🎯 下一步操作")
        lines.append("")
        lines.append("请在本地 `d:\\WorkSpace\\Code\\devPartner` 项目中：")
        lines.append("")
        lines.append("1. **审查变更**：查看上方代码变更是否符合预期")
        lines.append("2. **应用变更**：让 CodeBuddy 将上述文件变更写入本地项目")
        lines.append("3. **测试运行**：`python server.py` 验证变更无语法错误")
        lines.append("4. **决定推送**：审查通过后 `git add && git commit && git push`")
        lines.append("5. **更新部署**：如需同步到 ModelScope，重新构建镜像并部署")

    return "\n".join(lines)


def _prepare_local_changes(code_changes: list) -> list:
    """
    为本地模式准备代码变更列表
    返回每个文件的路径和新内容，方便 CodeBuddy 直接写入本地项目
    """
    changes = []
    for ch in code_changes:
        change_info = {
            "file": ch.get("file", ""),
            "action": ch.get("action", ""),  # modify / create
            "description": ch.get("description", ""),
            "content": ch.get("content", ""),
        }
        # 如果是 modify 且没有 content，尝试读取远程容器的当前文件
        if ch.get("action") == "modify" and not change_info["content"]:
            try:
                file_path = ch.get("file", "")
                if os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        change_info["content"] = f.read()
            except Exception:
                pass
        changes.append(change_info)
    return changes


async def check_and_improve() -> dict:
    """检查并执行改进（轻量版，适合频繁调用）"""
    try:
        from devpartner_agent.core.database import get_db
        db = get_db()

        # 检查待处理的改进
        pending = db.get_pending_improvements()
        if not pending:
            return {"has_pending": False, "count": 0}

        # 获取最高优先级的改进
        high_priority = [i for i in pending if i.get("priority") == "high"]
        return {
            "has_pending": True,
            "count": len(pending),
            "high_priority": len(high_priority),
            "top_suggestion": high_priority[0].get("suggestion", "") if high_priority else "",
        }
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# 公共入口函数
# ============================================================

def run_self_iterate(mode: str = "auto") -> dict:
    """
    执行自我迭代流程（公共入口）
    
    这是被 server.py 调用的入口函数，编排完整的自我迭代流程：
    1. 收集系统数据
    2. 生成改进建议
    3. 识别代码变更
    4. 应用变更
    5. 生成报告
    
    Args:
        mode: 运行模式
            - 'auto': 自动选择
            - 'local': 本地模式
            - 'full': 完整模式（Git分支+提交+PR）
            - 'analyze': 仅分析不执行变更
    
    Returns:
        dict: 迭代结果
    """
    import json
    from datetime import datetime
    
    result = {
        "success": False,
        "mode": mode,
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "suggestions": [],
        "code_changes": [],
        "applied_changes": [],
        "git_operations": [],
    }
    
    try:
        # Step 1: 收集系统数据
        try:
            system_data = _collect_system_data()
            result["steps"].append({
                "step": "collect_data",
                "status": "ok",
                "data_points": len(system_data),
            })
            result["system_data_summary"] = {
                "project_files": system_data.get("project_files", 0),
                "log_files": system_data.get("log_files", 0),
                "db_records": system_data.get("db_records", 0),
            }
        except Exception as e:
            result["steps"].append({
                "step": "collect_data",
                "status": "error",
                "error": str(e),
            })
            result["error"] = f"数据收集失败: {e}"
            return result
        
        # Step 2: 生成改进建议
        try:
            suggestions = _generate_data_driven_suggestions(system_data)
            result["suggestions"] = suggestions
            result["steps"].append({
                "step": "generate_suggestions",
                "status": "ok",
                "count": len(suggestions),
            })
        except Exception as e:
            result["steps"].append({
                "step": "generate_suggestions",
                "status": "error",
                "error": str(e),
            })
            result["error"] = f"建议生成失败: {e}"
            return result
        
        # Step 3: 识别代码变更
        try:
            code_changes = _identify_code_changes(suggestions, system_data)
            result["code_changes"] = code_changes
            result["steps"].append({
                "step": "identify_changes",
                "status": "ok",
                "count": len(code_changes),
            })
        except Exception as e:
            result["steps"].append({
                "step": "identify_changes",
                "status": "error",
                "error": str(e),
            })
            result["error"] = f"变更识别失败: {e}"
            return result
        
        # Step 4: 应用变更（非 analyze 模式）
        if mode != "analyze" and code_changes:
            try:
                applied = _apply_code_changes(code_changes)
                result["applied_changes"] = applied
                result["steps"].append({
                    "step": "apply_changes",
                    "status": "ok",
                    "count": len(applied),
                })
            except Exception as e:
                result["steps"].append({
                    "step": "apply_changes",
                    "status": "error",
                    "error": str(e),
                })
        elif mode == "analyze":
            result["steps"].append({
                "step": "apply_changes",
                "status": "skipped",
                "reason": "analyze 模式，跳过变更应用",
            })
        
        # Step 5: Git 操作（仅 full 模式）
        if mode == "full" and _is_git_available():
            try:
                branch_name = f"auto-iterate-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                _git_create_branch(branch_name)
                _git_add_all()
                commit_msg = _build_commit_message(suggestions, code_changes, result)
                _git_commit(commit_msg)
                result["git_operations"].append({
                    "action": "create_branch",
                    "branch": branch_name,
                    "status": "ok",
                })
                result["steps"].append({
                    "step": "git_operations",
                    "status": "ok",
                    "branch": branch_name,
                })
            except Exception as e:
                result["steps"].append({
                    "step": "git_operations",
                    "status": "error",
                    "error": str(e),
                })
        
        result["success"] = True
        return result
        
    except Exception as e:
        result["error"] = f"自我迭代异常: {e}"
        result["steps"].append({
            "step": "fatal",
            "status": "error",
            "error": str(e),
        })
        return result