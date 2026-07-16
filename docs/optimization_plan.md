# DevPartner 系统优化计划书

> **版本**: v1.0 | **日期**: 2026-07-08 | **状态**: 待执行
> 
> **审计来源**: 12 大类问题系统诊断  
> **优化原则**: 删除优先于添加，标准库优先，最少代码解决问题  
> **分层路径**: Agent 层要求 → 框架 → 逻辑 → 代码 → 新功能

---

## 一、问题归纳（12 类 → 5 层）

### 总览矩阵

| # | 问题大类 | 严重度 | 归属层 | 简要描述 |
|---|---------|--------|--------|---------|
| 1 | Schema 文档缺失 | 🔴 严重 | Agent层 | 11 张表全部缺 COMMENT/字段备注 |
| 2 | conversation_archive 冗余 | 🟡 一般 | 框架 | 表存在但无新数据写入，确认是否废弃 |
| 3 | conversation_steps 生命周期 | 🔴 严重 | 框架 | pending 状态历史遗留、无兜底、无清理 |
| 4 | 数据写入不完整 | 🔴 严重 | 逻辑 | knowledge_point_ids/duration_ms/started_at 未回写 |
| 5 | LLM 分析结果空 | 🟡 一般 | 逻辑 | actions 字段 "LLM深层分析:  " 后为空 |
| 6 | evolution_log 无数据 | 🟡 一般 | 逻辑 | 触发路径不明确，始终为空 |
| 7 | improvement_log 定位混乱 | 🟡 一般 | 逻辑 | 用户/系统混存，status 始终 pending |
| 8 | knowledge_points 数据质量问题 | 🟡 一般 | 代码 | source_id 格式不统一，usage_count 始终 0 |
| 9 | meta 表用途不明 | 🟢 低 | 代码 | 仅有 schema_version，缺设计文档 |
| 10 | optimization_feedback 审查 | 🟢 低 | 代码 | 字段冗余（conversation_id + conversations_id 双外键） |
| 11 | task_queue 数据缺失 | 🟡 一般 | 代码 | result/actual_memory_mb 未回写 |
| 12 | version_history 记录不完整 | 🟢 低 | 代码 | 服务重启被误记录，变更详情缺失 |
| 13 | 用户技能展示增强 | 🟢 低 | 新功能 | 复习机制、遗忘曲线、知识关联图谱 |

---

## 二、第一层：Agent 层要求

> **目标**: 定义"应该是什么样子"，不写代码，只说规范

### 2.1 数据库表文档规范

**要求**：每张表必须有 COMMENT 注释，每个字段必须有用途备注。

```
表名: conversations
用途: 核心对话记录表，存储每次对话的元信息
字段:
  id               INTEGER  自增主键
  conversation_id  TEXT     全局唯一对话标识（UUID）
  timestamp        TEXT     对话创建时间（ISO 8601）
  client           TEXT     客户端标识（codebuddy/cursor/...）
  topic            TEXT     对话主题（一句话）
  task_type        TEXT     任务类型（debug/design/code_change/...）
  actions          JSON     对话中执行的操作摘要
  analyzed         INTEGER  是否已完成用户画像分析（0/1）
  ...
```

**执行**: 在 `database.py` 的 `_create_local_tables()` 每个 `CREATE TABLE` 前加多行注释，描述表用途和字段含义。

### 2.2 生命周期状态机规范

**要求**：conversation_steps 必须定义完整的状态机。

```
                ┌─────────┐
        record_step()      │
                ↓          │
           ┌─────────┐    │
           │ pending │────┘ (重试)
           └────┬────┘
                │ Worker 拾取
                ↓
           ┌──────────┐
           │ in_progress │
           └─────┬──────┘
                 │
          ┌──────┼──────┐
          ↓      ↓      ↓
     completed failed timeout
          │      │      │
          └──────┼──────┘
                 ↓
           ┌─────────┐
           │ 兜底清理  │ ← 超过 24h 的 pending 标记为 orphaned
           └─────────┘
```

