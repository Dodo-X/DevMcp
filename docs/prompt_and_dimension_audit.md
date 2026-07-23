# DevPartner 报告体系审查：数据可分析性 + Prompt 优化 + 维度覆盖

> 审查目标：在你**现有框架**内回答三件事
> 1. 已存数据能分析出什么有用的东西
> 2. prompt 该怎么优化，让 LLM 给出决策有用的数据
> 3. 你想要的分析维度（心理/画像/对话内容），当前数据够不够、缺什么、怎么分析
>
> 范围声明：本文**不新建分析体系**，只审查现有 `backend/templates/llm_prompt/` + `backend/business/vault_export/` + SQLite 数据底座。

---

## 0. 你的真实框架（先对齐认知）

```
捕捉对话 → record_dialogue 入库(SQLite)
日报:   get_daily_work_data() 取库 → llm.generate_daily_summary()(TASK_DAILY_SUMMARY) → export_daily_report → Calendar/{date}.md
周报:   读 Calendar/*.md + 画像快照 → run_analysis(TASK_WEEKLY_REPORT) → Reports/Weekly/*.md   ← ❌ prompt 不存在
月报:   读 Reports/Weekly/*.md → run_analysis(TASK_MONTHLY_REPORT) → Reports/Monthly/*.md       ← ❌ prompt 不存在
年报:   读 Reports/Monthly/*.md → run_analysis(TASK_ANNUAL_REPORT) → Reports/Annual/*.md        ← ❌ prompt 不存在
成长:   月报后 → run_analysis(TASK_GROWTH_ANALYSIS) → growth_analysis 表                         ← ❌ prompt 不存在
```

**关键事实**：只有 `TASK_DAILY_SUMMARY` 真实存在且可用。周/月/年/成长 4 个 prompt 在架构迁移时被从 `llm_prompt/__init__.py` 移除、从未补回，`reports.py` 运行时 `from ... import TASK_WEEKLY_REPORT` 直接 `ImportError`。

---

## 1. 为什么报告"不够深入"（根因）

| # | 根因 | 证据 | 影响 |
|---|------|------|------|
| R1 | **长周期报告 prompt 缺失** | `llm_prompt/__init__.py` 注释明示已移除；本机验证 4 个 TASK_*_REPORT 均 `hasattr=False` | 周/月/年/成长报告生成即崩溃，等于只有日记式日报 |
| R2 | **日报输出全是自由文本，无量化锚点** | `TASK_DAILY_SUMMARY` 要求 deep_dive/lesson/insights/decisions… 全为散文字段；metrics 是 LLM 拍脑袋 1–10 分 | LLM 写散文、易流水账、无数据做支撑，无法决策 |
| R3 | **日报分数不落库** | grep 全仓无任何 `INSERT ... metrics/productivity_score` | 量化信号锁死在 MD 文本，DB 查不到、无法趋势/环比/聚合 |
| R4 | **口径未归一（存量数据）** | `task_type`: debug(14)/debugging(2)；refactoring(34)/code_change(3)/coding(2)；`system_id`: devPartner(60)/devpartner(1)；`domain`: Python/Python 编程/Python编程 同义 | 分布类指标被污染，聚合失真 |
| R5 | **埋点缺失** | `knowledge_points.usage_count` 82 行**全 0**；`task_queue` 运行库缺 `created_at`（仅 `queued_at`，schema 漂移） | 知识复用率/任务吞吐趋势无法度量 |

> R1 是"浅"的**主因**：你以为有多级报告，实际只有日报在跑，且日报还是散文式。

---

## 2. 你的数据到底能分析出什么（8 类，均基于真实库）

