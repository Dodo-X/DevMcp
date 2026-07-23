# DevPartner 分析流水线审计 v2 — 修正方案

> 2026-07-21 | 用户确认后版本

---

## 一、最终结论：按数据可得性划分职责

### 原则

**每层只分析"当前可得数据"能支撑的维度，不盲目割舍，也不做空对空分析。**

| 分析项 | 需要的数据 | 数据可得时机 | 归属 |
|--------|-----------|-------------|------|
| 知识点提取 | step content + ai_reasoning + commands | 单步 | **Step (L0)** ✅ |
| 技能领域标注 | step content + ai_reasoning | 单步 | **Step (L0)** ✅ |
| 命令记录 | step commands_executed | 单步 | **Step (L0)** ✅ |
| **解题模式推理** | step content + ai_reasoning + symptom/root_cause/solution | **单步** | **Step (L0)** ✅ 保留 |
| 关键洞察 | step ai_reasoning + content | 单步 | **Step (L0)** ✅ |
| 改进建议 | step ai_reasoning + content | 单步 | **Step (L0)** ✅ |
| 思维模式 | step ai_reasoning | 单步 | **Step (L0)** ✅ |
| **技术决策链** | 多个 step 的完整数据 + L0 结果 | 全对话 | **Finalize (L1)** ✅ |
| **知识图谱** | 多个 step 的 L0 知识点关联 | 全对话 | **Finalize (L1)** ✅ |
| **业务知识** | 全对话 + system_id + 项目上下文 | 全对话 | **Finalize (L1)** ✅ |
| **整体评估** | 全对话 + ai_summary | 全对话 | **Finalize (L1)** ✅ |
| **用户画像 9 维** | user_raw_input + ai_analysis + 跨天数据 | 全对话 + 跨天 | **Finalize (L1) + 日报合并** ✅ |

### 用户确认的调整

1. ✅ **Step 保留解题模式推理** — 单步的 content + ai_reasoning 足以分析出解题思路
2. ✅ **用户画像保留在 deep_analysis 中** — 从 user_raw_input 提取初始画像，日报 merge 精炼
3. ✅ **deep_analysis 整体不变** — 四维分析结构保留（业务知识+用户画像+技术决策+知识图谱）
4. ✅ **L0 skill_domains 产出，L1 聚合** — 不重复推断

---

## 二、当前代码中需要修复的问题

### P0-1: steps_summary 传递数据严重不足

**文件**: `conversation_engine.py` 第 1250-1261 行

**当前代码**:
```python
for row in (steps_rows or []):
    step_info = {"name": ..., "type": ..., "status": ..., "created_at": ...}
    # 只从 output_data 取了 thinking_patterns + complexity
    step_info["thinking_patterns"] = output_dict.get("thinking_patterns", [])
    step_info["complexity"] = output_dict.get("complexity_level", "")
```

**问题**: 传给 deep_analysis prompt 的 `steps_summary` 只有 name/type/status/thinking_patterns/complexity，
丢失了每个 step 的核心数据：content（AI做了什么）、ai_reasoning（AI怎么想的）、
symptom/root_cause/solution、commands_executed、L0 的知识点和解题模式。

**修正**: 改为从 `conversation_steps` 读取 `input_data`（原始 record_step payload）和 `output_data`（L0 分析结果），
传递每个 step 的：
- step_name, step_type
- content（从 input_data 取）
- ai_reasoning（从 input_data 取）
- symptom, root_cause, solution（从 input_data 取）
- commands_executed（从 input_data 取）
- knowledge_points, skill_domains, problem_solving_pattern（从 output_data 取）
- key_insights, thinking_patterns（从 output_data 取）

### P0-2: user_traits 数据源永远为空

**文件**: `conversation_engine.py` 第 1213-1235 行

**当前代码**:
```python
trait_rows = db.query_local(
    "SELECT input_data FROM conversation_steps "
    "WHERE conversation_id = ? AND input_data LIKE '%user_traits%' "
    "ORDER BY step_order", (conversation_id,)
)
```

**问题**: `conversation_steps.input_data` 中从来没有 `user_traits` 字段（AI 端只传 content/ai_reasoning 等），
所以 `user_traits` 永远是空 `{}`。

**修正**: `user_traits` 应该从以下数据源提取：
1. `user_raw_input` — 用户最初对 AI 说的原话（你在规范里说的"用户之初输入文本分析"）
2. `ai_analysis` — AI 对用户意图的理解和初步判断
3. `ai_summary` — AI 对整个对话的复盘观察

传给 prompt 时，不再叫 `user_traits`（误导性命名），改为 `user_context`:
```
user_context = {
    "user_raw_input": "...",
    "ai_analysis": "...",
    "ai_summary": "..."
}
```

prompt 中的 `{user_traits}` 占位符改为直接使用 `user_raw_input`（已经在模板中有这个字段）。

### P0-3: key_decisions 硬编码为空数组

**文件**: `conversation_engine.py` 第 1189 行

```python
key_decisions = []  # v9.2: decisions 字段已删除
```

**问题**: deep_analysis prompt 的 `{key_decisions}` 占位符永远为空。

