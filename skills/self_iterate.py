"""
自我迭代技能
- 涡轮效应执行
- 系统改进分析
- 自动应用改进
- 验证改进效果
"""
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional


async def execute_self_iterate(context: dict = None) -> dict:
    """执行自我迭代流程"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "improvements_applied": [],
        "suggestions_generated": [],
    }

    # Step 1: 收集系统数据
    system_data = _collect_system_data()
    result["steps"].append({"step": "collect_data", "status": "ok"})

    # Step 2: Ollama 分析改进机会
    try:
        from services.ollama_service import get_ollama
        ollama = get_ollama()

        analysis = await ollama.analyze_system_improvements(system_data)
        if analysis.get("success") and analysis.get("parsed"):
            suggestions = analysis["parsed"]
            result["suggestions_generated"] = suggestions

            # 保存改进建议到数据库
            for category, items in suggestions.items():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            suggestion_text = item.get("suggestion", str(item))
                        else:
                            suggestion_text = str(item)

                        try:
                            from core.database import get_db
                            db = get_db()
                            db.insert_improvement(
                                category=category,
                                suggestion=suggestion_text,
                                priority="high" if category == "priority_order" else "medium",
                            )
                        except Exception:
                            pass

            result["steps"].append({"step": "analyze", "status": "ok"})
        else:
            result["steps"].append({"step": "analyze", "status": "error",
                                     "error": analysis.get("error", "分析失败")})
            return result
    except Exception as e:
        result["steps"].append({"step": "analyze", "status": "error", "error": str(e)})
        return result

    # Step 3: 自动应用低风险改进
    try:
        applied = _auto_apply_improvements(result["suggestions_generated"])
        result["improvements_applied"] = applied
        result["steps"].append({"step": "apply_improvements", "status": "ok",
                                 "applied_count": len(applied)})
    except Exception as e:
        result["steps"].append({"step": "apply_improvements", "status": "error",
                                 "error": str(e)})

    # Step 4: 生成改进报告
    report = _generate_iteration_report(result)
    result["report"] = report

    return result


def _collect_system_data() -> dict:
    """收集系统当前状态数据"""
    data = {}

    # 配置信息
    try:
        from core.config import get_config
        cfg = get_config()
        data["config"] = {
            "version": cfg.version,
            "ollama_model": cfg.ollama.model,
            "evolution_enabled": cfg.evolution.enabled,
        }
    except Exception:
        data["config"] = {"error": "配置加载失败"}

    # 规则统计
    try:
        from core.rule_engine import get_engine
        engine = get_engine()
        data["rules"] = {
            "total": len(engine.get_all()),
            "auto_triggers": len(engine.get_auto_triggers()),
            "names": list(engine.get_all().keys()),
        }
    except Exception:
        data["rules"] = {}

    # 数据库统计
    try:
        from core.database import get_db
        db = get_db()
        conversations = db.query_local("SELECT COUNT(*) as cnt FROM conversations")
        improvements = db.query_local("SELECT COUNT(*) as cnt FROM system_improvements WHERE status='pending'")
        data["database"] = {
            "conversations": conversations[0]["cnt"] if conversations else 0,
            "pending_improvements": improvements[0]["cnt"] if improvements else 0,
        }
    except Exception:
        data["database"] = {}

    # 服务发现统计
    try:
        from services.discovery_service import get_discovery
        discovery = get_discovery()
        data["mcp_servers"] = discovery.get_scan_status()
    except Exception:
        data["mcp_servers"] = {}

    # 跨AI对话统计
    try:
        from services.dialogue_service import get_dialogue
        dialogue = get_dialogue()
        data["dialogue"] = dialogue.get_statistics()
    except Exception:
        data["dialogue"] = {}

    return data


def _auto_apply_improvements(suggestions: dict) -> list[dict]:
    """自动应用低风险的改进建议"""
    applied = []

    # 这里可以添加自动化的改进应用逻辑
    # 例如：自动修复配置、自动添加推荐的MCP服务等

    # 检查是否有新的 MCP 服务推荐
    mcp_suggestions = suggestions.get("mcp_suggestions", [])
    if mcp_suggestions:
        for suggestion in mcp_suggestions:
            applied.append({
                "type": "mcp_suggestion",
                "content": suggestion,
                "applied": False,  # 需要人工确认
                "reason": "新MCP服务需要确认后再集成",
            })

    # 检查配置优化建议
    config_suggestions = suggestions.get("performance_optimizations", [])
    for suggestion in config_suggestions:
        applied.append({
            "type": "performance",
            "content": suggestion,
            "applied": False,
            "reason": "性能优化需测试后再应用",
        })

    return applied


def _generate_iteration_report(result: dict) -> str:
    """生成自我迭代报告"""
    lines = [
        "# 自我迭代报告",
        f"生成时间: {result['timestamp']}",
        "",
        "## 分析结果",
    ]

    suggestions = result.get("suggestions_generated", {})
    if suggestions:
        for key, value in suggestions.items():
            if isinstance(value, list):
                lines.append(f"\n### {key}")
                for item in value:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            lines.append(f"- **{k}**: {v}")
                    else:
                        lines.append(f"- {item}")

    lines.append("\n## 已应用的改进")
    for imp in result.get("improvements_applied", []):
        status = "✅ 已应用" if imp.get("applied") else "⏳ 待确认"
        lines.append(f"- {status} - {imp.get('type', '')}: {imp.get('content', '')}")

    return "\n".join(lines)


async def check_and_improve() -> dict:
    """检查并执行改进（轻量版，适合频繁调用）"""
    try:
        from core.database import get_db
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
