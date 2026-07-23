# devPartner 数据分析报告体系设计

> 版本：v1.0　|　设计者：数据分析报告者（Phoebe）　|　日期：2026-07-23
> 配套落地原型：`backend/business/analytics/*` + `scripts/generate_analytics_report.py`

---

## 0. 文档目的

devPartner 的定位是**开发者交互数据分析工具**：通过 MCP 对接 AI，采集开发过程中"用户 ↔ IDE 插件"的多维度交互数据，支撑数据分析与决策。

当前最突出的问题是：**每个分析维度"数据从哪来、用什么分析模式、怎么算"没有系统化规划**，报告呈现为"LLM 对个人工作日记的叙事总结"，无法支撑业务决策。

本文给出一套**"维度 × 指标 × 分析方法 × 数据质量门禁 × 报告模板"**的专业体系，并附**已在真实数据库上跑通的最小可用原型**，做到设计即可落地。

---

## 1. 现状诊断（为什么现有报告"浅"）

探查真实库 `data/databases/devpartner.db` 后，确认根因不是"没数据"，而是**数据从没被规范化、也没被算成指标**：

| 问题 | 证据（真实库） | 对报告的影响 |
|---|---|---|
| 指标层缺失 | 报告仅把日记文本丢给 LLM 写散文，无 KPI、无趋势、无环比 | 无法回答"指标怎么变" |
| 字段口径混乱 | `task_type`：`debug`(14)/`debugging`(2)、`refactoring`(34)/`code_change`(3) 并存 | 任务类型分布指标失真 |
| 主键归一缺失 | `system_id`：`devPartner`(60) vs `devpartner`(1) | 系统级指标碎片化 |
| 同义词泛滥 | `domain`：`Python`(10)/`Python编程`(4)、`数据库`(6)/`数据库管理`(3) 并存 | 知识领域覆盖不可信 |
| 埋点缺失 | `knowledge_points.usage_count` **82 行全为 0** | "知识复用率"关键指标失明 |
| 闭环缺失 | `improvement_log.applied_at` 多为空、`growth_analysis` 0 行 | 改进闭环时效不可算 |
| schema 漂移 | `task_queue` 运行库无 `created_at`（DDL 有） | 可靠性/效率指标口径偏差 |
| 无数据质量门禁 | 直接信任原始记录 | 错误结论被当作事实下发 |

**结论**：要把报告从"日记"升级为"决策支持"，必须先建立**维度注册表 + 指标计算层 + 数据质量门禁**，LLM 只作为"自然语言润色层"而非"分析主体"。

---

## 2. 设计原则

1. **指标先行，LLM 退居增强层**——所有结论必须有可复现的 SQL/计算支撑，LLM 不替代计算。
2. **每个维度必须声明"数据来源 / 分析方法 / 计算口径"**——这是本体系的核心交付物（注册表）。
3. **分析前必过数据质量门禁**——门禁未过的指标降级标注，不可直接下结论。
4. **答案先行**——报告先给洞察、证据、置信度与行动建议，再给明细。
5. **可复现、可扩展**——指标 SQL 明确；新增维度只改注册表 + 一个计算函数。

---

## 3. 总体架构（五层）

```
┌──────────────────────────────────────────────────────────────┐
│  L5 交付层  Reports/ (MD) + Dashboard │ 节奏: 日/周/月/季/临时   │
├──────────────────────────────────────────────────────────────┤
│  L4 分析层  report_builder（答案先行）│ 描述/诊断/预测 方法论     │
├──────────────────────────────────────────────────────────────┤
│  L3 数据质量门禁  data_quality（DQ 评分 + 问题清单）  ← 报告前置  │
├──────────────────────────────────────────────────────────────┤
│  L2 指标层  metrics（当期/环比/置信度，含归一映射）               │
├──────────────────────────────────────────────────────────────┤
│  L1 维度×数据源注册表  registry（业务问题/来源/口径/分析方法/DQ） │
├──────────────────────────────────────────────────────────────┤
│  数据源  conversations / conversation_steps / knowledge_points  │
│        / task_queue / user_profile / user_skills /            │
│        connected_systems / system_context_fragments /         │
│        improvement_log / optimization_feedback                 │
└──────────────────────────────────────────────────────────────┘
```

