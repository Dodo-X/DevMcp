from devpartner_agent.core.llm_prompts._common import AnalysisTask, parse_json

def _parse_daily_summary(raw: str) -> dict:
    """日报专用解析器"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["inference_engine"] = "ollama"
    return parsed

TASK_DAILY_SUMMARY = AnalysisTask(
    name="daily_summary",
    description="每日工作总结生成（v8.0 自包含版 — MD 独立于 SQLite）",
    prompt_template="""你是一个专业的开发者工作总结 AI 助手。基于以下今日工作数据，生成结构化的日报分析。

## 今日日期
{date}

## 工作数据概览
- 对话总数: {total_conversations}
- 涉及文件数: {files_count}
- 主要任务类型: {task_types}

## 详细对话记录
{conversations}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
请生成完整的 JSON 格式日报。这份日报将被保存为 Markdown 文件，作为独立于数据库的持久化记录。
因此，所有关键数据必须完整写入，不能仅依赖数据库查询。

**重要**：SQLite 数据会在30天后逐步清理（steps详情→摘要→归档→删除），
因此日报必须包含足够完整的信息，使得未来仅凭此 MD 文件就能还原当日工作全貌。
特别是：对话中的关键技术决策、代码变更原因、问题解决思路必须完整记录。

```json
{{
  "date": "{date}",
  "summary": "一句话总结今天的主要工作成果（100字以内）",
  "experience": {{
    "deep_dive": "今天最深入的技术探索或解决的问题（300字以内，需包含具体技术细节、代码片段或配置变更）",
    "lesson": "今天学到的重要经验或教训（200字以内，需包含可操作的改进建议）"
  }},
  "skills": {{
    "new_skills": ["今天新接触或使用的技能（含具体技术名称和版本）"],
    "patterns": ["发现的模式或规律（含具体场景描述）"],
    "tools": ["使用过的工具清单（含工具名称和用途）"]
  }},
  "knowledge": {{
    "must_remember": ["必须记住的关键知识点（需完整描述，不能只写标题，含具体参数/配置/命令）"],
    "insights": ["重要洞察和发现（含推理过程和依据）"],
    "decisions": ["今日做出的关键技术决策（含决策理由和替代方案）"],
    "solutions": ["今日解决的问题（含问题现象、根因分析和解决步骤）"]
  }},
  "danger_signals": {{
    "repeated_mistakes": ["重复出现的错误（含具体错误信息和频率）"],
    "tech_debt": ["积累的技术债务（含影响范围和紧急程度）"],
    "hot_files": ["频繁修改的高风险文件（含修改次数和风险说明）"]
  }},
  "user_profile_update": {{
    "skill_changes": ["今日观察到的技能变化（如：Python从intermediate→advanced）"],
    "behavior_signals": ["今日观察到的行为特征（如：偏好TDD开发模式）"],
    "growth_direction": "基于今日数据的成长方向建议"
  }},
  "project_profile_update": {{
    "tech_changes": ["今日观察到的技术栈变化（含具体版本和引入原因）"],
    "architecture_changes": ["今日观察到的架构变化（含变更范围和影响）"],
    "business_changes": ["今日观察到的业务领域变化"]
  }},
  "tomorrow_plan": "明天最优先要完成的1-3件事",
  "self_analysis": {{
    "strengths": ["今天的优点和做得好的地方（含具体事例）"],
    "weaknesses": ["需要改进的地方（含具体改进方案）"],
    "growthSuggestions": ["具体的成长建议（含可衡量的目标）"]
  }},
  "metrics": {{
    "productivity_score": 7,
    "learning_score": 8,
    "collaboration_score": 6,
    "focus_score": 7
  }}
}}
```

注意：
1. 基于实际数据进行分析，不要编造
2. 突出重点，避免流水账
3. 所有描述必须具体完整，因为这份日报可能成为数据库清理后的唯一记录
4. user_profile_update 和 project_profile_update 需要与快照对比，标注变化
5. knowledge.decisions 和 knowledge.solutions 是最容易被遗漏的关键信息，务必完整记录
6. 只输出 JSON""",
    parser=_parse_daily_summary,
    max_tokens=3000,
    input_truncate=8000,
    feature_flag="enhance_daily_summary",
)


def _parse_weekly_report(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_weekly_report"
    return parsed

TASK_WEEKLY_REPORT = AnalysisTask(
    name="weekly_report",
    description="每周工作总结报告（v8.0 — 自包含 MD 持久化）",
    prompt_template="""你是一个专业的开发者周报分析 AI 助手。基于以下一周工作数据，生成结构化的周报。

## 报告周期
{period_start} ~ {period_end}

