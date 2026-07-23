# P1 落地：日报结构化（facts / psychology / evidence + 落库 + frontmatter）

## 背景
P0 让长周期报告能生成。P1 针对**日报**做三件事，让日报从"散文"变"可量化 + 结构化心理 + 可聚合"，全部基于现有框架、字段映射有代码依据。

## 改了什么

| 文件 | 改动 |
|------|------|
| `backend/templates/llm_prompt/daily_summary.py` | `TASK_DAILY_SUMMARY` 新增顶层 `facts`（带数字可量化事实）；`metrics` 每项改为 `{score, evidence}`（evidence 须引用 facts）；新增 `psychology{frustration_level 1-5, flow_signals[], decision_style, recurring_blockers[]}`；末尾加"禁止虚构"。保留全部现有占位符 |
| `backend/business/vault_export/md_engine.py` | 新增 `render_metrics`（处理 `{score,evidence}`/纯整数 → `**label**: score — 证据：evidence`）。修复同款嵌套字段 bug：先下钻 `value.get("metrics")` |
| `backend/business/vault_export/md_templates.py` | 日报模板加 `## 📊 事实锚点` 与 `## 🧠 心理与协作信号` 两 section；`## 📊 指标` 段改 `render_metrics`；`_daily_fm` 加 4 个分数 + frustration_level + tags；周/月/年报 `_*_fm` 加 overall_score + emotional_state_trend（供 Obsidian Dataview） |
| `backend/core/database/base_conn.py` | schema 新增 `daily_report_metrics` 表（date UNIQUE，4 score + 4 evidence 列，frustration_level，flow_signals/recurring_blockers/facts/psychology/metrics_json JSON 列，llm_method，created_at）+ 索引 |
| `backend/business/task_handlers/daily_summary.py` | 新增 `_store_daily_report_metrics(db, date_str, summary)`：`INSERT OR REPLACE`（按 date 幂等） |
| `backend/business/task_handlers/daily_engine.py` | `handle_daily_summary` 导出 MD 后、guard `analysis_method=="llm"` 下调用落库 |

## 验证（全绿）
- `TASK_DAILY_SUMMARY` 用 `base_client.generate_daily_summary` 实际传入的 kwargs 跑 `.format()` 通过（占位符完全对齐）。
- 端到端 `assemble("daily_report", ...)` 真实渲染出：
  - `## 📊 事实锚点`：`今日 12 次对话，debug 类 7 次占 58%` / `覆盖 40%→72%`
  - `## 📊 指标`：`**生产力**: 8 — 证据：完成 3 个核心模块，无返工`
  - `## 🧠 心理与协作信号`：`挫败水平(1-5): 2` / 心流信号 / 决策风格 / 反复阻塞
- `daily_report_metrics` DDL 在 in-memory sqlite 建表成功；`_store_daily_report_metrics` 连续两次写入得 **1 行**（证明 `INSERT OR REPLACE` 幂等）；分数/facts/evidence 正确回读。
- `_daily_fm` / `_weekly_fm` 查询字段正确产出。
- `pytest tests/test_vault_export.py tests/test_smoke.py` = **10 passed**，无回归。

## 日报 MD 效果片段
```
## 📊 事实锚点
**事实锚点**:
- 今日 12 次对话，debug 类 7 次占 58%
- 完成 3 个模块单测，覆盖 40%→72%

## 📊 指标
**生产力**: 8 — 证据：完成 3 个核心模块，无返工
**学习**: 7 — 证据：掌握回调重试机制
**协作**: 6 — 证据：与前端对齐 2 次接口
**专注**: 7 — 证据：深度专注 4h 无中断

## 🧠 心理与协作信号
**挫败水平(1-5)**: 2
**心流信号**:
- 重构模块时连续 2h 无打断
**决策风格**: 先全量扫描再定位
**反复阻塞**:
- 回调超时
```

## 关键渲染契约（再次确认）
`MdAssembler.assemble()` 给每个 section 的 `value` = `data.get(sec.key)`，日报 section 的 `key` 均为 `"report_data"`，故 renderer 收到的是**整个 LLM 结果 dict**，必须自己下钻取子字段（`render_kv._resolve` 下钻一层；`render_metrics` 取 `.metrics`；`render_psychology` 取 `.psychology`）。新增 renderer 时务必遵守，否则嵌套 section 会被静默跳过。

## 未做（P1 范围外，留给后续）
- 审计 4.1 改进点 4：`user_profile_update` 改 `dimension/value/trend/confidence` 对齐 `user_profile` 表 —— 未重构，避免破坏 finalize 画像合并管线。
- 维度治理：`task_type`/`domain`/`system_id` 归一、`usage_count` 全 0、`task_queue` 缺 `created_at` —— 仍未做（属数据治理，独立项）。

## 下一步建议
日报分数已落库，可直接写一条查询做**趋势/环比**（如近 30 天 productivity_score 走势、frustration_level 周环比）。需要我加一个 `scripts/query_daily_metrics.py` 或 Obsidian Dataview 查询示例吗？
