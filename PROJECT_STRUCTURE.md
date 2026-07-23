# 🗺️ DevPartner 项目导航指南

> **一句话定位**: 本文档帮助你快速找到需要的代码、配置和文档。
> **适用架构**: v9.5.5 分层架构（`foundation/` + `backend/` + `mcp_service/` + `frontend/`）

---

## 🎯 我想要...

### 📖 了解项目？
→ 从这里开始：[README.md](./README.md)
→ 深入架构：[docs/](./docs/)
→ 版本历史：[CHANGELOG.md](./CHANGELOG.md)

### 🚀 快速启动？
→ 5分钟上手：[README.md#快速开始](./README.md#🚀-快速开始)
→ 配置说明：[README.md#高级配置](./README.md#🔧-高级配置)

### 🔧 开发/修改代码？

#### 修改 Prompt 模板（推荐，无需改代码）
```
backend/templates/llm_prompt/   # ⭐ Prompt 独立于代码
├── _common.py              # AnalysisTask 框架
├── daily_summary.py        # 日/周/月/年报 + growth_analysis
├── conversation.py         # 对话分析 Prompt
├── step.py                 # 步骤分析 Prompt
├── user_profile.py         # 用户画像分析 Prompt
└── ...                     # 更多 Prompt 模板
```

#### 修改核心业务逻辑
```
backend/
├── core/conversation_mgr/engine.py    # ⭐ 对话生命周期管理（总分三步走）
├── core/llm_kernel/                   # LLM 推理内核
├── core/scheduler.py                  # 定时调度器
├── business/task_handlers/daily_summary.py  # 日报/周报/月报/年报生成
└── business/                          # 其他业务模块
```

#### 新增 MCP 工具
```
mcp_service/mcp_server.py     # 在 @mcp.tool 中新增工具函数
# 业务实现放在 backend/business/ 或 backend/core/，mcp_server 仅做薄壳转发
```

### 🧪 运行测试？
→ 测试指南：[tests/README.md](./tests/README.md)
→ 执行命令：`pytest tests/ -v`

### 🐛 排查问题？
→ 常见问题：[README.md#故障排查](./README.md#🐛-故障排查)
→ 部署问题：[docker-compose.yml](./docker-compose.yml)

### 📊 监控运维？
→ 运维面板：启动后访问 `http://localhost:7860/dashboard`（`backend/api_gateway/dashboard.html`）
→ API 端点：`/api/system/*`、`/api/tasks/*`、`/api/health/*`、`/api/growth/*`
→ 日志位置：`data/logs/agent.log`
→ 数据库维护：`scripts/check_db_integrity.py`

---

## 📂 目录速查表

| 路径 | 用途 | 重要程度 |
|------|------|---------|
| `/` | 项目根目录 | ⭐⭐⭐ |
| ├─ [README.md](./README.md) | **主文档**（必读） | ⭐⭐⭐⭐⭐ |
| ├─ [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md) | 项目导航 | ⭐⭐⭐⭐ |
| ├─ [CHANGELOG.md](./CHANGELOG.md) | 版本迭代记录 | ⭐⭐⭐⭐ |
| ├─ [main.py](./main.py) | 统一启动入口 | ⭐⭐⭐⭐ |
| │ | | |
| ├─ **mcp_service/** | MCP 薄壳模块（注解暴露工具） | ⭐⭐⭐⭐⭐ |
| │ └─ mcp_server.py | FastMCP 入口 | ⭐⭐⭐⭐⭐ |
| │ | | |
| ├─ **foundation/** | 全局基础框架（与业务解耦） | ⭐⭐⭐⭐⭐ |
| │ ├─ config/config.yaml | 运行时配置 | ⭐⭐⭐⭐ |
| │ ├─ logger_framework/ | 统一日志 | ⭐⭐⭐ |
| │ ├─ trace_tracker/ | 埋点追踪 | ⭐⭐⭐ |
| │ ├─ exception_framework/ | 统一异常 | ⭐⭐⭐ |
| │ ├─ api_response/ | 统一返回体 | ⭐⭐⭐ |
| │ └─ common_utils/ | 通用工具 | ⭐⭐⭐ |
| │ | | |
| ├─ **backend/** | 后端业务层（核心大脑） | ⭐⭐⭐⭐⭐ |
| │ ├─ core/conversation_mgr/ | 对话引擎（总分三步走） | ⭐⭐⭐⭐⭐ |
| │ ├─ core/llm_kernel/ | LLM 推理内核 | ⭐⭐⭐⭐⭐ |
| │ ├─ core/task_queue_kernel/ | 异步任务队列 | ⭐⭐⭐⭐ |
| │ ├─ core/database/ | 数据库连接与 DAO | ⭐⭐⭐⭐ |
| │ ├─ business/system_ops/ | 系统引擎 | ⭐⭐⭐⭐ |
| │ ├─ business/knowledge_extractor/ | 知识引擎 | ⭐⭐⭐⭐ |
| │ ├─ business/vault_export/ | Obsidian 导出 | ⭐⭐⭐ |
| │ ├─ business/analytics/ | 成长分析 | ⭐⭐⭐ |
| │ ├─ business/task_handlers/ | 日报/周报/月报/年报 | ⭐⭐⭐ |
| │ ├─ api_gateway/rest_api.py | REST 路由 | ⭐⭐⭐⭐ |
| │ └─ templates/llm_prompt/ | LLM 提示词模板 | ⭐⭐⭐⭐ |
| │ | | |
| ├─ **frontend/** | 前端（预留，尚未构建） | ⭐ |
| ├─ **scripts/** | 运维脚本 | ⭐⭐⭐ |
| ├─ **tests/** | 测试套件 | ⭐⭐⭐⭐ |
| ├─ **docs/** | 技术文档 | ⭐⭐⭐ |
| ├─ **data/** | 运行时数据（gitignore） | ⭐⭐ |
| ├─ **models/** | LLM 模型文件（gitignore） | ⭐⭐⭐⭐ |
| ├─ docker-compose.yml / Dockerfile | 部署配置 | ⭐⭐⭐⭐ |
| ├─ pyproject.toml | 项目元数据 | ⭐⭐ |
| └─ requirements.txt | 全局依赖 | ⭐⭐ |

---

## 🔍 文件查找指南

### 按功能查找

#### 对话相关
- **记录对话**: `backend/core/conversation_mgr/engine.py` → `start_conversation`
- **记录步骤**: `backend/core/conversation_mgr/engine.py` → `record_step`
- **结束对话**: `backend/core/conversation_mgr/engine.py` → `finalize_conversation`
- **存储对话**: `backend/core/database/base_conn.py`

#### LLM 相关
- **推理服务**: `backend/core/llm_kernel/base_client.py`
- **统一工具**: `backend/core/llm_kernel/llm_utils.py`
- **模型配置**: `foundation/config/config.yaml` → `llm.*`

#### 日报总结
- **生成日报**: `backend/business/task_handlers/daily_summary.py`
- **周/月/年报**: `backend/business/task_handlers/reports.py`
- **数据收集**: `backend/business/task_handlers/daily_summary.py` → `get_daily_work_data()`

#### 用户画像
- **画像构建**: `backend/business/system_ops/` + `backend/core/conversation_mgr/handlers/finalize_user_profile.py`
- **特征融合**: 由 LLM 分析后写入 `user_profile` 表

#### 知识图谱
- **提取**: `backend/business/knowledge_extractor/`
- **导出**: `backend/business/vault_export/`（Obsidian Vault）

#### 数据库
- **CRUD 操作**: `backend/core/database/base_conn.py`
- **Schema 定义**: `scripts/v5.0_schema_upgrade.sql`
- **升级迁移**: `scripts/upgrade_to_v5.py`
- **完整性检查**: `scripts/check_db_integrity.py`

---

## 🎨 代码风格规范

### 导入顺序
```python
# 1. 标准库
import os
import sys
from pathlib import Path

# 2. 第三方库
import yaml

# 3. 本地模块（绝对导入，跨包禁止相对导入）
from backend.core.bootstrap import ensure_ready
from foundation.config.app_settings import get_config
```

### 分层约定
- `foundation/` 不得反向依赖 `backend/` 或 `mcp_service/`
- `backend/core/` 提供底层能力，可被 `backend/business/` 与 `mcp_service/` 复用
- `mcp_service/` 仅做薄壳转发，不含业务逻辑
- `backend/api_gateway/` 通过 REST 暴露业务能力，与 MCP 互不冲突

---

## 🔄 开发工作流

### 日常开发流程
```
1. 创建特性分支
   git checkout -b feature/new-feature

2. 编写代码和测试
   vim backend/business/new_module.py
   vim tests/test_new_module.py

3. 运行测试
   pytest tests/test_new_module.py -v

4. 启动验证
   python main.py 7860

5. 提交代码
   git add .
   git commit -m "feat: add new module for xxx"

6. 推送并创建 PR
```

### Commit Message 规范
```
<type>(<scope>): <subject>

<body>
```
**Type**: `feat` / `fix` / `docs` / `style` / `refactor` / `perf` / `test` / `chore`

---

## ✅ 新人入职清单

1. ☑️ **[README.md](./README.md)** (30分钟) — 了解项目是什么、能做什么
2. ☑️ **[PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)** (本文档，15分钟) — 知道东西在哪
3. ☑️ **[CHANGELOG.md](./CHANGELOG.md)** (15分钟) — 了解版本演进
4. ☑️ **[tests/README.md](./tests/README.md)** (10分钟) — 学会运行测试
5. ☑️ **实际动手** (2-4小时) — 启动服务、运行测试、尝试小改动
6. ☑️ **深入源码** (按需) — 阅读 `backend/core/conversation_mgr/` 理解核心逻辑

**预计总时间**: ~4小时（含实践）

---

**维护者**: DevPartner Team
**适用版本**: v9.5.5（分层架构）
**最后更新**: 2026-07-23