每一层都有对应代码文件，已在原型中落地（见 §9）。

---

## 4. 维度模型（8 个分析维度）

每个维度在 `registry.py` 中声明 6 个要素：**业务问题 / 数据来源 / 指标清单 / 分析方法 / DQ 校验 / 归一映射**。

| ID | 维度 | 业务问题（决策价值） | 主数据源 | 分析方法 |
|---|---|---|---|---|
| D1 | 参与度与体量 | 交互活跃度与健康度？是否沉默？ | conversations | 描述 + 趋势(WoW/MoM) + 沉默检测 |
| D2 | 任务类型分布 | 在做什么工作？构成是否健康？ | conversations.task_type | 构成分析(mix shift) |
| D3 | 执行与可靠性 | 成败与效率？哪里出错/卡顿/重试？ | conversation_steps, task_queue | 诊断(失败聚类) + 耗时分布 |
| D4 | 知识沉淀 | 积累多少可复用知识？质量与覆盖？ | knowledge_points | 构成 + 质量 + 复用闭环 |
| D5 | 用户能力成长 | 哪些领域提升？学习计划执行？ | user_profile, user_skills, user_skill_plan | 趋势 + 计划漏斗 |
| D6 | 系统/项目覆盖 | 覆盖多少系统？上下文是否持续？ | connected_systems, system_context_fragments | 覆盖 + 集中度 + 发现速率 |
| D7 | 改进闭环 | 问题/建议是否闭环？响应及时？ | improvement_log, optimization_feedback | 漏斗 + 时效 |
| D8 | 效率与成本 | 单位时间产出？资源消耗合理？ | conversation_steps, task_queue | 分布(分位抗偏态) + 吞吐 |
| D9 | 用户心理与画像 | 用户在想什么/怎么想/在成长还是受挫？对话内容藏什么洞察？ | conversations(topic/intent/reflection), user_profile, user_skills, user_skill_plan | 定性内容分析：主题聚类 + 心理信号词典 + 画像聚合 + 成长势能 |

> 扩展新维度只需在 `registry.py` 的 `DIMENSIONS` 追加一条，并在 `metrics.py` 增加对应计算函数（见 §13）。

---

## 5. KPI 框架（结果 / 驱动 / 护栏）

避免"一堆指标没有主次"，每个维度下的指标分三层：

- **结果指标（Outcome）**：直接回答业务成败。例：步骤成功率、知识复用率、改进建议采纳率。
- **驱动指标（Driver）**：解释结果为何变化。例：重试率、debug 占比、知识新增速度。
- **护栏指标（Guardrail）**：防止"为了结果伤害系统"。例：真实错误率、数据停滞天数、孤儿步骤数。

**目标设定**两路并行：
- 自上而下：行业/历史基准（如步骤成功率 >95%、真实错误率 <5%）。
- 自下而上：基于近期可影响范围设定可达目标，逐期收紧。

---

## 6. 分析方法论（按问题选型）

| 业务问题类型 | 分析方法 | 统计口径要求 |
|---|---|---|
| 指标怎么变？ | 描述性 + 时间序列（WoW/MoM） | 环比需等长窗口；样本 <10 置信度降为 low |
| 为什么变？ | 诊断性分解（mix shift / 失败聚类） | 区分"构成变化"与"组内表现" |
| 会怎样？ | 预测性（趋势外推/预警） | 标注置信区间，避免无样本外推 |
| 是否显著？ | 假设检验 / 效应量 | p<0.05 方可下因果之外推；时序相关须谨慎 |
| 分布是否偏态？ | 用中位数 + 分位数，不用均值 | 耗时/内存类必须用中位数（防长尾扭曲） |

**关键规则**：时序数据不做"同因推断"——A 先于 B 不等于 A 导致 B，结论中区分"已验证驱动"与"合理假设"。

---

## 7. 数据质量门禁（DQ Gate）

报告生成前强制运行 `data_quality.run_dq()`，输出 **DQ 评分（0-100）+ 问题清单（严重度/影响行/修复建议）**。评分规则：high 项扣 12、medium 扣 6、low 扣 2，按影响行数触发。