| 类 | 数据源（真实字段） | 能挖出的有用信息 | 当前限制 |
|----|--------------------|------------------|----------|
| **活跃度** | `conversations.timestamp`(61行) | 日/周对话量趋势、工作节奏 | 数据仅 07-03~07-22，跨度短 |
| **任务结构** | `conversations.task_type` | 任务类型分布（debug/refactor/learning…），识别主战场 | 需先做同义词归一（R4） |
| **系统覆盖** | `conversations.system_id` | 在哪些项目/系统上工作 | `devPartner` vs `devpartner` 大小写分裂 |
| **执行可靠性** | `conversation_steps.status`(96) / `error_message` | 步骤成功率、真实错误率（排除 duplicate_discarded 后） | `duplicate_discarded` 197 条需剥离口径 |
| **效率** | `conversation_steps.duration_ms` | 步骤耗时中位数/分位（抗偏态） | 部分行为空，需非空率校验 |
| **知识沉淀** | `knowledge_points.category/domain/type`(82) | 领域/类别分布、知识增长曲线 | `usage_count` 全 0 → 复用率失明（R5） |
| **心理/复盘** | `self_reflection`(60%有值) / `user_intent`(85%) / `topic`(100%) | 复盘率、意图清晰度、受挫/心流信号（词典法） | 无结构化标签列，只能 LLM 现提；25/61 空 |
| **画像/成长** | `user_profile`(5维) / `user_skills`(7) / `user_skill_plan`(33) | 成长势能（trend 聚合）、技能演进、学习计划完成度 | skill_plan 完成率 0%；画像更新依赖 finalize 子任务 |

**最重要的一条**：你已有结构化的**用户画像三层数据**（`user_profile` 带 trend/confidence/evidence、`user_skills` 带 growth_trend、`user_skill_plan` 33 条），这是做"心理+画像"分析最扎实的地基——比日报散文可靠得多。

---

## 3. 维度覆盖矩阵（你想要的：心理 / 画像 / 对话内容）

### 3.1 用户心理（受挫/心流/决策风格/风险信号）
| 项 | 现有数据 | 够不够 | 缺口 | 怎么分析 |
|----|----------|--------|------|----------|
| 文本原料 | `self_reflection`(60%)、`user_intent`(85%)、`topic`(100%) | 原料够 | 无结构化标签列；25/61 空 | 在日报 prompt 增"心理信号提取"段，要求输出结构化 JSON（`frustration_level` 1–5 / `flow_signals` / `decision_style` / `recurring_blockers`），并落库（新表 `conversation_psychology` 或合并进 `user_profile`） |
| 决策风格 | `user_profile.communication_style=详细型`、`problem_solving=systematic_analysis` | 已有结构化 | 维度少 | 持续在 finalize 中更新 `user_profile` 的 trend |
| 风险信号 | 日报 `danger_signals`（仅散文） | 不够 | 未结构化、不落库 | 同上，要求结构化输出 + 落库 |

### 3.2 用户画像（技能/成长/协作偏好）
| 项 | 现有数据 | 够不够 | 缺口 | 怎么分析 |
|----|----------|--------|------|----------|
| 技能树 | `user_skills`(7) 带 level/growth_trend/confidence | 够 | — | 直接做技能演进曲线 |
| 成长势能 | `user_profile` 的 trend(rising/stable) | 够 | 需聚合 | 统计 rising 维度占比 = 成长势能 |
| 学习计划 | `user_skill_plan`(33) 带 current_progress/status | 够（结构） | 完成率 0% → 计划没被跟踪 | 计算 completed/(completed+active) 完成率；驱动 weekly prompt 追问进度 |
| 协作偏好 | `user_profile.communication_style` | 够 | 维度少 | 扩展维度（如 feedback_style） |

### 3.3 对话内容分析
| 项 | 现有数据 | 够不够 | 缺口 | 怎么分析 |
|----|----------|--------|------|----------|
| 主题/意图 | `topic`(100%) / `user_intent`(85%) | 够 | — | 主题聚类、意图分布 |
| 复杂度 | `complexity`（10/61 空） | 不够 | 采集缺口 | 补齐采集；或用语义估算 |
| 步骤质量 | `conversation_steps.output_data` 4 字段(step_summary/problem_solving_pattern/key_insights/improvement_suggestions) | 够 | 仅存 DB，日报未充分利用 | 日报 prompt 要求引用具体 step 的 insights |
| 任务类型 | `task_type` | 不够（口径乱） | 同义词未归一 | 先跑归一映射再分析 |

