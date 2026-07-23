from backend.templates.llm_prompt._common import AnalysisTask, parse_json


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
    description="每日工作总结生成（v9.9.1 — 精简 step output_data 为4字段，聚焦人的发展复盘）",
    prompt_template="""你是一个专业的开发者工作总结 AI 助手。基于以下今日工作数据，生成结构化的日报分析。

## 今日日期
{date}

## 工作数据概览
- 对话总数: {total_conversations}
- 涉及的开发系统: {systems_active}
- 主要任务类型: {task_types}

## 详细对话记录
每个对话以 conversation 为单位组织，包含：
- topic: 对话主题
- task_type: 任务类型（debug/coding/refactoring/config/design/learning/general）
- system_id: 所属系统
- self_reflection: 用户自我反思
- user_raw_input: 用户原始输入
- conversation_steps: 步骤列表，每步含 output_data（精简为4个关键字段：step_summary、problem_solving_pattern、key_insights、improvement_suggestions）

{conversations}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
请生成完整的 JSON 格式日报。这份日报将被保存为 Markdown 文件，作为独立于数据库的持久化记录。
日报的核心价值是**对人的发展进行复盘和成长指导**，而非简单罗列操作细节。

**v9.8.3 设计原则**：
- 知识点、文件变更等精细数据由 step_analysis 独立处理并存入数据库，不需要在日报中重复
- 日报聚焦于：今天做了什么、遇到了什么困难、如何解决的、学到了什么、明天怎么改进
- project_analysis 按 system_id 分组归纳，关注项目层面的进展和决策，而非单个文件修改

```json
{{
  "date": "{date}",
  "summary": "一句话总结今天的主要工作成果（100字以内）",
  "facts": [
    "本日可量化事实1（必须带数字，如'今日 12 次对话，debug 类 7 次占 58%'）",
    "可量化事实2（如'完成 3 个模块单测，覆盖率 40%→72%'）",
    "可量化事实3（来自步骤统计：成功 X / 失败 Y）"
  ],
  "experience": {{
    "deep_dive": "今天最深入的技术探索或解决的问题（300字以内，需包含具体技术细节和思考过程）",
    "lesson": "今天学到的重要经验或教训（200字以内，需包含可操作的改进建议）"
  }},
  "skills": {{
    "patterns": ["发现的模式或规律（含具体场景描述）"]
  }},
  "knowledge": {{
    "insights": ["重要洞察和发现（含推理过程和依据）"],
    "decisions": ["今日做出的关键技术决策（含决策理由和替代方案）"],
    "solutions": ["今日解决的问题（含问题现象、根因分析和解决步骤）"]
  }},
  "project_analysis": {{
    "projects": [
      {{
        "project_name": "项目名（从 system_id 获取，如 devPartner、toptown-settlement）",
        "work_summary": "该项目今天的主要工作内容（100字以内）",
        "bugs_found": [
          {{
            "category": "Bug分类（编码错误/逻辑缺陷/配置问题/性能问题/兼容性问题/安全问题）",
            "description": "Bug现象描述",
            "root_cause": "根因分析",
            "solution": "解决方案"
          }}
        ],
        "bugs_fixed": [
          {{
            "description": "已修复的Bug描述",
            "solution": "修复方案"
          }}
        ],
        "decisions": ["该项目相关的技术决策及理由"]
      }}
    ]
  }},
  "danger_signals": {{
    "repeated_mistakes": ["重复出现的错误（含具体错误信息和频率）"],
    "tech_debt": ["积累的技术债务（含影响范围和紧急程度）"]
  }},
  "user_profile_update": {{
    "behavior_signals": ["今日观察到的行为特征（如：偏好TDD开发模式）"],
    "growth_direction": "基于今日数据的成长方向建议"
  }},
  "project_profile_update": {{
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
    "productivity_score": {{"score": 7, "evidence": "今日完成的核心产出（引用 facts 中的真实数字）"}},
    "learning_score": {{"score": 8, "evidence": "今日学到/应用的具体技能（引用 facts）"}},
    "collaboration_score": {{"score": 6, "evidence": "今日协作对齐的具体事例"}},
    "focus_score": {{"score": 7, "evidence": "今日深度专注的具体表现"}}
  }},
  "psychology": {{
    "frustration_level": 2,
    "flow_signals": ["进入心流的具体时刻/任务（如'重构模块时连续 2h 无打断'）"],
    "decision_style": "今日主要决策风格（如'先全量扫描再定位'/'遇到不确定先小步验证'）",
    "recurring_blockers": ["今日反复出现的阻塞点（如'回调超时''环境配置'）"]
  }}
}}
```

注意：
1. 基于实际数据进行分析，不要编造；facts 必须带真实数字，每条都能在对话/步骤数据中找到依据
2. metrics 每项必须含 evidence，evidence 必须引用 facts 中的真实数字（禁止凭感觉打分）
3. psychology 是基于今日数据的推断，区分"事实信号"与"推测"；frustration_level 为 1-5 整数
4. 突出重点，避免流水账——日报的价值在于复盘和成长，不是操作日志
5. 知识点和文件变更已由 step_analysis 独立处理，日报不需要重复这些精细数据
6. user_profile_update 和 project_profile_update 需要与快照对比，标注变化
7. knowledge.decisions 和 knowledge.solutions 是最容易被遗漏的关键信息，务必完整记录
8. project_analysis 按 system_id 分组归纳，system_id 为空的归入"通用/未分类"
9. 只输出 JSON，无数据字段留空（用空字符串/空数组），禁止虚构细节""",
    parser=_parse_daily_summary,
    max_tokens=4000,
    input_truncate=8000,
    feature_flag="enhance_daily_summary",
)
