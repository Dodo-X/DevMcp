"""
每日总结技能 v3.0 - AI-Client-Driven 数据提供
=================================================
v3.0 重大架构变更:
  - 不再调用本地 Ollama（太慢、不支持远程部署）
  - MCP 提供纯数据工具，AI客户端（CodeBuddy/Trae的LLM）自己做分析
  - AI 客户端的 LLM (Claude/GPT) 远比本地 7B 模型强大

架构:
  AI客户端 → 调用 get_daily_work_data() 获取原始数据
           → 用自己的 LLM 分析总结
           → 调用 save_daily_analysis() 保存结果

数据流向:
  daily_logs/ + SQLite DB → get_daily_work_data → AI分析 → save_daily_analysis → DB + Report
"""
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path


def get_daily_work_data(date_str: str = None, fallback_to_log: bool = True) -> dict:
    """
    获取指定日期的工作数据（供 AI 客户端分析用的原始数据）
    
    v4.1 增强：当数据库为空时，自动从本地 Markdown 日志解析数据作为降级方案
    解决"刚部署 DB 无历史数据"问题
    
    参数:
    - date_str: 日期字符串 YYYY-MM-DD
    - fallback_to_log: 是否在DB无数据时降级读取本地日志（默认True）
    
    返回:
    - 对话日志内容（Markdown）
    - 数据库中的结构化记录
    - 统计数据
    - 涉及的文件列表
    - data_source: 标识数据来源 ("db" / "local_log" / "mixed")
    
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
        "data_source": "db",
    }

    # 1. 读取日志文件（始终尝试）
    has_local_log = False
    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()
        log_data_str = log_svc.read_daily_log(date_str)
        log_data = json.loads(log_data_str) if isinstance(log_data_str, str) else log_data_str
        
        if "error" not in log_data and log_data.get("content", "").strip():
            result["log_content"] = log_data["content"]
            result["log_size_bytes"] = log_data.get("size_bytes", 0)
            has_local_log = True
    except Exception:
        pass

    # 2. 从数据库读取结构化记录
    db_has_data = False
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
        
        if convs:
            db_has_data = True
            
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

    # 3. 降级机制：DB 无数据但有本地日志时，从日志解析
    if not db_has_data and fallback_to_log and has_local_log and result["log_content"]:
        result["data_source"] = "local_log"
        parsed_convs = parse_markdown_log(result["log_content"], date_str)
        
        if parsed_convs:
            result["conversations"] = parsed_convs
            
            # 从解析的数据中提取统计信息
            task_types = {}
            for conv in parsed_convs:
                tt = conv.get("task_type", "未分类")
                task_types[tt] = task_types.get(tt, 0) + 1
                
                # 收集文件
                if conv.get("files_touched"):
                    result["files_touched"].extend(conv["files_touched"])
                
                # 收集问题和思考
                if conv.get("problems"):
                    result["problems_found"].append(conv["problems"])
                if conv.get("thinking_steps"):
                    result["thinking_data"].append({
                        "topic": conv["topic"],
                        "steps": conv["thinking_steps"],
                        "self_reflection": conv.get("self_reflection", ""),
                    })
            
            result["files_touched"] = list(set(result["files_touched"]))
            result["stats"] = {
                "date": date_str,
                "total": len(parsed_convs),
                "by_type": task_types,
            }
            result["fallback_note"] = "⚠️ 数据库暂无记录，已从本地日志文件降级读取。可调用 import_daily_log_to_db() 导入到数据库"
    
    elif db_has_data and has_local_log:
        result["data_source"] = "mixed"
    
    return result


def save_daily_analysis(analysis_json: str) -> dict:
    """
    保存 AI 客户端的分析结果
    
    analysis_json: JSON 字符串，格式如下:
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


def parse_markdown_log(log_content: str, date_str: str) -> list[dict]:
    """
    解析 Markdown 日志文件，提取结构化对话记录
    
    支持格式:
    ## HH:MM:SS - 主题
    - **任务类型**: xxx
    - **用户意图**: xxx
    - **执行操作**: xxx
    ...
    """
    conversations = []
    
    # 按 ## 分割每个条目
    entries = re.split(r'\n(?=## \d{2}:\d{2}:\d{2})', log_content)
    
    for entry in entries:
        if not entry.strip() or not entry.startswith('##'):
            continue
            
        conv = {
            "timestamp": f"{date_str}T",
            "topic": "",
            "task_type": "未分类",
            "user_intent": "",
            "actions": "",
            "problems": "",
            "solutions": "",
            "decisions": "",
            "files_touched": [],
            "thinking_steps": [],
            "self_reflection": "",
            "client": "unknown",
        }
        
        # 提取时间戳和主题
        header_match = re.match(r'## (\d{2}:\d{2}:\d{2})\s*-\s*(.+)', entry)
        if header_match:
            time_str = header_match.group(1)
            conv["timestamp"] = f"{date_str}T{time_str}"
            conv["topic"] = header_match.group(2).strip()
        
        # 提取任务类型
        task_match = re.search(r'\*\*任务类型\*\*:\s*(.+)', entry)
        if task_match:
            conv["task_type"] = task_match.group(1).strip()
        
        # 提取用户意图
        intent_match = re.search(r'\*\*用户意图\*\*:\s*(.+)', entry)
        if intent_match:
            conv["user_intent"] = intent_match.group(1).strip()
        
        # 提取执行操作
        actions_match = re.search(r'\*\*执行操作\*\*:\s*(.+)', entry)
        if actions_match:
            conv["actions"] = actions_match.group(1).strip()
        
        # 提取涉及文件
        files_match = re.search(r'\*\*涉及文件\*\*:\s*(.+)', entry)
        if files_match:
            files_str = files_match.group(1).strip()
            conv["files_touched"] = [f.strip() for f in files_str.split(',')]
        
        # 提取问题
        prob_match = re.search(r'\*\*遇到的问题\*\*:\s*(.+)', entry)
        if prob_match:
            conv["problems"] = prob_match.group(1).strip()
        
        # 提取解决方案
        sol_match = re.search(r'\*\*解决方案\*\*:\s*(.+)', entry)
        if sol_match:
            conv["solutions"] = sol_match.group(1).strip()
        
        # 提取关键决策
        dec_match = re.search(r'\*\*关键决策\*\*:\s*(.+)', entry)
        if dec_match:
            conv["decisions"] = dec_match.group(1).strip()
        
        # 提取自我反省
        reflect_match = re.search(r'### 自我反省\n(.+?)(?:\n---|\Z)', entry, re.DOTALL)
        if reflect_match:
            conv["self_reflection"] = reflect_match.group(1).strip()
        
        # 提取思考历程
        think_section = re.search(r'### 思考历程\n(.+?)(?=###|\n---|\Z)', entry, re.DOTALL)
        if think_section:
            think_text = think_section.group(1)
            steps = []
            for step_match in re.finditer(r'(\d+)\.\s*\[([^\]]+)\]\s*(.+)', think_text):
                steps.append({
                    "step": int(step_match.group(1)),
                    "phase": step_match.group(2),
                    "content": step_match.group(3).strip(),
                })
            conv["thinking_steps"] = steps
        
        conversations.append(conv)
    
    return conversations