**结论**：你想要的"心理/画像/对话内容"三大维度，**结构化数据基本够**（尤其画像），缺的是：①把心理信号从"散文"变成"结构化可落库字段"；②task_type 归一；③日报分数落库。都不需要新建大体系，是在现有框架内补采集+补 prompt。

---

## 4. Prompt 优化方案（在 `llm_prompt/` 框架内）

### 4.1 日报 `TASK_DAILY_SUMMARY` 的 5 处关键改进

现状问题：输出几乎全自由文本 → LLM 写散文；metrics 无依据；心理信号不结构化；分数不落库。

改进原则（改 `daily_summary.py` 的 `prompt_template`）：

1. **强制事实锚定**：在输出 JSON 前，要求 LLM 先输出 `facts`（本日可量化事实：对话数、各 task_type 计数、步骤成功/失败数），再叙述。杜绝编造。
2. **分数必须带证据**：`metrics` 每项改为 `{score, evidence}`，evidence 必须引用 `facts` 中的真实数字。
3. **结构化心理信号**：新增 `psychology` 段 → `frustration_level`(1–5)、`flow_signals[]`、`decision_style`、`recurring_blockers[]`，可直接落库/供 Obsidian 查询。
4. **user_profile_update 对齐表结构**：输出 `dimension/value/trend/confidence`，与 `user_profile` 表一一对应，便于 finalize 落库。
5. **显式拒编**：prompt 末尾加"无数据则留空，禁止虚构细节"。

> 注意：4.1 的 `psychology` 与 `metrics.evidence` 若要落库，需在 `vault_export` 之外增加一步"日报结构化字段入库"（现有 daily_summary 只 export MD）。这是最小新增点，非另起体系。

### 4.2 必须补全的 4 个缺失 prompt（让框架真正跑起来）

`reports.py` 需要以下 4 个对象，目前缺失。建议新建 `backend/templates/llm_prompt/reports_prompts.py` 定义它们，并在 `__init__.py` 注册。它们的设计要点：

- **`TASK_WEEKLY_REPORT`**：输入=本周 7 篇日报 MD + 画像快照；要求输出**聚合+环比(WoW)**，metrics 带 `current/prev/delta`；心理维度输出本周 `frustration_trend`、`recurring_blockers_top3`；结构对齐 `md_templates.py` 里 weekly_report 的 section（key_achievements / skill_progress / risk_assessment / next_week_plan / metrics）。
- **`TASK_MONTHLY_REPORT`**：输入=本月周报 MD；输出**月环比(MoM)** + 技能演进（skills_at_start→skills_at_end）+ 风险与债务；触发 `_run_growth_analysis`。
- **`TASK_ANNUAL_REPORT`**：输入=本年各月报；输出年度回顾 + 技能旅程 + 成长分析（学习曲线/决策成熟度演变）。
- **`TASK_GROWTH_ANALYSIS`**：双维度（system_analyses / user_analyses），输出 `analysis_type/title/description/suggestion/related_skills/trend_keywords/expected_effect/priority`，写入 `growth_analysis` 表。

> 这 4 个 prompt 的**完整模板文本**见本文附录 A（可直接落到 `reports_prompts.py`）。

### 4.3 Obsidian 对接已具备，只需补 frontmatter 字段
`md_templates.py` 已有 YAML frontmatter（`type/date/projects/engine` 等）与 `[[wikilink]]`。要让 Dataview 查到心理/分数，只需在 `_daily_fm` 等 builder 里**加字段**（如 `frustration`、`productivity_score`、`tags`），无需改架构。

---

## 5. 建议的落地顺序（最小改动、基于现有框架）

| 阶段 | 动作 | 改动文件 | 产出 |
|------|------|----------|------|
| P0(必修) | 补全 4 个缺失 prompt + 注册 | 新建 `llm_prompt/reports_prompts.py`，改 `__init__.py` | 周/月/年/成长报告能生成 |
| P1 | 日报 prompt 增加 facts/psychology/evidence | 改 `llm_prompt/daily_summary.py` | 日报从散文变可量化+结构化心理 |
| P1 | 日报结构化字段落库 | 改 `daily_summary.py` 的 export 或 finalize | 分数/心理可聚合趋势 |
| P2 | task_type / domain / system_id 归一 | 复用此前 `registry.py` 的映射，在入库或查询时套用 | 分布指标可信 |
| P2 | frontmatter 加查询字段 | 改 `md_templates.py` 的 `_*_fm` | Dataview 可查心理/分数 |
| P3 | 补埋点：usage_count、task_queue.created_at | 改采集层 | 复用率/吞吐趋势可度量 |

