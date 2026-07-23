# 日报结构化指标 · 趋势与环比分析查询

> 本文件是 P1（日报结构化字段落库）的**消费侧**文档：把 `daily_report_metrics` 表里的数据变成可看的趋势/环比/频率分析。
> 所有 SQL 已用 30 天合成数据（与真实落库同路径 `json.dumps(ensure_ascii=False)`）跑通验证。

## 1. 数据来源与前提

- **表**：`daily_report_metrics`（v9.10.1 P1 新增），每日一行，`date` 为唯一主键。
- **真实库路径**：`data/databases/devpartner.db`（SQLite）。表由 `base_conn._init_local_schema` 在首次 `get_db()` 时自动建；已对当前真实库手动 ensure 过。
- **落库触发**：每次 LLM 日报生成后，`handle_daily_summary` 调用 `_store_daily_report_metrics` 执行 `INSERT OR REPLACE`（按 `date` 幂等）。
- **列清单**（与 schema 完全一致）：
  - `date` TEXT，分数：`productivity_score` / `learning_score` / `collaboration_score` / `focus_score`（INT 0-10）
  - 分数依据：`productivity_evidence` / `learning_evidence` / `collaboration_evidence` / `focus_evidence`（TEXT，引用 facts 里的真实数字）
  - `frustration_level` INT 1-5，`decision_style` TEXT
  - JSON 数组：`flow_signals` / `recurring_blockers` / `facts`
  - JSON 对象：`psychology` / `metrics_json`，`llm_method` TEXT，`created_at` TEXT
- **空库属正常**：表刚建、尚无日报落库时，所有查询返回 0 行。先确保日报按 LLM 模式生成过一次。

## 2. SQL 趋势/环比查询（SQLite）

### Q1 · 近 30 日每日分数趋势（折线图 / Dataview 表的数据源）
```sql
SELECT date, productivity_score, learning_score, collaboration_score, focus_score, frustration_level
FROM daily_report_metrics
WHERE date >= date('now','-30 days')
ORDER BY date;
```

### Q2 · 7 日移动平均（平滑单日噪声，看真实走势）
```sql
SELECT date,
  ROUND(AVG(productivity_score) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),2) AS productivity_7d,
  ROUND(AVG(focus_score)      OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),2) AS focus_7d,
  ROUND(AVG(frustration_level) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),2) AS frustration_7d
FROM daily_report_metrics
WHERE date >= date('now','-30 days')
ORDER BY date;
```

### Q3 · 周环比 WoW（本周均值 − 上周均值）
```sql
WITH w AS (
  SELECT
    CASE WHEN date >= date('now','-7 days')  THEN 'cur'
         WHEN date >= date('now','-14 days') THEN 'prev' END AS wk,
    AVG(productivity_score) AS prod,
    AVG(focus_score)       AS foc,
    AVG(frustration_level) AS frus
  FROM daily_report_metrics
  WHERE date >= date('now','-14 days')
  GROUP BY wk
)
SELECT
  ROUND(MAX(CASE WHEN wk='cur' THEN prod END) - MAX(CASE WHEN wk='prev' THEN prod END),2) AS productivity_wow,
  ROUND(MAX(CASE WHEN wk='cur' THEN foc END) - MAX(CASE WHEN wk='prev' THEN foc END),2) AS focus_wow,
  ROUND(MAX(CASE WHEN wk='cur' THEN frus END) - MAX(CASE WHEN wk='prev' THEN frus END),2) AS frustration_wow
FROM w;
```
> 正数 = 本周优于上周；`frustration_wow` 为负 = 挫败下降（好事）。

### Q4 · 月度聚合（月度健康度）
```sql
SELECT strftime('%Y-%m', date) AS month,
  ROUND(AVG(productivity_score),2) AS avg_productivity,
  ROUND(AVG(learning_score),2)    AS avg_learning,
  ROUND(AVG(frustration_level),2) AS avg_frustration,
  COUNT(*) AS days
FROM daily_report_metrics
GROUP BY month ORDER BY month;
```

### Q5 · 反复阻塞点频率（JSON 数组展开）
```sql
SELECT value AS blocker, COUNT(*) AS freq
FROM (SELECT recurring_blockers AS rb FROM daily_report_metrics), json_each(rb)
GROUP BY blocker ORDER BY freq DESC LIMIT 10;
```
> ⚠️ **关键坑**：`json_each` 的 `value` 已是「解码后的标量字符串」（如 `编译慢`），**直接用 `value` GROUP BY**。
> 不要用 `json_extract(value,'$')`——裸字符串不是合法 JSON，会报 `malformed JSON`。

### Q6 · 心流信号频率
```sql
SELECT value AS flow, COUNT(*) AS freq
FROM (SELECT flow_signals AS fs FROM daily_report_metrics), json_each(fs)
GROUP BY flow ORDER BY freq DESC LIMIT 10;
```

## 3. Obsidian Dataview 查询

日报 MD 的 frontmatter 由 `_daily_fm` 注入 `type/productivity_score/learning_score/collaboration_score/focus_score/frustration_level/date/tags` 等字段，Dataview 可直接查。

### 近 14 天分数表
```
TABLE
  productivity_score AS 生产力,
  learning_score     AS 学习,
  collaboration_score AS 协作,
  focus_score        AS 专注,
  frustration_level  AS 挫败
FROM "Calendar"
WHERE type = "daily_report"
SORT date DESC
LIMIT 14
```
> 路径 `"Calendar"` 按你的 vault 实际文件夹调整（devPartner 导出到 Obsidian vault 的日报目录）。

### 心流 / 阻塞点频率（DataviewJS）
frontmatter 里的 `facts` / `psychology` 是 JSON 字符串，可在 DataviewJS 里 `JSON.parse` 后统计。下面是个最小模板（按你的 vault 路径改 `pages` 来源）：

```js
const pages = dv.pages('#daily_report').where(p => p.recurring_blockers);
const freq = {};
for (const p of pages) {
  let arr = [];
  try { arr = JSON.parse(p.recurring_blockers); } catch (e) {}
  for (const b of arr) freq[b] = (freq[b] || 0) + 1;
}
const rows = Object.entries(freq).sort((a,b)=>b[1]-a[1]).slice(0,10);
dv.table(["阻塞点","频次"], rows);
```

## 4. 怎么用

1. **本地快速看趋势**：用任意 SQLite 客户端打开 `data/databases/devpartner.db`，粘贴上面的 SQL。
2. **长期看板**：把日报 MD 落进 Obsidian vault，用第 3 节的 Dataview 查询做持续追踪。
3. **数据为空**：先让 devPartner 按 LLM 模式跑一次日报（自动落库），再回来查。

## 5. 验证记录

- 合成 30 天数据，覆盖带上行趋势的分数、波动的挫败、含中文的阻塞点/心流数组。
- Q1-Q4（趋势/移动平均/周环比/月度）全部正常返回。
- Q5/Q6 频率统计正确（如 `接口文档不全 30 / 编译慢 15 / 环境不一致 15`）。
- 修复点：`json_extract(value,'$')` → `value`（json_each 标量元素不能二次 JSON 解析）。