**兜底政策**:
- `pending` 超过 **24 小时** → 自动标记为 `orphaned`（不删除，保留数据）
- `in_progress` 超过 **10 分钟** → Worker 超时检查回退为 `pending`
- `failed` 超过最大重试次数 → 永久 `failed`，不自动恢复

**数据恢复**:
- 孤儿步骤可手动 `retry` 重置为 `pending`
- 不提供自动恢复（防止误操作覆盖人工分析）

**清理政策**:
- 已完成的 `conversation_steps` → 不自动清理（永久保留）
- `orphaned` 超过 **30 天** → 可归档到 `conversation_archive`
- 不提供硬删除（数据安全优先）

### 2.3 improvement_log 定位规范

**要求**：明确定义两表分工。

| 表 | 定位 | 数据来源 | 示例 |
|----|------|---------|------|
| `improvement_log` | **系统自改进** | AI 分析生成 | "LLM 深层分析发现：系统缺少 XX 能力" |
| `optimization_feedback` | **用户反馈** | 用户主动提交 | "用户反馈：记录太冗长，希望精简" |

**字段约束**:
- `improvement_log.status` 必须流转：`pending` → `in_progress` → `applied`/`rejected`
- `improvement_log.category` 取值：`system_issue` / `decision` / `user_insight` / `self_improvement`

---

## 三、第二层：框架层

> **目标**: 调整表结构和约束，不改业务逻辑

### 3.1 conversation_archive 去留决策

**现状**: 表存在且有 FK 约束，但无新数据写入。  
**决策**: **保留但标记为 deprecated**。

```sql
-- 在表注释中标明
-- @deprecated v6.0: 总分总架构后不再使用，保留仅用于历史数据查询
-- 计划移除: v8.0
```

**理由**: 
- 历史数据不能丢
- 移除 FK 约束需要迁移脚本
- 新数据已全部走 `conversation_steps` 流程

### 3.2 添加缺失的字段默认值和约束

**conversation_steps**:
```sql
-- started_at: 默认插入时自动设置
ALTER TABLE conversation_steps ... started_at TEXT DEFAULT CURRENT_TIMESTAMP;

-- knowledge_point_ids: 默认空字符串，避免 NULL
-- 已有字段，仅需确保写入逻辑

-- duration_ms: 允许 NULL（未完成时为 NULL，完成后回写）
```

**task_queue**:
```sql
-- result: 已完成任务必须回写
-- actual_memory_mb: 任务完成后回写实际内存占用
```

### 3.3 optimization_feedback 外键简化

**现状**: 同时有 `conversation_id TEXT` 和 `conversations_id INTEGER` 两个外键。  
**决策**: 保留 `conversations_id`（INTEGER FK），`conversation_id` 标记 deprecated。

```sql
-- @deprecated v6.0: conversation_id 字段保留用于兼容，新数据用 conversations_id
```

### 3.4 索引补充

```sql
-- conversation_steps 按时间清理
CREATE INDEX IF NOT EXISTS idx_conversation_steps_created 
ON conversation_steps(created_at);

-- knowledge_points 按使用频率排序
CREATE INDEX IF NOT EXISTS idx_knowledge_points_usage 
ON knowledge_points(usage_count DESC);

-- improvement_log 按状态筛选
CREATE INDEX IF NOT EXISTS idx_improvement_log_status 
ON improvement_log(status);
```

---

## 四、第三层：逻辑层

> **目标**: 修复数据流中的逻辑缺陷，不新增代码文件

### 4.1 conversation_steps 数据写入修复

**问题**: `_execute_step_analysis()` 中三个字段未正确回写。

**文件**: `devpartner_agent/services/task_queue.py`

#### 修复 1: knowledge_point_ids 回写