真实库首次运行结果（证据体系必要性）：

```
DQ 评分 36/100（D），发现 9 项问题，其中 high=3 项需优先修复
high: 孤儿步骤(2行) / 知识复用埋点缺失(82行全0) / task_queue schema 漂移(缺 created_at)
medium: task_type 未归一(41行) / system_id 大小写(1行) / domain 同义词(25行) / self_reflection 空值41%
low:   complexity 空值16% / user_intent 空值15%
```

门禁对报告的影响：
- 受污染指标在计分卡与明细中标注 ⚠️ 并附说明；
- 置信度随样本量与埋点完整性下调（如 reuse_rate = low）；
- DQ 摘要固定置于报告第二节（"可信度前置"）。

---

## 8. 报告模板与节奏

### 8.1 四种模板

1. **执行摘要（答案先行）**——给负责人。结构：`核心洞察 / 关键证据 / 置信度 / 建议动作`。
2. **KPI 计分卡**——全量指标一表：维度 / 指标 / 当期 / 环比 / 基准 / 状态 / 置信度。
3. **分维度诊断**——每个维度：发生了什么 / 为什么 / 业务含义 / 下一步。
4. **行动建议与待解问题**——高/中/低优先级建议 + 提升置信度需补齐的埋点。

### 8.2 节奏与受众

| 节奏 | 范围 | 受众 | 重点 |
|---|---|---|---|
| 日报 | 当日 | 个人/值班 | 异常与阻塞（DQ 红项） |
| 周报 | 近 7 天 | 团队负责人 | 趋势 + 构成(mix) + 预警 |
| 月报 | 近 30 天 | 管理者 | 成长 + 闭环 + 目标达成 |
| 季报 | 季度 | 决策者 | 战略维度复盘 + 路线图调整 |
| 临时下钻 | 任意维度 | 分析者 | 根因钻取（失败聚类/字段细分） |

> 现有 `reports.py` 的 LLM 日记式周/月报可保留为"叙述层"，但必须以本体系的 KPI 计分卡为骨架，LLM 仅做润色。

---

## 9. 落地原型（已跑通真实库）

已实现并验证的代码：

| 文件 | 职责 |
|---|---|
| `backend/business/analytics/registry.py` | 维度×数据源×分析模式注册表（9 维度全声明） |
| `backend/business/analytics/metrics.py` | 指标计算层（当期/环比/置信度 + 归一映射 + 容错） |
| `backend/business/analytics/profiling.py` | **D9 用户心理与画像**：内容完整度 + 心理信号词典 + 画像聚合 + 技能树/计划 |
| `backend/business/analytics/data_quality.py` | 数据质量门禁（9 项检查 + 评分） |
| `backend/business/analytics/report_builder.py` | 答案先行报告生成器（Obsidian-native：frontmatter/tags/wikilink/callout） |
| `scripts/generate_analytics_report.py` | CLI：`--all` 全量快照 / `--days N` 滚动窗口 / `--plain` 关 Obsidian |

**运行**：
```bash
python scripts/generate_analytics_report.py --all --out data/reports/analytics_sample_report.md
python scripts/generate_analytics_report.py --days 30 --end 2026-07-23
```

**真实样本结论（节选，证明可落地）**：
- 参与度：对话量本期 40 次，环比 **▲90.5%**（活跃度上升）。
- 可靠性：步骤成功率 **93.5%（▼6.5%）** 触发预警——真实下滑，需下钻失败步骤。
- 错误率：真实错误率 **3.6%（▼53.2%）**，已落回健康区（<5%）。
- 知识：新增 39 个，归一后覆盖 9 个领域，但**复用率 0%（埋点缺失）**。
- 闭环：改进建议采纳率 0%、积压 83 条——闭环机制未运转。
- 心理与画像：复盘率 60%（▲5.1%）、意图清晰度 95%（▲42.4%）；受挫/风险信号占比 **83.3%**（词典法，多为调试型 vocabulary，需结合画像 trend 判断真实性）；画像置信度 0.8、成长势能 40%（debug/refactoring 维度 rising）；技能树 7 个、学习计划 33 条但完成率 0%。

---

## 10. 实施路线图

