---
description: 
alwaysApply: false
enabled: false
updatedAt: 2026-07-04T14:35:24.377Z
provider: 
---

# CodeBuddy 任务管道规范 v6.0

## 📋 概述
本规则定义了 CodeBuddy 客户端与 DevPartner 系统交互时的**任务执行流程**和**数据落地规范**。

### 核心原则
- ✅ **唯一标识**：每个对话必须有唯一的 `conversation_id`（UUID格式）
- ✅ **步骤化拆分**：复杂任务必须拆分为可追踪的 `step`
- ✅ **异步优先**：耗时操作（LLM推理、数据分析）必须异步执行
- ✅ **有序落地**：知识点按步骤顺序写入知识库
- ✅ **资源友好**：控制内存占用，避免阻塞客户端交互

---

## ⚡ v6.0 强制约束：总分总 N×Task 模式

### 🚨 硬性要求（AI 每次对话必须遵守）

```
1. 分析用户请求 → 生成 TODO 列表（todo_write）
2. 调用 create_conversation() → 获取 conversation_id
3. 每完成一个 TODO 项 → 立即调用 record_step()（一个子任务 = 一个 step）
4. 所有 TODO 完成后 → 调用 finalize_conversation()
```

### ❌ 严禁行为
- ❌ 整个对话只调用一次 record_dialogue() 替代 N 次 record_step()
- ❌ 等待所有任务完成后再一次性提交
- ❌ 跳过 record_step 直接 finalize
- ❌ 数据截断导致关键信息丢失（v6.0.2: 截断上限提升至 100K/50K 字符）

### ✅ 正确示例
```
对话开始:
  create_conversation(client="codebuddy", topic="修复3个Bug", task_type="debug")
      → conv_abc123

子任务1完成 (修复 LLM 导入路径):
  record_step(conversation_id="conv_abc123", step_name="修复LLM导入路径",
              step_type="debug", content="...", files_changed='["llm_service.py"]')

子任务2完成 (修复记录截断):
  record_step(conversation_id="conv_abc123", step_name="移除数据截断限制",
              step_type="code_change", ...)

子任务3完成 (更新录制规则):
  record_step(conversation_id="conv_abc123", step_name="强制N×Task模式",
              step_type="config", ...)

对话结束:
  finalize_conversation(conversation_id="conv_abc123", summary="...")
```

### 📊 预期效果
- 1 个对话 → 3-7 个 steps（不是 1 个）
- 每个 step 数据量小（<5000 字符），精确且不截断
- 知识图谱按 step 维度构建，更精细

---

## 🔧 对话生命周期管理

### 1️⃣ 创建会话（必选）
```python
# 调用 DevPartner MCP 工具：create_conversation
{
  "client": "codebuddy",
  "topic": "重构数据库Schema",           # 必填：任务主题
  "task_type": "refactoring",              # 可选：general/debugging/refactoring/learning
  "user_intent": "优化表结构并加强外键约束", # 可选：用户意图描述
  "priority": "high"                      # 可选：low/medium/high/critical
}
# 返回值：{"conversation_id": "conv_abc123..."}
```

### 2️⃣ 步骤定义模板（推荐）
将复杂任务拆分为以下标准步骤类型：

| 步骤类型 | 用途 | 示例 | 预估耗时 |
|---------|------|------|----------|
| `analysis` | 对话内容分析 | 提取技能领域/复杂度 | 5-15秒 |
| `knowledge_gen` | 知识点生成 | 从分析结果提取技能点 | 3-10秒 |
| `user_profile` | 用户画像更新 | 更新技能等级/行为模式 | 2-5秒 |
| `system_optimize` | 系统优化建议 | 识别工具缺口/改进方向 | 10-30秒 |
| `data_migration` | 数据迁移 | Schema升级/数据回填 | 30-300秒 |
| `validation` | 数据校验 | 外键完整性检查 | 5-10秒 |

#### 示例：数据库重构任务的步骤定义
```json
[
  {
    "step_type": "analysis",
    "step_name": "分析当前数据库结构",
    "order": 1,
    "input_data": {"content": "用户提供的SQL或表结构描述"},
    "depends_on": []
  },
  {
    "step_type": "knowledge_gen",
    "step_name": "提取设计模式和最佳实践",
    "order": 2,
    "input_data": {},  // 自动从上一步获取 analysis_output
    "depends_on": ["step_001"]
  },
  {
    "step_type": "data_migration",
    "step_name": "执行Schema升级脚本",
    "order": 3,
    "input_data": {"script_path": "v5.0_schema_upgrade.sql"},
    "depends_on": ["step_002"]
  },
  {
    "step_type": "validation",
    "step_name": "验证外键约束和数据完整性",
    "order": 4,
    "input_data": {},
    "depends_on": ["step_003"]
  }
]
```

### 3️⃣ 异步执行协议（强制）

#### ⚠️ 同步调用场景（仅限快速操作）
以下操作可以同步调用：
- ✅ 创建会话 (`create_conversation`) - <100ms
- ✅ 查询状态 (`get_conversation_status`) - <50ms
- ✅ 取消任务 (`cancel_task`) - <50ms
- ✅ 获取知识库列表 (`list_knowledge_points`) - <200ms

#### ⏱️ 异步调用场景（必须使用任务队列）
以下操作**必须**通过 `execute_steps_async` 提交到后台队列：
- ❌ **禁止同步调用**：LLM 推理（`analyze_conversation`, `generate_daily_summary`）
- ❌ **禁止同步调用**：批量数据处理（`migrate_database`, `backfill_data`）
- ❌ **禁止同步调用**：长时间运行的分析任务（>5秒）