---

## 附录 A：缺失的 4 个 prompt 完整模板（待你确认后落入 `reports_prompts.py`）

> 以下为可直接落地的模板骨架。设计遵循现有 `AnalysisTask` 接口（`name/description/prompt_template/parser/max_tokens/input_truncate/feature_flag`）。

### A.1 TASK_WEEKLY_REPORT
```python
TASK_WEEKLY_REPORT = AnalysisTask(
    name="weekly_report",
    description="周报生成（聚合本周日报 + 环比 WoW，含心理/画像维度）",
    prompt_template="""你是开发者成长分析师。基于本周({period_start}~{period_end})的日报与用户/项目画像，生成结构化周报。

## 输入
- 本周日报（已含 facts/psychology/metrics）：
{daily_summaries}
- 用户画像快照：
{user_profile_snapshot}
- 项目画像快照：
{project_profile_snapshot}

## 输出要求（JSON）
1. 先基于日报中的 facts 计算本周聚合（对话总数、任务类型分布、步骤成功率、平均耗时）。
2. 与上周对比给出 WoW（周环比），metrics 每项含 current/prev/delta_pct。
3. 心理维度：本周 frustration_trend（升/平/降）、recurring_blockers_top3（重复阻塞点）。
4. 画像维度：本周技能进展（new_skills_acquired/skills_improved/skills_to_learn）。
5. 风险：technical_risks/knowledge_gaps/process_issues。
6. 下周计划：priorities/learning_goals/experiments。
7. 禁止虚构；无数据字段留空。

{{
  "summary": "本周一句话总结",
  "key_achievements": ["..."],
  "skill_progress": {{"new_skills_acquired":[...],"skills_improved":[...],"skills_to_learn":[...]}},
  "risk_assessment": {{"technical_risks":[...],"knowledge_gaps":[...],"process_issues":[...]}},
  "next_week_plan": {{"priorities":[...],"learning_goals":[...],"experiments":[...]}},
  "psychology": {{"frustration_trend":"降/平/升","recurring_blockers_top3":[...]}},
  "metrics": {{
    "productivity_trend": {{"current":0,"prev":0,"delta_pct":0}},
    "learning_velocity": {{"current":0,"prev":0,"delta_pct":0}},
    "code_quality_trend": {{"current":0,"prev":0,"delta_pct":0}},
    "overall_score": {{"current":0,"prev":0,"delta_pct":0}}
  }}
}}""",
    parser=_parse_weekly,
    max_tokens=3000,
    input_truncate=8000,
    feature_flag="enhance_weekly_report",
)
```

### A.2 TASK_MONTHLY_REPORT / TASK_ANNUAL_REPORT / TASK_GROWTH_ANALYSIS
（结构同 A.1，差异：月报输入为周报、输出含 skills_at_start→skills_at_end 与 MoM；年报输入为月报、含技能旅程与成长分析；成长分析输出双维度 system_analyses/user_analyses 写入 growth_analysis 表。完整文本可在此基础上扩展，确认后一并交付。）

---

## 附：本文基于的真实证据
- 代码：`backend/business/task_handlers/{daily_summary,reports}.py`、`backend/templates/llm_prompt/{__init__,daily_summary}.py`、`backend/business/vault_export/md_templates.py`
- 数据：`data/databases/devpartner.db`（conversations 61 / steps 96 / knowledge_points 82 / task_queue 363 / user_profile 5 / user_skills 7 / user_skill_plan 33）
- 运行验证：`hasattr(llm_prompt, TASK_WEEKLY_REPORT)` = False（4 个均缺失）；`TASK_DAILY_SUMMARY` 存在