| 阶段 | 内容 | 产出 | 建议排期 |
|---|---|---|---|
| **P0（已落地）** | 维度注册表 + 指标层 + DQ 门禁 + 报告生成器 + CLI | 可运行原型、样本报告 | 已完成 |
| **P1（数据治理）** | 落归一映射（`TASK_TYPE`/`SYSTEM_ID`/`DOMAIN`）；修 schema 漂移（补 `task_queue.created_at` 或统一 `queued_at`）；隔离孤儿步骤 | 指标口径可信 | 1 周 |
| **P2（埋点补齐）** | `usage_count` 引用计数、`actual_memory_mb` 采集、`applied_at` 写入 | reuse_rate / mem_accuracy / 闭环时效 可用 | 2 周 |
| **P3（接入现有报告）** | 用本 KPI 计分卡替换 `reports.py` 的 LLM 日记骨架；周/月报自动生成 | 决策级周/月报 | 1 周 |
| **P4（Dashboard）** | 指标层暴露为 API；前端图表（趋势/构成/漏斗）；异常自动告警 | 实时看板 | 2-3 周 |
| **P5（预测与闭环）** | 趋势预测 + 目标达成预警；growth_analysis 自动写入并跟踪采纳 | 主动决策支持 | 持续 |

---

## 11. 可视化规范（图表选型矩阵）

| 分析意图 | 推荐图表 | 禁止 |
|---|---|---|
| 看趋势（指标随时间） | 折线图（带环比对照） | 饼图 |
| 看构成（任务/领域占比） | 堆叠条形图 / 100% 堆叠 | 3D 饼图 |
| 看分布（耗时/内存偏态） | 箱线图 / 直方图（中位数+分位） | 仅均值 |
| 看漏斗（改进闭环） | 漏斗图 | — |
| 看集中度（系统占比） | 条形图 + 帕累托线 | 饼图（>6 类） |
| 看相关性（埋点齐后） | 散点图 + 趋势线 | 无坐标轴线 |

通用规范：配色区分"好/警"（绿/琥珀），灰度可辨；标签不重叠；坐标轴从 0 起（比例类可截断但须标注）；所有图附数据来源与统计周期。

---

## 12. 扩展指南（新增一个维度/指标）

1. 在 `registry.py` 的 `DIMENSIONS` 追加一条：声明 `business_question / source / metrics / analysis_mode / dq_checks / normalization`。
2. 在 `metrics.py` 增加 `_dN_xxx(cur, ...)` 计算函数，返回指标列表（含 `current/previous/delta_pct/unit/baseline/direction/confidence`）。
3. 在 `compute_metrics()` 的 `results` 中注册该维度。
4. 若该维度依赖新字段归一，在 `registry.py` 顶部增加映射表并在 `data_quality.py` 增加对应校验。
5. 运行 CLI 验证输出，确认 DQ 评分与新指标出现在计分卡。

---

## 13. 附录：注册表字段字典

| 字段 | 含义 | 示例 |
|---|---|---|
| `id` | 维度唯一标识 | `D3_reliability` |
| `business_question` | 该维度要回答的决策问题 | "AI 执行任务的成败与效率如何？" |
| `source.tables` | 数据来源表 | `["conversation_steps","task_queue"]` |
| `source.grain` | 统计粒度 | `step / task` |
| `source.key_fields` | 关键字段 | `["status","duration_ms","error_message"]` |
| `source.collection` | 采集机制 | `step_analysis 执行时写入` |
| `source.freshness` | 新鲜度 SLA | `实时` |
| `source.owner` | 负责人/模块 | `backend.core.task_queue` |
| `metrics[].formula` | 计算口径（对应 SQL） | `completed/(completed+orphaned+failed)` |
| `metrics[].baseline` | 比较基准 | `>95%` |
| `metrics[].direction` | 优劣方向 | `up_good / down_good / balanced` |
| `analysis_mode` | 分析方法 | `diagnostic（失败根因分解）` |
| `dq_checks` | 依赖的数据质量校验 | `["step.status 枚举合法"]` |
| `normalization` | 引用的归一映射名 | `SYSTEM_ID_NORMALIZATION` |

---