**修正**: 删除 `key_decisions` 参数。prompt 中已经有 `{steps_summary}`（修正后包含完整步骤数据），
LLM 可以从步骤数据中自己推断技术决策。不需要预先提取 key_decisions。

---

## 三、MD 文档格式与对接流程（周/月/年报数据源）

### 3.1 现状确认

当前 MD 文件体系**已经存在且运作良好**：

```
data/Knowledge Library/
├── Calendar/           ← 日报 MD: {YYYY-MM-DD}.md
├── Reports/
│   ├── Weekly/         ← 周报 MD: {YYYY-WXX}.md
│   ├── Monthly/        ← 月报 MD: {YYYY-MM}.md
│   └── Annual/         ← 年报 MD: {YYYY}.md
├── Cards/{domain}/     ← 技能知识卡片
├── Efforts/{project}/  ← 项目仪表盘 + 业务知识卡片
└── Atlas/              ← 用户画像.md + 知识图谱.md
```

### 3.2 数据对接链路

```
日报生成 (handle_daily_summary)
  输入: SQLite conversations + conversation_steps（当日数据）
  输出: Calendar/{date}.md
      ↓
周报生成 (generate_weekly_report)
  输入: _read_md_reports(Calendar/, date_from, date_to) — 读上周的日报 MD
       + 用户/项目画像快照
  输出: Reports/Weekly/{YYYY-WXX}.md
      ↓
月报生成 (generate_monthly_report)
  输入: _read_md_reports(Reports/Weekly/, date_from, date_to) — 读上月的周报 MD
       + 用户/项目画像快照
  输出: Reports/Monthly/{YYYY-MM}.md
      ↓
年报生成 (generate_annual_report)
  输入: _read_md_reports(Reports/Monthly/, date_from, date_to) — 读去年的月报 MD
       + 用户/项目画像快照
  输出: Reports/Annual/{YYYY}.md
```

### 3.3 _read_md_reports 当前行为

```python
def _read_md_reports(directory, limit=10, date_from=None, date_to=None):
    # 1. 按文件名倒序排列 MD 文件
    # 2. 支持日期范围过滤（文件名格式匹配）
    # 3. 每个文件读取前 2000 字符
    # 4. 返回 [{"file": "2026-07-20.md", "content": "..."}, ...]
```

**文件名格式约定**:
- 日报: `YYYY-MM-DD.md` (如 `2026-07-21.md`)
- 周报: `YYYY-WXX.md` (如 `2026-W30.md`)
- 月报: `YYYY-MM.md` (如 `2026-07.md`)
- 年报: `YYYY.md` (如 `2026.md`)

### 3.4 日报 MD 格式（已实现，需要确认）

当前 `export_daily_report()` 生成的 MD 结构（第 324-543 行）包含：
- Frontmatter（type, date, productivity, learning, projects, kb_links）
- 📋 总结
- 🔍 深度体验（deep_dive + lesson）
- 🛠️ 技能（新技能/模式/工具）
- 📚 知识（必须记住/洞察/技术决策/问题解决）
- ⚠️ 危险信号（重复错误/技术债务/高风险文件）
- 👤 用户画像变化
- 🏗️ 项目画像变化
- 📊 指标（生产力/学习/协作/专注）
- 🏗️ 项目维度（Bug 表格/文件变更/知识落地/决策/项目仪表盘链接）
- 🔗 关联文档（双向链接）

**潜在问题**: 
- `_read_md_reports` 只读前 2000 字符，日报可能很长，2000 字符可能不够 LLM 提取关键信息
- 周报/月报 prompt 的 `{daily_summaries}` 和 `{weekly_summaries}` 是 MD 原文拼接，没有结构化解析

### 3.5 MD 对接改进建议（用户确认）

**方案 A（最小改动）**: 增大 `_read_md_reports` 的读取长度，从 2000 → 5000 字符
**方案 B（结构化）**: 日报 MD 的 Frontmatter 中增加 `summary` 字段，周报读取时先解析 frontmatter 取摘要

建议先用**方案 A**，足够简单有效。

---

## 四、实施计划

### 第一批（P0 — 数据传递修正）

| # | 改动 | 文件 | 行数 |
|---|------|------|------|
| 1 | `steps_summary` 改为包含完整 step 数据 | `conversation_engine.py` | 1242-1276 |
| 2 | 删除 `user_traits` 的无效 grep | `conversation_engine.py` | 1213-1235 |
| 3 | `key_decisions` 不再传空数组 | `conversation_engine.py` | 1189 |
| 4 | deep_analysis prompt 适配新的 steps_summary 格式 | `deep_analysis.py` | 55-57 |

### 第二批（P1 — MD 对接优化）

| # | 改动 | 文件 |
|---|------|------|
| 5 | `_read_md_reports` 读取长度 2000→5000 | `daily_summary.py` |
| 6 | 日报 MD 格式文档化（当前格式确认） | 本文档 |

### 第三批（P2 — prompt 微调）

| # | 改动 | 文件 |
|---|------|------|
| 7 | Step prompt 明确保留解题模式推理 | `step.py` |
| 8 | deep_analysis prompt 的 user_traits 占位符改为 user_raw_input | `deep_analysis.py` |