```python
# 当前代码 (L591-601): UPDATE 只写了 status/output_data/completed_at/duration_ms
# 修复: 追加 knowledge_point_ids

db.query_local("""
    UPDATE conversation_steps SET
        status = 'completed', 
        output_data = ?,
        knowledge_point_ids = ?,
        completed_at = ?, 
        duration_ms = ?
    WHERE step_id = ?
""", (
    json.dumps(results, ensure_ascii=False),
    json.dumps(kp_ids),          # ← 新增
    datetime.now().isoformat(),
    actual_duration_ms,           # ← 见修复 2
    step_id
))
```

#### 修复 2: duration_ms 计算

```python
# 当前代码 (L599): duration_ms = 0 硬编码
# 修复: 在 Worker 拾取任务时记录 started_at，完成后计算差值

# 在 _execute_step_analysis() 开头记录开始时间
step_start = datetime.now()

# ... LLM 分析逻辑 ...

# 计算实际耗时
actual_duration_ms = int((datetime.now() - step_start).total_seconds() * 1000)
```

#### 修复 3: started_at 设置

```python
# 在 record_step() 写入时设置（server.py L4074 附近）
db.query_local("""
    INSERT INTO conversation_steps (...) VALUES (...)
""")

# 同时 UPDATE started_at
db.query_local("""
    UPDATE conversation_steps SET started_at = ? WHERE step_id = ?
""", (datetime.now().isoformat(), step_id))
```

### 4.2 LLM 分析结果空值修复

**问题**: `actions` 字段 `"LLM深层分析: "` 后为空（`overall_assessment` 可能为空字符串）。

**文件**: `devpartner_agent/services/task_queue.py` (L851-861)

```python
# 当前代码:
# actions = CASE WHEN ... THEN ? ELSE actions || ' | LLM_DEEP: ' || ? END
# 参数: f"LLM深层分析: {results.get('overall_assessment', '')[:500]}"

# 修复: 当 overall_assessment 为空时跳过拼接
overall = results.get('overall_assessment', '')
llm_actions = f"LLM深层分析: {overall[:500]}" if overall else "LLM深层分析: 未获取到有效评估"

# 且只在有实质内容时才拼接
if overall:
    db.query_local("""
        UPDATE conversations SET analyzed = 1, updated_at = ?,
            actions = CASE WHEN actions IS NULL OR actions = '' 
                THEN ? ELSE actions || ' | LLM_DEEP: ' || ? END
        WHERE conversation_id = ?
    """, (datetime.now().isoformat(), llm_actions, summary_stats, conversation_id))
else:
    db.query_local("""
        UPDATE conversations SET analyzed = 1, updated_at = ?
        WHERE conversation_id = ?
    """, (datetime.now().isoformat(), conversation_id))
```

### 4.3 evolution_log 触发路径明确

**现状**: `_log_evolution()` 仅在 `evolution.py` 的 `_upgrade_file()` / `_create_file()` 中调用。这两个方法只有在代码自进化触发时才会执行，而自进化门槛很高，导致表始终为空。

**修复**: 在 `_execute_conversation_finalize()` 的优化建议环节中，当发现可自动执行的优化时写入 evolution_log。

```python
# 在 task_queue.py _execute_conversation_finalize() 中 (L836 附近)
if opt_result.get("auto_applied"):
    db.log_evolution(
        change_type="auto_optimize",
        description=f"对话 {conversation_id} 触发自动优化: {opt_result.get('description')}",
        files_changed=opt_result.get("files", ""),
        version=current_version,
    )
```

### 4.4 improvement_log status 流转

**现状**: 所有记录 status 始终 `pending`，从未流转。

**修复**: 在 `_execute_conversation_finalize()` 末尾追加自动流转逻辑。

```python
# 在 finalize 末尾，将本对话关联的 pending improvement 标记为 reviewed
db.query_local("""
    UPDATE improvement_log SET status = 'reviewed'
    WHERE conversations_id = (
        SELECT id FROM conversations WHERE conversation_id = ?
    ) AND status = 'pending'
""", (conversation_id,))
```

---

## 五、第四层：代码层

> **目标**: 代码级别的细节修复，不改变架构

### 5.1 knowledge_points source_id 统一

