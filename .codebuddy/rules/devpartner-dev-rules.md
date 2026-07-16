# DevPartner 开发规则 v7.0

> **融合**: Ponytail 开发哲学 + 12 类审计经验 + DevPartner 项目规范  
> **适用范围**: DevPartner 项目所有代码变更  
> **核心理念**: **最短路径即正确路径** — 用最少的代码解决问题，删除优于添加，无聊胜过聪明

---

## 一、Ponytail YAGNI 梯子（决策框架）

> **来源**: Ponytail 规则 | **优先级**: 每次写代码前执行

按顺序执行，**前两步有效就停止**：

1. **不需要？不构建** — 真的需要这个功能吗？
2. **标准库能做？用标准库** — `functools.lru_cache` 胜过自定义缓存
3. **Python 原生功能？用原生** — `dataclasses` 胜过手写 DTO
4. **已有依赖能解决？用它** — 不为新功能引入新依赖
5. **能写成一行？一行搞定**
6. **最后手段**：写最少能工作的代码

### 重要前提
- 梯子在**理解问题之后**运行，而非替代理解
- 先完整阅读任务和相关代码，追踪实际流程

### 输出格式
```
[代码] → 跳过: [X], 当 [Y] 时添加。
```

---

## 二、数据库设计规范（审计沉淀）

> **来源**: 审计问题 #1-3, #8-10 | **优先级**: 涉及 Schema 变更时强制执行

### 2.1 表文档（必须）

每张 CREATE TABLE 前必须有多行注释：

```sql
-- ============================================================
-- 表名: conversations
-- 用途: 核心对话记录表，存储每次对话的元信息
-- 字段:
--   id               INTEGER  自增主键
--   conversation_id  TEXT     全局唯一对话标识（UUID）
--   timestamp        TEXT     对话创建时间（ISO 8601）
--   client           TEXT     客户端标识（codebuddy/trae/...）
--   topic            TEXT     对话主题
--   task_type        TEXT     任务类型（debug/design/code_change/...）
--   actions          JSON     对话中执行的操作摘要
--   analyzed         INTEGER  是否已完成 LLM 分析（0/1）
-- ============================================================
```

### 2.2 字段约束（必须）

- 所有字段必须有 **DEFAULT 值**，避免 NULL 污染
- 时间字段统一 **ISO 8601 格式** TEXT 存储
- JSON 字段默认值统一 `'{}'` 或 `'[]'`，不存 NULL
- 外键用 INTEGER 引用 `id`，不用 TEXT 引用 `conversation_id`

### 2.3 生命周期状态机（必须）

所有带 `status` 字段的表必须定义完整状态机：

```
pending → in_progress → completed / failed / timeout
                           ↓
                       archived (30天后)
```

**兜底政策**（必须实现）：
- `pending` 超过 **24h** → 标记为 `orphaned`
- `in_progress` 超过 **10min** → 回退为 `pending`
- `failed` 超过最大重试 → 永久 `failed`
- `orphaned` 超过 **30 天** → 可归档

### 2.4 废弃字段管理

废弃字段不立即删除，用注释标记：

```sql
-- @deprecated v6.0: 总分总架构后不再使用，保留仅用于历史数据查询
-- 计划移除: v8.0
```

### 2.5 ALTER TABLE 补丁模式

> **审计发现**: 11 次重复的 `ALTER TABLE ADD COLUMN try/except`

**规则**: 使用循环合并，避免重复代码：

```python
# ✅ 正确：循环合并
ALTER_COLUMNS = {
    "conversation_steps": [
        ("knowledge_point_ids", "TEXT DEFAULT '[]'"),
        ("duration_ms", "INTEGER DEFAULT 0"),
    ],
    "task_queue": [
        ("actual_memory_mb", "REAL DEFAULT 0"),
    ],
}
for table, columns in ALTER_COLUMNS.items():
    for col_name, col_def in columns:
        try:
            db.query_local(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # 列已存在
```

### 2.6 外键规范