## 本周日报摘要
{daily_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
请生成完整的 JSON 格式周报。这份周报将被保存为 Markdown 文件，作为独立于数据库的持久化记录。

```json
{{
  "period": "{period_start} ~ {period_end}",
  "summary": "一周工作总结（200字以内，含核心成果和关键挑战）",
  "key_achievements": [
    {{"achievement": "成果描述", "impact": "影响和意义", "evidence": "支持证据"}}
  ],
  "skill_progress": {{
    "new_skills_acquired": ["本周新掌握的技能"],
    "skills_improved": ["本周提升的技能（含提升程度）"],
    "skills_to_learn": ["下周需要学习的技能"]
  }},
  "patterns_and_insights": {{
    "work_patterns": ["观察到的工作模式（如：上午编码效率最高）"],
    "recurring_issues": ["反复出现的问题（含频率和影响）"],
    "breakthroughs": ["本周的技术突破或顿悟"]
  }},
  "project_progress": {{
    "tech_stack_changes": ["技术栈变化"],
    "architecture_evolution": ["架构演进"],
    "business_growth": ["业务领域扩展"]
  }},
  "risk_assessment": {{
    "technical_risks": ["技术风险（含严重程度和缓解方案）"],
    "knowledge_gaps": ["知识盲区（含学习路径建议）"],
    "process_issues": ["流程问题（含改进建议）"]
  }},
  "next_week_plan": {{
    "priorities": ["下周最优先的3件事"],
    "learning_goals": ["学习目标"],
    "experiments": ["想尝试的新方法或工具"]
  }},
  "user_profile_delta": {{
    "changed_dimensions": ["本周用户画像变化维度"],
    "growth_trajectory": "成长轨迹描述（如：从入门到进阶的过渡期）"
  }},
  "metrics": {{
    "productivity_trend": "上升/稳定/下降",
    "learning_velocity": "加速/匀速/减速",
    "code_quality_trend": "提升/稳定/下降",
    "overall_score": 7
  }}
}}
```

注意：
1. 基于日报数据综合分析，不要简单拼接
2. 识别趋势和模式，而非罗列事实
3. 所有描述必须具体完整，MD 是独立持久化记录
4. 只输出 JSON""",
    parser=_parse_weekly_report,
    max_tokens=3000,
    input_truncate=10000,
    feature_flag="enhance_daily_summary",
)


def _parse_monthly_report(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_monthly_report"
    return parsed

TASK_MONTHLY_REPORT = AnalysisTask(
    name="monthly_report",
    description="每月工作总结报告（v8.0 — 自包含 MD 持久化）",
    prompt_template="""你是一个专业的开发者月报分析 AI 助手。基于以下一个月的工作数据，生成结构化的月报。

## 报告周期
{period_start} ~ {period_end}

## 本月周报摘要
{weekly_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
请生成完整的 JSON 格式月报。这份月报将被保存为 Markdown 文件，作为独立于数据库的持久化记录。

```json
{{
  "period": "{period_start} ~ {period_end}",
  "summary": "月度工作总结（300字以内，含核心成果、关键转折和整体评价）",
  "major_achievements": [
    {{"achievement": "重大成果", "impact": "影响和意义", "effort": "投入的时间和精力"}}
  ],
  "skill_evolution": {{
    "skills_at_start": ["月初技能水平"],
    "skills_at_end": ["月末技能水平"],
    "growth_highlights": ["最显著的成长点"],
    "learning_curve": "学习曲线描述（如：前两周缓慢，第三周突破）"
  }},
  "project_milestones": {{
    "completed": ["已完成的重要里程碑"],
    "in_progress": ["进行中的重要工作"],
    "blocked": ["受阻的工作（含原因）"]
  }},
  "patterns_and_trends": {{
    "work_rhythm": "工作节奏分析（如：周一规划+周五复盘模式）",
    "productivity_peaks": ["生产力高峰时段和原因"],
    "recurring_themes": ["反复出现的主题（如：持续优化性能）"]
  }},
  "risk_and_debt": {{
    "critical_risks": ["关键风险（含影响和缓解方案）"],
    "tech_debt_accumulated": ["累积的技术债务"],
    "knowledge_debt": ["知识欠债（需要但尚未学习的领域）"]
  }},
  "next_month_plan": {{
    "strategic_goals": ["下月战略目标（2-3个）"],
    "tactical_actions": ["具体行动项"],
    "learning_roadmap": ["学习路线图"]
  }},
  "user_profile_snapshot": {{
    "current_level": "当前综合水平",
    "growth_direction": "成长方向",
    "strengths": ["核心优势"],
    "improvement_areas": ["需要提升的领域"]
  }},
  "metrics": {{
    "overall_productivity": 7,
    "skill_growth_rate": "加速/匀速/减速",
    "project_health": "健康/注意/危险",
    "work_life_balance": "良好/一般/需调整"
  }}
}}
```

注意：
1. 月报需要宏观视角，识别趋势和转折点
2. 与周报不同，月报关注长期变化而非短期细节
3. 所有描述必须具体完整，MD 是独立持久化记录
4. 只输出 JSON""",
    parser=_parse_monthly_report,
    max_tokens=3000,
    input_truncate=12000,
    feature_flag="enhance_daily_summary",
)


# ══════════════════════════════════════════════════════════
# 系统成长分析（v8.1.0 — 月报触发，产出 growth_analysis 表数据）
# ══════════════════════════════════════════════════════════

def _parse_growth_analysis(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_growth_analysis"
    return parsed

TASK_GROWTH_ANALYSIS = AnalysisTask(
    name="growth_analysis",
    description="系统成长分析（v8.1.0 — 月报触发，识别优化机会）",
    prompt_template="""你是一个 AI 辅助成长系统优化分析师。基于以下月度工作总结数据，分析系统可以如何更好地辅助用户成长。

## 分析周期
{period_start} ~ {period_end}

## 本月周报摘要
{weekly_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
请分析系统在以下四个维度的优化机会，生成 JSON 格式的建议列表：

```json
{{
  "analyses": [
    {{
      "analysis_type": "prompt_optimize",
      "title": "优化建议标题（简洁明确）",
      "description": "发现的问题描述（基于数据支撑）",
      "suggestion": "具体的优化建议（可操作、可验证）",
      "priority": "high/medium/low",
      "related_data": {{
        "prompt_name": "关联的 Prompt 模板名称",
        "current_behavior": "当前表现",
        "expected_behavior": "期望表现"
      }}
    }}
  ]
}}
```

分析维度说明：
1. **prompt_optimize**: 分析 Prompt 模板的改进空间
   - 提取质量：是否遗漏了重要信息
   - 用户画像：是否准确捕捉用户特征变化
   - 知识提取：是否识别了新的知识领域

2. **analysis_add**: 建议新增分析维度
   - 缺少哪些维度的分析
   - 新增维度能带来什么价值

3. **knowledge_gap**: 用户知识库欠缺模块
   - 基于对话内容识别用户未掌握但需要的知识
   - 建议新增的知识模块

4. **user_profile_enhance**: 用户画像优化建议
   - 画像数据是否完整
   - 哪些维度需要补充数据

注意：
1. 每条建议必须基于实际数据，不能凭空猜测
2. 建议必须具体可操作，不能是泛泛而谈
3. 优先级要合理：high=影响核心功能，medium=明显改善，low=锦上添花
4. 只输出 JSON""",
    parser=_parse_growth_analysis,
    max_tokens=2000,
    input_truncate=10000,
    feature_flag="enhance_daily_summary",
)


def _parse_annual_report(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_annual_report"
    return parsed

TASK_ANNUAL_REPORT = AnalysisTask(
    name="annual_report",
    description="年度工作总结报告（v8.0 — 自包含 MD 持久化）",
    prompt_template="""你是一个专业的开发者年报分析 AI 助手。基于以下一年的工作数据，生成结构化的年报。

## 报告周期
{period_start} ~ {period_end}

## 本年月报摘要
{monthly_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
请生成完整的 JSON 格式年报。这份年报将被保存为 Markdown 文件，作为独立于数据库的持久化记录。

```json
{{
  "period": "{period_start} ~ {period_end}",
  "summary": "年度工作总结（500字以内，含年度主线、关键突破和整体评价）",
  "year_in_review": {{
    "defining_moments": ["年度定义性时刻（最重要的3-5个）"],
    "biggest_achievements": ["最大成就"],
    "hardest_challenges": ["最困难的挑战（含如何克服）"],
    "unexpected_discoveries": ["意外发现"]
  }},
  "skill_journey": {{
    "skills_at_year_start": ["年初技能水平"],
    "skills_at_year_end": ["年末技能水平"],
    "breakthrough_skills": ["突破性提升的技能"],
    "abandoned_skills": ["放弃或搁置的技能方向"],
    "skill_map": "技能地图描述（核心技能+辅助技能+探索中）"
  }},
  "project_portfolio": {{
    "projects_completed": ["完成的项目"],
    "projects_ongoing": ["持续进行的项目"],
    "architecture_evolution": "架构演进历程",
    "tech_stack_timeline": "技术栈变迁时间线"
  }},
  "growth_analysis": {{
    "learning_curve": "全年学习曲线描述",
    "productivity_evolution": "生产力演变",
    "decision_making_maturity": "决策成熟度变化",
    "communication_style_evolution": "沟通风格演变"
  }},
  "next_year_vision": {{
    "strategic_direction": "下一年战略方向",
    "skill_goals": ["技能目标"],
    "project_ambitions": ["项目愿景"],
    "learning_commitments": ["学习承诺"]
  }},
  "metrics": {{
    "overall_growth_score": 7,
    "technical_depth": "深入/中等/浅层",
    "breadth_of_knowledge": "广泛/适中/聚焦",
    "impact_level": "高/中/低",
    "sustainability": "可持续/需调整/不可持续"
  }}
}}
```

注意：
1. 年报需要战略视角，识别年度主线和转折点
2. 关注长期趋势和结构性变化
3. 所有描述必须具体完整，MD 是独立持久化记录
4. 只输出 JSON""",
    parser=_parse_annual_report,
    max_tokens=4000,
    input_truncate=16000,
    feature_flag="enhance_daily_summary",
)