**问题**: `source_id` 有时存 `step_id`，有时存 `conversation_id`，格式不统一。

**修复**: 统一使用 `step_id` 作为 `source_type='step'` 的 source_id，`conversation_id` 作为 `source_type='finalize'` 的 source_id。当前代码基本正确，仅需在 `_create_knowledge_point()` 中加断言。

```python
# conversation_manager.py _create_knowledge_point()
assert source_type in ('step', 'finalize', 'manual', 'knowledge_graph'), \
    f"Unknown source_type: {source_type}"
```

### 5.2 knowledge_points usage_count 更新

**问题**: `usage_count` 始终为 0，从未递增。

**修复**: 在 `finalize` 时关联已有知识点时递增。

```python
# task_queue.py _execute_conversation_finalize() 知识图谱环节
for node in nodes:
    existing = db.query_local(
        "SELECT id FROM knowledge_points WHERE title = ?", 
        (node.get("label"),)
    )
    if existing:
        db.query_local("""
            UPDATE knowledge_points SET 
                usage_count = usage_count + 1,
                last_used_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), existing[0]["id"]))
```

### 5.3 task_queue result 回写

**问题**: 任务完成后 `result` 字段未写入数据库。

**修复**: 在 `_process_task()` 的任务完成路径中追加 UPDATE。

```python
# task_queue.py _process_task() (完成路径)
db.query_local("""
    UPDATE task_queue SET 
        status = 'completed',
        result = ?,
        actual_memory_mb = ?,
        completed_at = ?
    WHERE task_id = ?
""", (
    json.dumps(result, ensure_ascii=False),
    get_current_memory_mb(),  # 需要实现或估算
    datetime.now().isoformat(),
    task_id,
))
```

### 5.4 version_history 过滤启动记录

**问题**: 每次服务重启都被记录为版本变更。

**修复**: 在写入 `version_history` 前检查是否真正的版本变更。

```python
# database.py 或 server.py 中写入 version_history 的位置
last_version = db.query_local(
    "SELECT version FROM version_history ORDER BY timestamp DESC LIMIT 1"
)
if last_version and last_version[0]["version"] == current_version:
    # 同版本重启，不记录
    return
# 否则记录真正的版本变更
```

### 5.5 version_history 变更详情填充

**问题**: `diff_detail` / `optimize_point` / `bug_fix` / `new_feature` / `data_change` 五个字段始终为空。

**修复**: 在 `server.py` 记录版本历史时从 CHANGELOG.md 提取结构化信息。

```python
# server.py record_version()
# 解析 CHANGELOG.md 的当前版本条目
changelog_path = Path(__file__).parent / "CHANGELOG.md"
if changelog_path.exists():
    content = changelog_path.read_text(encoding="utf-8")
    # 提取当前版本的 feat/fix/optimize/data 条目
    # ... 解析逻辑
```

---

## 六、第五层：新功能

> **目标**: 用户技能展示增强（最低优先级，待前四层完成后执行）

### 6.1 技能复习提醒

**触发条件**: 知识点 `last_used_at` 超过 7 天未使用。

```
用户打开 IDE → 后台检查 → 发现 7 天未使用的技能 → 推送提醒卡片
```

**实现**:
```python
# 新增 skills/recall_reminder.py
def check_stale_skills(days=7):
    """查找超过 N 天未使用的技能"""
    stale = db.query_local("""
        SELECT skill_domain, last_updated 
        FROM user_skills 
        WHERE last_updated < date('now', ?)
    """, (f'-{days} days',))
    return stale
```

### 6.2 遗忘曲线可视化

**数据基础**: `knowledge_points.usage_count` + `last_used_at` + `created_at`。

**简化实现**:
```python
# 在 growth_analytics.py 中新增
def get_forgetting_curve(domain):
    """返回指定领域的遗忘曲线数据"""
    points = db.query_local("""
        SELECT title, usage_count, 
               julianday('now') - julianday(last_used_at) as days_since_use
        FROM knowledge_points 
        WHERE domain = ? AND usage_count > 0
        ORDER BY days_since_use DESC
    """, (domain,))
    return points
```

