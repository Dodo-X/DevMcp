# P0 修复完成：长周期报告（周/月/年/成长）真正可生成

## 根因（为什么报告"浅"、长周期报告跑不起来）
架构迁移时 `llm_prompt/__init__.py` 删除了 `TASK_WEEKLY_REPORT / TASK_MONTHLY_REPORT / TASK_ANNUAL_REPORT / TASK_GROWTH_ANALYSIS` 且未补回。
`reports.py` 运行时 `from ... import TASK_WEEKLY_REPORT` 直接 **ImportError** → 周/月/年/成长报告根本不生成，只有日记式日报在跑。
同时发现第二层系统性 bug：`MdAssembler.assemble()` 把整个 `report_data` dict 作为 `value` 传给 renderer，但多数 renderer 原期望子字段直接传入 → 嵌套 section（成果/技能/指标/心理/事实锚点）被静默跳过，报告更"空"。

## 改动（全部基于现有框架，未引入平行体系）
| 文件 | 改动 |
|------|------|
| `backend/templates/llm_prompt/reports_prompts.py`（新建） | 4 个 `AnalysisTask`：结构化 JSON 输出，新增 `facts`（3-8 条带数字的可量化事实）与 `psychology`（情绪走向/反复卡点/成长思维/沟通风格，要求区分事实与推测）。`feature_flag` 对齐 config 的 enhance_* 开关 |
| `backend/templates/llm_prompt/__init__.py` | 导入 4 常量 + 加 v9.10.1 注释 + 注册进 `TASK_REGISTRY` |
| `backend/business/vault_export/md_templates.py` | 周/月/年报各加 `## 📊 事实锚点` 与 `## 🧠 心理与协作信号` 两 section（带 condition） |
| `backend/business/vault_export/md_engine.py` | 修复 renderer 嵌套字段 bug：`render_text/render_achievements/render_project_dimension` 在 value 为 dict 时取子字段；`render_kv` 加 `_resolve()` 下钻一层；新增 `render_psychology` |

## 验证（端到端，全绿）
- 4 个 prompt 用 `reports.py` 实际传入的 kwargs 跑 `.format()` —— 占位符完全对齐，无 MissingPlaceholder。
- `MdAssembler.register_all()` + `assemble()`：周/月/年报均渲染出 **事实锚点** + **心理与协作信号**（真实内容可见，非空白）。
- `reports.py` 导入干净，3 个 generator（`generate_weekly/monthly/annual_report`）+ `_run_growth_analysis` 均在 —— 原 ImportError 已消除。

## 关键渲染契约（后续改 md 渲染务必记住）
`assemble()` 对每个 section：`value = data.get(sec.key)`，section 的 `key` 多为 `"report_data"`，故 renderer 收到的 `value` 是**整个 LLM 结果 dict**，renderer 必须自己取子字段（render_kv 用 `_resolve` 下钻一层，render_psychology 取 `.psychology`）。
top-level `data` 需含 `period_start/period_end/report_data`（年报用 `year/report_data`）。

## 下一步（P1，待你确认，未动代码）
1. 改 `TASK_DAILY_SUMMARY` 增 `facts/psychology/evidence`；
2. 日报结构化字段落库（当前仅渲染进 MD，全仓无对应 INSERT，无法聚合/环比）；
3. `md_templates._*_fm` 加 frontmatter 查询字段，供 Obsidian Dataview。
维度治理（task_type/domain/system_id 归一、usage_count 全 0、task_queue 缺 created_at）属独立数据治理项。