def import_daily_log_to_db(date_str: str = None) -> dict:
    """
    将指定日期的本地 Markdown 日志导入到数据库
    
    解决"DB刚部署无数据"问题：从本地日志文件解析并灌入SQLite
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    result = {
        "date": date_str,
        "imported_count": 0,
        "skipped_count": 0,
        "errors": [],
    }
    
    try:
        from services.log_service import get_log_service
        from core.database import get_db
        
        log_svc = get_log_service()
        db = get_db()
        
        # 读取日志文件
        log_data_str = log_svc.read_daily_log(date_str)
        log_data = json.loads(log_data_str) if isinstance(log_data_str, str) else log_data_str
        
        if "error" in log_data:
            return {"success": False, "error": f"日志文件不存在: {date_str}"}
        
        log_content = log_data.get("content", "")
        if not log_content.strip():
            return {"success": False, "error": "日志文件为空"}
        
        # 解析 Markdown 日志
        conversations = parse_markdown_log(log_content, date_str)
        
        if not conversations:
            return {"success": True, "imported_count": 0, "message": "未解析到有效条目"}
        
        # 检查是否已有数据（避免重复导入）
        existing = db.query_local(
            "SELECT COUNT(*) as cnt FROM conversations WHERE date(timestamp) = ?",
            (date_str,)
        )
        existing_count = existing[0]["cnt"] if existing else 0
        
        # 导入每条记录
        for conv in conversations:
            try:
                # 检查是否已存在相同时间戳的记录
                dup_check = db.query_local(
                    "SELECT id FROM conversations WHERE timestamp = ? AND topic = ?",
                    (conv["timestamp"], conv["topic"])
                )
                if dup_check:
                    result["skipped_count"] += 1
                    continue
                
                db.insert_conversation(conv)
                result["imported_count"] += 1
            except Exception as e:
                result["errors"].append(f"导入失败 [{conv['topic']}]: {str(e)}")
        
        result["success"] = True
        result["message"] = f"成功导入 {result['imported_count']} 条记录"

        if result["skipped_count"]:
            result["message"] += f"，跳过 {result['skipped_count']} 条重复记录"
            
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
    
    return result


def sync_all_logs_to_db() -> dict:
    """
    批量同步所有本地日志到数据库
    
    扫描 daily_logs 目录下所有日志文件，逐个导入数据库
    用于首次部署或数据迁移场景
    """
    result = {
        "synced_dates": [],
        "total_imported": 0,
        "total_skipped": 0,
        "errors": [],
    }
    
    try:
        from services.log_service import get_log_service
        
        log_svc = get_log_service()
        logs = log_svc.list_logs()
        
        if not logs:
            return {"success": True, "message": "没有找到日志文件", "total_imported": 0}
        
        for log_info in logs:
            date_str = log_info["date"]
            if not date_str:
                continue
            
            import_result = import_daily_log_to_db(date_str)
            
            if import_result.get("success"):
                result["synced_dates"].append(date_str)
                result["total_imported"] += import_result.get("imported_count", 0)
                result["total_skipped"] += import_result.get("skipped_count", 0)
            else:
                result["errors"].append(f"{date_str}: {import_result.get('error', '未知错误')}")
        
        result["success"] = True
        result["message"] = f"同步完成: {len(result['synced_dates'])} 个日期 共导入 {result['total_imported']} 条记录"
        
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
    
    return result


def _generate_report_file(analysis: dict, target_date: str) -> str:
    """生成 Markdown 日报文件"""
    # 确定报告目录
    try:
        from core.config import get_config
        cfg = get_config()
        report_dir = Path(cfg.data.root_dir) / "reports"
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
        f"**深挖**: {exp.get('deep_dive', '无')}",
        "",
        f"**教训**: {exp.get('lesson', '无')}",
        "",
    ]
    
    # 技能
    new_skills = skills.get("new_skills", [])
    if new_skills:
        lines.append("## 🔧 新技能")
        for s in new_skills:
            lines.append(f"- {s}")
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
        lines.append("## 🧠 必记知识")
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
                lines.append(f"- 💸 技术债务: {t}")
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
    lines.append(f"*devPartner MCP v3.0 数据服务生成*")
    
    content = "\n".join(lines)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    return str(report_path)