### 6.3 知识关联图谱

**数据基础**: `knowledge_points.related_knowledge_ids`。

**简化实现**: 基于共现关系构建关联（同一 conversation 中出现的知识点互相关联）。

```python
# 在 knowledge_graph.py 中新增
def build_cooccurrence_graph(conversation_id):
    """基于共现关系构建知识点关联"""
    # 查找同一次对话中出现的所有知识点
    # 两两建立关联
    # 更新 related_knowledge_ids
```

---

## 七、执行路线图

### 第一阶段（紧急，本周）

| 优先级 | 问题 | 预计工时 | 风险 |
|--------|------|---------|------|
| P0 | 4.1 数据写入修复（knowledge_point_ids/duration_ms/started_at） | 2h | 低 |
| P0 | 3.1 conversation_archive 去留决策 | 0.5h | 低 |
| P1 | 4.2 LLM 分析结果空值修复 | 1h | 低 |

### 第二阶段（重要，下周）

| 优先级 | 问题 | 预计工时 | 风险 |
|--------|------|---------|------|
| P1 | 2.2 生命周期状态机规范 + 兜底实现 | 3h | 中 |
| P1 | 4.3 evolution_log 触发路径明确 | 1h | 低 |
| P1 | 4.4 improvement_log status 流转 | 0.5h | 低 |
| P2 | 5.1-5.2 knowledge_points 数据质量 | 1h | 低 |
| P2 | 5.3 task_queue result 回写 | 1h | 低 |

### 第三阶段（一般，本月）

| 优先级 | 问题 | 预计工时 | 风险 |
|--------|------|---------|------|
| P2 | 2.1 数据库表文档规范（注释） | 2h | 低 |
| P2 | 2.3 improvement_log 定位规范 | 0.5h | 低 |
| P2 | 3.2 缺失字段默认值/约束 | 1h | 低 |
| P2 | 3.3 optimization_feedback 外键简化 | 0.5h | 低 |
| P2 | 5.4 version_history 过滤启动记录 | 0.5h | 低 |
| P2 | 5.5 version_history 变更详情填充 | 2h | 中 |
| P3 | 3.4 索引补充 | 0.5h | 低 |

### 第四阶段（低优先级，下月）

| 优先级 | 问题 | 预计工时 | 风险 |
|--------|------|---------|------|
| P3 | 6.1 技能复习提醒 | 3h | 中 |
| P3 | 6.2 遗忘曲线可视化 | 4h | 中 |
| P3 | 6.3 知识关联图谱 | 5h | 中 |

---

## 八、风险与注意事项

1. **数据完整性**: 修复写入逻辑前先备份 `data/*.db`
2. **向后兼容**: 所有 ALTER TABLE 用 `IF NOT EXISTS` 模式
3. **Ponytail 原则**: 每次改动前问自己 — 标准库能做吗？已有依赖能做吗？能一行搞定吗？
4. **不新增文件**: 除新功能阶段外，所有修复在现有文件中完成
5. **LLM 依赖**: LLM 分析修复依赖模型可用性，模型不可用时降级为规则引擎

---

## 九、Ponytail 审计

| 位置 | 标签 | 说明 |
|------|------|------|
| task_queue.py:L599 | delete | `duration_ms = 0` 硬编码，应计算实际耗时 |
| task_queue.py:L858 | shrink | `actions` 拼接逻辑过度复杂，空值判断可提前 |
| database.py:L406-425 | yagni | 11 次 ALTER TABLE try/except 可合并为循环 |
| database.py:L140-158 | yagni | conversation_archive 表不再写入新数据，标记 deprecated |
| task_queue.py:L711-739 | shrink | 两次 INSERT improvement_log 可合并 |

**净减少**: ~30 行可能（去除冗余 ALTER TABLE 补丁 + 合并重复 INSERT）

---

**维护者**: DevPartner Team | **审查**: 待定 | **下一版**: 根据执行反馈更新