##### 正确的异步调用方式
```python
# 步骤1: 创建会话 + 定义步骤
conv_id = create_conversation(...)
step_ids = create_steps(conv_id, step_configs)

# 步骤2: 异步提交（不阻塞！）
task_id = execute_steps_async(conv_id, priority="high")
print(f"📤 任务已提交: {task_id}")
print("💡 你可以继续其他工作，任务将在后台完成...")

# 步骤3: （可选）轮询进度或设置回调
import time
while True:
    status = get_task_status(task_id)
    if status["status"] in ["completed", "failed"]:
        break
    time.sleep(3)  # 每3秒查询一次
    print(f"⏳ 进度: {status.get('progress', 0)}%")
```

---

## 💾 数据落地规范

### 会话记录存储位置
```
data/databases/devpartner.db
├── conversations              # 主会话表（唯一 conversation_id）
├── conversation_steps         # 执行步骤记录（有序）
├── knowledge_points           # 知识库（按步骤落地）
├── task_queue                 # 异步任务状态
├── user_skills                # 用户画像（异步更新）
└── improvement_log            # 优化建议（异步生成）
```

### 知识点落地时机
- ✅ **即时落地**：每个 `knowledge_gen` 步骤完成后立即写入
- ✅ **关联追踪**：知识点必须包含 `source_step_id` 和 `source_conv_id`
- ✅ **版本迭代**：相同主题的知识点应更新版本号，而非重复创建

### 数据完整性保障
1. **外键级联删除**：删除会话时自动清理关联的步骤和知识点
2. **事务保证**：单个步骤的成功/失败原子性更新
3. **幂等性**：重试步骤不会产生重复数据（基于 step_id 唯一性）

---

## ⚠️ 资源使用限制

### 内存占用红线
| 组件 | 正常占用 | 警告阈值 | 上限 |
|------|---------|---------|------|
| 任务队列服务 | ~50MB | >200MB | 512MB |
| 单个 LLM 推理任务 | ~500MB | >800MB | 1.5GB |
| 并发任务总数 | 2个 | >4个 | 6个 |
| 总系统内存 | ~1GB | >2.5GB | 4GB |

### 并发控制策略
- **默认并发数**: 2（为本地系统保守配置）
- **高优先级抢占**: 当 `critical` 任务到达时，可暂停 1 个 `low` 优先级任务
- **超时自动取消**: 单任务超过 5 分钟未完成则终止

---

## 🔄 错误处理与重试

### 失败重试机制
| 重试次数 | 延迟时间 | 触发条件 |
|---------|---------|----------|
| 第1次 | 2秒 | 网络超时/临时错误 |
| 第2次 | 4秒 | LLM 推理失败 |
| 第3次 | 8秒 | 数据库锁定 |
| >3次 | 标记失败 | 持续错误 |

### 错误分类处理
1. **可恢复错误**（网络抖动、临时锁）：自动重试
2. **业务错误**（无效输入、权限不足）：标记失败，通知用户
3. **系统错误**（OOM、磁盘满）：紧急告警，暂停新任务

---

## 🎯 最佳实践清单

### ✅ Do（推荐做法）
- [ ] 每次对话开始时调用 `create_conversation` 获取唯一 ID
- [ ] 将复杂任务拆分为 3-7 个清晰的步骤
- [ ] 所有 LLM 相关操作都使用 `execute_steps_async` 异步提交
- [ ] 在步骤间传递关键数据（如 `analysis_output`）
- [ ] 定期查询 `get_task_status` 监控进度
- [ ] 为重要步骤设置合理的 `timeout_seconds`（默认300秒）
- [ ] 在知识库中查找已有知识点后再创建新的

### ❌ Don't（禁止做法）
- [ ] 不要在主线程中直接调用 LLM 服务（会导致卡顿）
- [ ] 不要忽略 `conversation_id` 的返回值（后续API都需要）
- [ ] 不要创建超过 10 个步骤的单个会话（考虑拆分多个会话）
- [ ] 不要在循环中高频轮询状态（间隔≥3秒）
- [ ] 不要手动拼接 SQL（使用 DevPartner 提供的工具方法）

---

## 📞 故障排查指南

### 常见问题

#### Q1: 任务一直显示 "pending" 不执行？
**原因**: 可能达到并发上限或内存不足。
**解决**: 
1. 调用 `get_queue_stats()` 检查资源使用情况
2. 如果 `running_tasks >= concurrency_limit`，等待当前任务完成
3. 如果 `memory_usage_mb > memory_limit_mb * 0.8`，关闭不必要的应用

#### Q2: 步骤执行失败但重试也不成功？
**原因**: 可能是依赖的前置步骤失败。
**解决**:
1. 查看 `error_message` 字段获取详细错误
2. 检查 `depends_on` 的步骤是否全部 `completed`
3. 手动重新执行失败的独立步骤（`force_retry=True`）

#### Q3: 知识点没有落地到数据库？
**原因**: `knowledge_gen` 步骤可能被跳过或失败。
**解决**:
1. 查询 `SELECT * FROM conversation_steps WHERE conversation_id='xxx' AND step_type='knowledge_gen'`
2. 如果状态是 `skipped`，检查前置条件是否满足
3. 手动触发: `execute_single_step(step_id, force_retry=True)`

---

## 📊 监控指标

CodeBuddy 应定期收集以下指标以评估系统健康度：

- **吞吐量**: 每小时完成的会话数（目标: ≥10 个/小时）
- **延迟 P99**: 从提交到完成的时长（目标: <60 秒）
- **成功率**: 任务成功完成比例（目标: >95%）
- **资源利用率**: 内存/CPU 使用率（目标: <70%）
- **知识沉淀率**: 成功落地的知识点数 / 分析次数（目标: >80%）

---

**最后更新**: 2026-07-02  
**适用版本**: DevPartner v5.0+  
**维护者**: DevPartner Team