- 一张表只保留 **一个** 外键指向同一父表
- 发现双外键（如 `conversation_id` + `conversations_id`）→ 保留 INTEGER FK，TEXT 标记 deprecated

---

## 三、数据写入完整性规范（审计沉淀）

> **来源**: 审计问题 #4, #5, #11 | **优先级**: 涉及数据库写入时强制执行

### 3.1 INSERT 后必须确认写入

每次 INSERT/UPDATE 后，所有声明字段必须实际写入值。**禁止**：
- `duration_ms = 0` 硬编码
- `knowledge_point_ids` 字段存在但不回写
- `started_at` 字段声明但不设置
- `result` 字段存在但任务完成后不写入

### 3.2 LLM 输出空值守卫

> **审计发现**: `"LLM深层分析: "` 后跟空字符串

**规则**: 所有 LLM 输出拼接前必须判空：

```python
# ✅ 正确
overall = results.get('overall_assessment', '')
if overall:
    actions = f"LLM深层分析: {overall[:500]}"
else:
    actions = "LLM深层分析: 未获取到有效评估"
```

### 3.3 时间字段自动计算

- `duration_ms` = `(completed_at - started_at).total_seconds() * 1000`
- `started_at` = 任务被 Worker 拾取时的时间戳
- `completed_at` = 任务执行完成时的时间戳
- **禁止**硬编码时间差

---

## 四、代码组织规范

> **来源**: 项目规则 + Trae 项目结构规范 | **优先级**: 新增文件时强制执行

### 4.1 目录职责（SRP）

```
devpartner_agent/    → 核心业务逻辑（大脑）
devpartner_tools/    → MCP 工具实现（手部）
server.py            → 服务入口（脊髓）
tests/               → 质量保障（眼睛）
scripts/             → 运维工具（工具箱）
```

### 4.2 层次结构

```
核心层 (core/) → 服务层 (services/) → 技能层 (skills/)
    ↓              ↓                ↓
引擎能力      业务编排        场景封装
```

**禁止反向依赖**：skills 不能直接 import core，services 不能 import skills

### 4.3 命名一致性

| 类型 | 规范 | 示例 |
|------|------|------|
| 目录 | 小写 + 下划线 | `conversation_analyzer` |
| 文件 | 小写 + 下划线 | `llm_service.py` |
| 类名 | 大驼峰 | `LLMUnifiedAnalyzer` |
| 函数/变量 | 小写 + 下划线 | `analyze_conversation` |
| 常量 | 全大写 + 下划线 | `MAX_TOKENS` |

### 4.4 导入顺序（强制）

```python
# 1. 标准库
import os
import sys
from datetime import datetime
from typing import Optional, Dict, List

# 2. 第三方库
import yaml
import llama_cpp
from fastapi import FastAPI

# 3. 本地模块
from devpartner_agent.core.config import Config
from devpartner_agent.core.database import get_db
from devpartner_agent.services.llm_service import LLMService
from devpartner_tools.tools.filesystem import FilesystemTool
```

### 4.5 类组织结构

```python
class MyService:
    """类文档字符串"""

    # ===== 类属性 =====
    _instance = None

    # ===== 魔法方法 =====
    def __init__(self): ...

    # ===== 公共方法 =====
    def public_method(self): ...

    # ===== 受保护方法（内部使用）=====
    def _protected_method(self): ...

    # ===== 静态方法/类方法 =====
    @staticmethod
    def static_method(): ...
```

---

## 五、禁止事项

> **来源**: Ponytail 规则 + 审计经验

### 5.1 Ponytail 禁止

- ❌ **不请求的抽象**：单实现的接口、单产品的工厂、永不改变的配置
- ❌ **样板代码**、"为以后准备的脚手架"
- ❌ **过度聪明的代码**（凌晨 3 点没人能看懂的逻辑）

### 5.2 项目结构禁止