*本体系以"可落地"为硬标准：设计文档 + 真实库跑通的原型 + 样本报告，三者齐备。下一步建议从 P1 数据治理启动，1 周内即可让指标口径可信。*

---

## 14. 用户心理与画像层（D9，定性内容分析）

### 14.1 定位：定量层 + 定性层互补
D1–D8 是**行为/运营计数层**（把对话当计数行）；D9 是**语义/心理定性层**。两者回答不同问题：定量说「发生了什么、变了多少」，定性说「用户在想什么、为什么这样想、在成长还是受挫」。原 LLM 日记式周/月报只做了定性叙述却无定量骨架；本体系把二者结合——D9 在指标骨架之上做内容分析，LLM 仅做润色而非替代计算。

### 14.2 数据底座（真实库已具备，无需新建）
| 来源 | 字段 | 填充率 |
|---|---|---|
| `conversations` | `topic` / `user_intent` / `self_reflection` / `complexity` | 100% / 85% / 60% / 84% |
| `user_profile` | `dimension` / `value` / `trend` / `confidence` / `evidence`（已结构化画像） | 5 维 |
| `user_skills` | `skill_domain` / `skill_name` / `skill_level` / `growth_trend` / `hours_spent` | 7 条 |
| `user_skill_plan` | `goal` / `target_level` / `current_progress` / `status` | 33 条 |
| `knowledge_points` | `domain`（能力雷达） | 9 领域 |

### 14.3 指标（8 个）
复盘率、意图清晰度、受挫/风险信号占比、进展/心流信号占比、画像置信度、成长势能、技能树规模、学习计划完成率。

### 14.4 方法论（透明、可审计、非黑箱）
- **内容完整度**（复盘率/意图清晰度）：越高越利于后续分析。
- **心理信号**：中文词典法（`RISK_LEXICON` / `PROGRESS_LEXICON`，见 `profiling.py`），对 `self_reflection` 做扫描，给出受挫 vs 进展信号占比。词典可审计、可迭代；深度心理编码建议叠加 LLM 定性摘要（在指标之上叙述，不替代计算）。
- **画像聚合**：`user_profile` 的 `confidence` / `trend` → 画像置信度 / 成长势能。
- **技能树/计划**：`user_skills` / `user_skill_plan` 聚合。

### 14.5 置信度与边界（重要）
- 受挫信号 83.3% 多为**调试型 vocabulary**（「暴露/问题/错误」高频），需结合画像 `trend` 判断是否为真实摩擦，不可直接解读为"用户状态差"。
- `self_reflection` 仍 25/61 为空 → 信号置信度 medium，建议强化复盘采集。
- 明确标注：本层为**基于词典的内容信号分析，非临床心理评估**。

---

## 15. Obsidian 对接规范

用户将报告落地为 `.md` 是为接入 **Obsidian 知识库**，故输出默认 Obsidian-native。

### 15.1 报告笔记（`data/reports/analytics_sample_report.md`）
- **YAML frontmatter**：`type / period_type / period_start / period_end / generated / dq_score / dq_grade` + 关键指标属性（`conv_total / step_success_rate / real_error_rate / reflection_rate / portrait_confidence`）→ 供 **Dataview** 查询。
- **#标签**：`#devpartner/report/<type>`、`#analytics/devpartner`。
- **Callout**：`> [!tip]` 核心洞察 / `> [!warning]` 数据质量 / `> [!note]` 定性层说明。
- **Wikilink**：D9 段链接 `[[devPartner/用户画像]]`，串成知识图谱。
- CLI 加 `--plain` 可关闭上述所有 Obsidian 特性，退回纯 markdown。

### 15.2 常青画像笔记（`data/reports/user_portrait.md`）
- 跨报告复用，是图谱**枢纽节点**；每次运行自动更新（聚合 `user_profile` + `user_skills` + `user_skill_plan`）。
- 同样带 frontmatter + `#user-portrait` 标签 + 反向 wikilink 回来源报告。

### 15.3 图谱用法建议
报告 → 用户画像 → 技能/计划实体形成链路；建议为高频 `knowledge.domain` 也建 `[[knowledge/<domain>]]` 原子笔记，进一步丰富双向链接，发挥 Obsidian 图谱与反链价值。
