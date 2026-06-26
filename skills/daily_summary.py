"""
每日总结技能 v3.0 — AI-Client-Driven 数据提供
=================================================
v3.0 重大架构变更：
  - ❌ 不再调用本地 Ollama（太慢、不支持远程部署）
  - ✅ MCP 提供纯数据工具，AI客户端（CodeBuddy/Trae的LLM）自己做分析
  - ✅ AI 客户端的 LLM (Claude/GPT) 远比本地 7B 模型强大

架构：
  AI客户端 → 调用 get_daily_work_data() 获取原始数据
           → 用自己的 LLM 分析总结
           → 调用 save_daily_analysis() 保存结果

数据流向：
  daily_logs/ + SQLite DB → get_daily_work_data → AI分析 → save_daily_analysis → DB + Report
"""
import json
import os
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional


def get_daily_work_data(date_str: str = None) -> dict:
    """
    获取指定日期的工作数据（给 AI 客户端分析用的原始数据）
    
    返回：
    - 对话日志内容（Markdown）
    - 数据库中的结构化记录
    - 统计数据
    - 涉及的文件列表
    
    AI客户端拿到这些数据后用自己的LLM分析总结
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    result = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "log_content": "",
        "conversations": [],
        "stats": {},
        "files_touched": [],
        "problems_found": [],
        "thinking_data": [],
    }

    # 1. 读取日志文件
    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()
        log_data_str = log_svc.read_daily_log(date_str)
        log_data = json.loads(log_data_str) if isinstance(log_data_str, str) else log_data_str
        result["log_content"] = log_data.get("content", "")
        result["log_size_bytes"] = log_data.get("size_bytes", 0)
    except Exception:
        pass

    # 2. 从数据库读取结构化记录
    try:
        from core.database import get_db
        db = get_db()

        # 对话记录
        convs = db.query_local(
            """SELECT * FROM conversations 
               WHERE date(timestamp) = ? 
               ORDER BY timestamp ASC""",
            (date_str,)
        )
        for c in convs:
            entry = {
                "timestamp": c.get("timestamp", ""),
                "topic": c.get("topic", ""),
                "task_type": c.get("task_type", ""),
                "user_intent": c.get("user_intent", ""),
                "actions": c.get("actions", ""),
                "problems": c.get("problems", ""),
                "solutions": c.get("solutions", ""),
                "decisions": c.get("decisions", ""),
                "self_reflection": c.get("self_reflection", ""),
                "client": c.get("client", "unknown"),
            }
            # 解析 JSON 字段
            try:
                files = json.loads(c.get("files_touched", "[]"))
                entry["files_touched"] = files
                result["files_touched"].extend(files)
            except (json.JSONDecodeError, TypeError):
                entry["files_touched"] = []

            try:
                thinking = json.loads(c.get("thinking_steps", "[]"))
                entry["thinking_steps"] = thinking
                if thinking:
                    result["thinking_data"].append({
                        "topic": entry["topic"],
                        "steps": thinking,
                        "self_reflection": entry["self_reflection"],
                    })
            except (json.JSONDecodeError, TypeError):
                entry["thinking_steps"] = []

            if entry["problems"]:
                result["problems_found"].append(entry["problems"])
            if entry["solutions"]:
                if result["problems_found"]:
                    result["problems_found"][-1] += f" → 解决: {entry['solutions']}"

            result["conversations"].append(entry)

        # 去重文件列表
        result["files_touched"] = list(set(result["files_touched"]))

        # 统计
        result["stats"] = db.get_daily_stats(date_str)

        # 检查跨AI对话
        try:
            from core.database import get_db
            dialogue_data = db.query_local(
                "SELECT * FROM conversations WHERE date(timestamp) = ? AND client != 'unknown'",
                (date_str,)
            )
            clients = set(c.get("client", "") for c in dialogue_data)
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
        from core.database import get_db
        db = get_db()

        timestamp = datetime.now().isoformat()
        db.query_local(
            """INSERT INTO conversations
               (timestamp, topic, task_type, user_intent, actions, raw_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (timestamp, "每日总结",
             "daily_summary",
             f"AI客户端生成 {target_date} 工作总结",
             "AI分析 + 生成日报",
             json.dumps(analysis, ensure_ascii=False)),
        )
        result["steps"].append({"step": "save_to_local_db", "status": "ok"})
    except Exception as e:
        result["steps"].append({"step": "save_to_local_db", "status": "error", "error": str(e)})

    # 2. 保存到共享数据库（如果可用）
    try:
        from core.database import get_db
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
            from core.database import get_db
            db = get_db()
            db.query_local(
                """INSERT INTO system_improvements
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

    # 4. 生成 Markdown 报告
    try:
        report_path = _generate_report_file(analysis, target_date)
        result["report_path"] = report_path
        result["steps"].append({"step": "generate_report", "status": "ok"})
    except Exception as e:
        result["steps"].append({"step": "generate_report", "status": "error", "error": str(e)})

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
            from core.database import get_db
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


def _generate_report_file(analysis: dict, target_date: str) -> str:
    """生成 Markdown 日报文件"""
    # 确定报告目录
    try:
        from core.config import get_config
        cfg = get_config()
        report_dir = Path(cfg.database.report_dir)
    except Exception:
        report_dir = Path("data/reports")
    
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"daily_report_{target_date}.md"
    
    exp = analysis.get("experience", {})
    skills = analysis.get("skills", {})
    knowledge = analysis.get("knowledge", {})
    danger = analysis.get("danger_signals", {})
    self_a = analysis.get("self_analysis", {})
    
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        weekday = weekdays[dt.weekday()]
    except ValueError:
        weekday = ""
    
    lines = [
        f"# 📋 每日工作总结 - {target_date} {weekday}",
        "",
        f"> 🤖 由 AI 客户端分析生成 | 数据来源: devPartner MCP",
        "",
        f"## 📌 概要",
        f"",
        f"> {analysis.get('summary', '无')}",
        "",
        "## 💎 经验凝练",
        "",
        f"**深挖：** {exp.get('deep_dive', '无')}",
        "",
        f"**教训：** {exp.get('lesson', '无')}",
        "",
    ]
    
    # 技能
    new_skills = skills.get("new_skills", [])
    if new_skills:
        lines.append("## 🔧 新技能")
        for s in new_skills:
            lines.append(f"- ✅ {s}")
        lines.append("")
    
    patterns = skills.get("patterns", [])
    if patterns:
        lines.append("## 📐 可复用模式")
        for p in patterns:
            lines.append(f"- 🔄 {p}")
        lines.append("")
    
    # 知识
    must_know = knowledge.get("must_remember", [])
    if must_know:
        lines.append("## 🧠 必记知识点")
        for k in must_know:
            lines.append(f"- 💡 {k}")
        lines.append("")
    
    # 危险信号
    repeated = danger.get("repeated_mistakes", [])
    tech_debt = danger.get("tech_debt", [])
    hot_files = danger.get("hot_files", [])
    
    if repeated or tech_debt or hot_files:
        lines.append("## ⚠️ 危险信号")
        if repeated:
            for r in repeated:
                lines.append(f"- 🔄 重复踩坑: {r}")
        if tech_debt:
            for t in tech_debt:
                lines.append(f"- 💸 技术债: {t}")
        if hot_files:
            for h in hot_files:
                lines.append(f"- 📄 高频文件: `{h}`")
        lines.append("")
    
    # 明日计划
    lines.append("## 🎯 明日行动")
    lines.append(f"> {analysis.get('tomorrow_plan', '持续精进')}")
    lines.append("")
    
    # 自我分析
    strengths = self_a.get("strengths", [])
    weaknesses = self_a.get("weaknesses", [])
    suggestions = self_a.get("growth_suggestions", [])
    
    if strengths or weaknesses:
        lines.append("## 🪞 自我认知")
        for s in strengths:
            lines.append(f"- 💪 优势: {s}")
        for w in weaknesses:
            lines.append(f"- 🎓 待加强: {w}")
        for s in suggestions:
            lines.append(f"- 🚀 建议: {s}")
        lines.append("")
    
    lines.append("---")
    lines.append(f"*由 devPartner MCP v3.0 数据服务生成*")
    
    content = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return str(report_path)