- ❌ 测试代码混入业务模块（测试必须在 `tests/`）
- ❌ 配置文件散落各处（统一 `config.yaml` + 环境变量）
- ❌ 工具代码放在 agent 中（工具必须在 `devpartner_tools/tools/`）
- ❌ 文档散落在根目录（只保留 `README.md` + `CHANGELOG.md`）

### 5.3 数据写入禁止

- ❌ 硬编码 `duration_ms = 0`
- ❌ INSERT 时遗漏已声明字段
- ❌ LLM 输出不经空值守卫直接拼接
- ❌ `usage_count` 创建后永不递增
- ❌ `status` 始终 `pending` 不流转

---

## 六、版本记录规范

> **来源**: 审计问题 #12 | **优先级**: 服务启动时强制执行

### 6.1 版本变更记录

- **同版本重启** → 不记录 `version_history`
- **真正版本变更** → 记录并从 `CHANGELOG.md` 提取变更详情

```python
# ✅ 正确
last = db.query_local("SELECT version FROM version_history ORDER BY timestamp DESC LIMIT 1")
if last and last[0]["version"] == current_version:
    return  # 同版本重启，跳过
# 否则记录真正的版本变更
```

### 6.2 Commit Message 规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

| Type | 说明 | 使用场景 |
|------|------|---------|
| `feat` | 新功能 | 新增分析方法、工具、API |
| `fix` | Bug 修复 | 修复崩溃、数据错误、性能问题 |
| `docs` | 文档变更 | 更新 README、CHANGELOG、注释 |
| `refactor` | 重构 | 结构优化但不改变行为 |
| `perf` | 性能优化 | 加速查询、减少内存占用 |
| `test` | 测试相关 | 新增测试用例、修复测试 |
| `chore` | 构建/依赖 | 更新 requirements、配置调整 |

| Scope | 对应模块 |
|-------|---------|
| `agent` | devpartner_agent 整体 |
| `core` | devpartner_agent/core/ |
| `services` | devpartner_agent/services/ |
| `skills` | devpartner_agent/skills/ |
| `tools` | devpartner_tools/tools/ |
| `server` | server.py |
| `tests` | tests/ |
| `docs` | docs/ |

---

## 七、代码审查规则（Ponytail Review）

> **来源**: Ponytail 规则 | **目标**: 专门查找过度工程化

### 7.1 审查标签

| 标签 | 含义 | 替代方案 |
|------|------|---------|
| `delete` | 死代码、未使用的灵活性 | 无替代 |
| `stdlib` | 手写的标准库已有功能 | 命名标准库函数 |
| `native` | 依赖做了平台原生的事 | 命名原生特性 |
| `yagni` | 单实现抽象、无人设置的配置 | 内联直到第 2 个出现 |
| `shrink` | 相同逻辑更少行数 | 展示简短形式 |

### 7.2 格式

```
L<行号>: <标签> <要删的内容>. <替代方案>.
```

### 7.3 本项目的已知债务

```
task_queue.py:L599     delete   duration_ms = 0 硬编码，应计算实际耗时
task_queue.py:L858     shrink   actions 拼接逻辑过度复杂，空值判断可提前
database.py:L406-425   yagni    11 次 ALTER TABLE try/except 可合并为循环
database.py:L140-158   yagni    conversation_archive 表不再写入新数据，标记 deprecated
task_queue.py:L711-739 shrink   两次 INSERT improvement_log 可合并
```

---

## 八、有意简化标记

> **来源**: Ponytail 规则 | **格式**: `# ponytail: <上限>, <升级路径>`

**示例**：
```python
cache = {}  # ponytail: 1000条, 当内存>500MB 时换 lru_cache
```

**没有升级路径的标记** = `no-trigger`（静默腐烂风险），必须标注。

---

## 九、绝不简化的事项

> **来源**: Ponytail 规则

- ✅ 信任边界的输入验证
- ✅ 防止数据丢失的错误处理
- ✅ 安全措施
- ✅ 用户明确要求的功能

