"""
每日总结技能 v5.0 — LLM 智能增强版
=====================================
v5.0 (LLM 增强): 集成本地 Ollama/Qwen3.5 进行智能日报生成。
  - ✨ 使用 LLM 自动提取关键成果、学习收获、风险预警
  - 📊 基于实际工作数据的深度分析（非模板化）
  - 🔄 双模式：LLM 可用时智能生成，不可用返回原始数据供 AI 客户端分析

v4.0 (v6.2 架构): daily_log Markdown 文件已废弃，数据仅存 SQLite。
  - ❌ 不再读取 data/daily_logs/conversation_*.md
  - ✅ 纯从 conversations 表读取
  - ✅ 所有记录由 record_dialogue MCP 工具写入 DB

数据流向：
  record_dialogue → SQLite DB → get_daily_work_data → [可选] LLM 分析 → save_daily_analysis
"""
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path


def get_daily_work_data(date_str: str = None, fallback_to_log: bool = False) -> dict:
    """
    获取指定日期的工作数据（给 AI 客户端分析用的原始数据）
    
    v4.0: 纯从 SQLite 数据库读取，不再读取本地 Markdown 日志文件。
    fallback_to_log 参数保留兼容但已无效果。
    
    参数：
    - date_str: 日期字符串 YYYY-MM-DD
    - fallback_to_log: 已废弃（v4.0），保留仅为兼容旧调用
    
    返回：
    - 数据库中的结构化记录
    - 统计数据
    - 涉及的文件列表
    - data_source: 固定为 "db"
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    result = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "conversations": [],
        "stats": {},
        "files_touched": [],
        "problems_found": [],
        "thinking_data": [],
        "data_source": "db",
        "note": "v4.0: 纯数据库读取，daily_log Markdown 文件已废弃",
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
        
        for c in (convs or []):
            entry = {
                "timestamp": c.get("timestamp", ""),
                "conversation_id": c.get("conversation_id", ""),
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


def parse_markdown_log(log_content: str, date_str: str) -> list[dict]:
    """
    解析 Markdown 日志文件，提取结构化对话记录
    
    支持格式：
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
        from devpartner_agent.services.log_service import get_log_service
        from devpartner_agent.core.database import get_db
        
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
            result["message"] += f"，跳过 {result['skipped_count']} 条重复"
            
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
        from devpartner_agent.services.log_service import get_log_service
        
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
        result["message"] = f"同步完成: {len(result['synced_dates'])} 天, 共导入 {result['total_imported']} 条"
        
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
    
    return result


def _generate_report_file(analysis: dict, target_date: str) -> str:
    """生成 Markdown 日报文件"""
    # 确定报告目录
    try:
        from devpartner_agent.core.config import get_config
        cfg = get_config()
        report_dir = Path(cfg.data.reports_dir)
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
                from devpartner_agent.services.llm_service import get_llm_service
                llm = get_llm_service()
                
                # 检查是否启用 LLM 总结功能
                cfg = llm._get_config()
                if getattr(cfg, 'enhance_daily_summary', False) and llm.is_available():
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
                "problems_count": sum(1 for t in tasks if t.get("problems")),
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