**绝不偷懒的场景**：
- **理解问题**：先完整阅读再动手
- **Bug 修复**：修复根因而非症状（grep 所有调用者）
- **非平凡逻辑**：必须留下一个可运行的检查（assert 或测试）

---

## 十、提交前检查清单

### Ponytail 检查（优先级最高）
- [ ] 这个改动真的需要吗？（YAGNI 梯子 1-3 步试过了吗？）
- [ ] 能用标准库/已有依赖替代吗？
- [ ] 有可以删除的代码吗（旧实现、注释掉的代码、死分支）？
- [ ] 有意简化是否标记了 `# ponytail:` 注释？

### 数据库检查
- [ ] 新表有完整 COMMENT 注释？
- [ ] 所有字段有 DEFAULT 值？
- [ ] 带 status 字段的表有完整状态机？
- [ ] 废弃字段/表标记了 `@deprecated`？

### 数据完整性检查
- [ ] INSERT 的字段全部实际写入？
- [ ] 时间字段使用 `datetime.now().isoformat()`？
- [ ] LLM 输出有判空守卫？
- [ ] `duration_ms` 是计算值而非硬编码？

### 代码质量检查
- [ ] 文件在正确的目录中
- [ ] 导入顺序符合规范
- [ ] 类和函数都有 docstring
- [ ] 类型注解完整（Python 3.10+）

### 测试
- [ ] 核心业务逻辑有对应测试
- [ ] `pytest tests/ -v` 全部通过

### Git
- [ ] Commit message 符合 `<type>(<scope>): <subject>` 格式
- [ ] 没有 `data/`, `models/` 等敏感文件被提交

---

## 十一、表分工速查

> **来源**: 审计问题 #7 | **审计发现**: improvement_log / optimization_feedback 定位混乱

| 表 | 定位 | 数据来源 | 示例 |
|----|------|---------|------|
| `conversations` | 对话主记录 | 每次对话开始 | "修复 server.py 的 3 个 Bug" |
| `conversation_steps` | 对话步骤 | 每个子任务 | "修复导入路径" |
| `knowledge_points` | 知识沉淀 | LLM 分析提取 | "Python 相对导入 vs 绝对导入" |
| `improvement_log` | **系统自改进** | AI 分析生成 | "系统缺少 XX 能力" |
| `optimization_feedback` | **用户反馈** | 用户主动提交 | "记录太冗长" |
| `evolution_log` | **代码自进化** | 自动优化触发 | "自动修复了 YY 逻辑" |
| `task_queue` | 异步任务调度 | Worker 调度 | step_analysis / conversation_finalize |
| `user_skills` | 用户技能画像 | LLM 画像分析 | "Python: demonstrated" |
| `meta` | 系统元信息 | 系统初始化 | schema_version |
| `version_history` | 版本变更记录 | 真正的版本升级 | v5.0 → v6.0 |

---

## 十二、LLM 分析流水线速查

```
create_conversation()
       ↓
record_step() ──→ task_queue (FIFO)
       ↓              ↓
       │        Worker 拾取
       │              ↓
       │    _execute_step_analysis()    ← 分步分析
       │       ├─ LLM 推理
       │       ├─ 知识提取 → knowledge_points
       │       ├─ 技能更新 → user_skills
       │       └─ 回写 conversation_steps (knowledge_point_ids / duration_ms)
       ↓
finalize_conversation()
       ↓
task_queue ──→ Worker 拾取
       ↓
_execute_conversation_finalize()    ← 全局总结
  ├─ 对话总结 + actions 回写
  ├─ 用户画像更新 (9维)
  ├─ 知识图谱构建
  ├─ improvement_log 状态流转 (pending → reviewed)
  ├─ 优化建议 (→ evolution_log 如有自动应用)
  └─ usage_count 递增
```

---

**维护者**: DevPartner Team  
**创建日期**: 2026-07-08  
**融合来源**: Ponytail v3.0 + DevPartner 项目规则 v6.0 + 12 类审计问题  
**适用版本**: DevPartner v6.0+
