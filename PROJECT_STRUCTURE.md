# 🗺️ DevPartner 项目导航指南

> **一句话定位**: 本文档帮助你快速找到需要的代码、配置和文档。

---

## 🎯 我想要...

### 📖 了解项目？
→ 从这里开始：[README.md](./README.md)  
→ 深入架构：[docs/](./docs/)  
→ 版本历史：[CHANGELOG.md](./CHANGELOG.md)

### 🚀 快速启动？
→ 5分钟上手：[README.md#快速开始](./README.md#🚀-快速开始)  
→ 配置说明：[README.md#高级配置](./README.md#🔧-高级配置)  
→ 部署生产：[deploy/README.md](./deploy/README.md)

### 🔧 开发/修改代码？

#### 修改核心业务逻辑
```
devpartner_agent/
├── core/llm_unified_analyzer.py   # ⭐ LLM 统一引擎（最核心）
├── services/conversation_analyzer.py  # 对话分析
└── services/daily_summary.py          # 日报生成
```

#### 新增 MCP 工具
```
devpartner_tools/tools/
├── filesystem.py        # 文件操作示例
├── git_operations.py    # Git 操作示例
└── [你的新工具].py      # 在此添加
```

#### 调整分析规则（无需改代码！）
```yaml
# 编辑 devpartner_agent/config.yaml 的 llm 部分
# 或修改 core/llm_unified_analyzer.py 中的 Prompt 模板
```

### 🧪 运行测试？
→ 测试指南：[tests/README.md](./tests/README.md)  
→ 执行命令：`pytest tests/ -v`

### 🐛 排查问题？
→ 常见问题：[README.md#故障排查](./README.md#🐛-故障排查)  
→ 详细诊断：[docs/troubleshooting.md](./docs/troubleshooting.md)  
→ 部署问题：[deploy/README.md#故障排查](./deploy/README.md#🐛-故障排查)

### 📊 监控运维？
→ Web Dashboard: http://localhost:8082  
→ 日志位置：`data/logs/agent.log`  
→ 数据库维护：`scripts/check_db_integrity.py`

---

## 📂 目录速查表

| 路径 | 用途 | 重要程度 |
|------|------|---------|
| `/` | 项目根目录 | ⭐⭐⭐ |
| ├─ [README.md](./README.md) | **主文档**（必读） | ⭐⭐⭐⭐⭐ |
| ├─ [CHANGELOG.md](./CHANGELOG.md) | 版本迭代记录 | ⭐⭐⭐⭐ |
| ├─ [server.py](./server.py) | 启动入口 | ⭐⭐⭐⭐ |
| │ | | |
| ├─ **devpartner_agent/** | 核心系统（大脑） | ⭐⭐⭐⭐⭐ |
| │ ├─ core/ | 核心引擎层 | ⭐⭐⭐⭐⭐ |
| │ │ └─ llm_unified_analyzer.py | LLM 统一引擎 | ⭐⭐⭐⭐⭐ |
| │ ├─ services/ | 业务服务层 | ⭐⭐⭐⭐ |
| │ ├─ skills/ | 技能模块 | ⭐⭐⭐ |
| │ └─ config.yaml | Agent 配置 | ⭐⭐⭐⭐ |
| │ | | |
| ├─ **devpartner_tools/** | 工具集（手部） | ⭐⭐⭐⭐ |
| │ └─ tools/ | 具体工具实现 | ⭐⭐⭐ |
| │ | | |
| ├─ **scripts/** | 运维脚本 | ⭐⭐⭐ |
| │ ├─ upgrade_to_v5.py | 数据库升级 | ⭐⭐⭐ |
| │ └─ backfill_conversation.py | 数据回填 | ⭐⭐ |
| │ | | |
| ├─ **tests/** | 测试套件 | ⭐⭐⭐⭐ |
| │ └─ README.md | 测试指南 | ⭐⭐⭐ |
| │ | | |
| ├─ **docs/** | 技术文档 | ⭐⭐⭐ |
| │ ├─ architecture.md | 架构设计 | ⭐⭐⭐ |
| │ └─ troubleshooting.md | 故障排查 | ⭐⭐⭐ |
| │ | | |
| ├─ **deploy/** | 部署配置 | ⭐⭐⭐⭐ |
| │ ├─ Dockerfile | 容器定义 | ⭐⭐⭐ |
| │ ├─ docker-compose.yml | 编排配置 | ⭐⭐⭐ |
| │ └─ README.md | 部署指南 | ⭐⭐⭐⭐ |
| │ | | |
| ├─ **data/** | 运行时数据 | ⭐⭐ (gitignore) |
| │ ├─ databases/ | SQLite 数据库 | ⭐⭐ |
| │ ├─ logs/ | 日志文件 | ⭐⭐ |
| │ └─ reports/ | 生成的报告 | ⭐ |
| │ | | |
| └─ **models/** | LLM 模型文件 | ⭐⭐⭐⭐ (gitignore) |

---

## 🔍 文件查找指南

### 按功能查找

#### 对话相关
- **记录对话**: `services/conversation_manager.py`
- **分析对话**: `core/llm_unified_analyzer.py` → `analyze_conversation()`
- **存储对话**: `core/database.py` → `archive_conversation()`

#### LLM 相关
- **推理服务**: `services/llm_service.py`
- **统一分析**: `core/llm_unified_analyzer.py`
- **模型配置**: `config.yaml` → `llm.*`

#### 日报总结
- **生成日报**: `skills/daily_summary.py`
- **LLM 生成**: `core/llm_unified_analyzer.py` → `generate_daily_summary()`
- **数据收集**: `skills/daily_summary.py` → `get_daily_work_data()`

#### 自我优化
- **触发迭代**: `skills/self_iterate.py`
- **建议生成**: `core/llm_unified_analyzer.py` → `generate_self_improvements()`
- **应用改进**: `services/optimization_loop.py`

#### 用户画像
- **画像构建**: `services/user_profile_service.py`
- **特征融合**: `core/llm_unified_analyzer.py` → `apply_user_traits()`
- **存储画像**: `core/database.py` → `upsert_user_skills()`

#### MCP 工具
- **文件操作**: `tools/filesystem.py`
- **Git 操作**: `tools/git_operations.py`
- **HTTP 请求**: `tools/web_requests.py`
- **系统命令**: `tools/system_utils.py`
- **逻辑推理**: `tools/reasoning.py`

#### 数据库
- **CRUD 操作**: `core/database.py`
- **Schema 定义**: `scripts/v5.0_schema_upgrade.sql`
- **升级迁移**: `scripts/upgrade_to_v5.py`
- **完整性检查**: `_check_db.py` (在 tests/)

---

## 🎨 代码风格规范

### 命名约定
```python
# 类名: 大驼峰
class LLMUnifiedAnalyzer:
    pass

# 函数/方法: 小驼峰 + 下划线
def analyze_conversation(content: str) -> dict:
    pass

# 变量: 小写 + 下划线
user_traits = {}
skill_domains = []

# 常量: 全大写 + 下划线
MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.3

# 私有属性: 单下划线前缀
def _infer(self, prompt: str):
    pass
```

### 注释规范
```python
def function_name(param1: type, param2: type) -> return_type:
    """
    函数简短描述（一行）
    
    详细说明（多行，解释实现细节、注意事项等）
    
    Args:
        param1: 参数1说明
        param2: 参数2说明
        
    Returns:
        返回值说明
        
    Raises:
        ExceptionType: 异常情况说明
        
    Example:
        >>> result = function_name("test", 123)
        >>> print(result)
    """
    pass
```

### 导入顺序
```python
# 1. 标准库
import os
import sys
from datetime import datetime
from typing import Optional, Dict, List

# 2. 第三方库
import yaml
import llama_cpp

# 3. 本地模块
from devpartner_agent.core.config import Config
from devpartner_agent.core.database import get_db
```

---

## 🔄 开发工作流

### 日常开发流程
```
1. 创建特性分支
   git checkout -b feature/new-feature

2. 编写代码和测试
   vim devpartner_agent/core/new_module.py
   vim tests/test_new_module.py

3. 运行测试
   pytest tests/test_new_module.py -v

4. 提交代码
   git add .
   git commit -m "feat: add new module for xxx"

5. 推送并创建 PR
   git push origin feature/new-feature
   # 在 GitHub 创建 Pull Request
```

### Commit Message 规范
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type 类型**:
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档变更
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构（非新功能、非修复）
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具链变更

**示例**:
```
feat(llm): add database schema analysis method

Implement analyze_database_schema() in LLMUnifiedAnalyzer
to replace hardcoded validation logic in upgrade scripts.

Closes #123
```

---

## 📞 快速联系

| 场景 | 联系方式 |
|------|---------|
| Bug 反馈 | [GitHub Issues](https://github.com/your-repo/issues) |
| 功能建议 | [GitHub Discussions](https://github.com/your-repo/discussions) |
| 安全漏洞 | security@example.com (加密邮件) |
| 一般咨询 | devpartner@example.com |

---

## ✅ 新人入职清单

如果你是刚加入项目的新开发者，请按以下顺序阅读：

1. ☑️ **[README.md](./README.md)** (30分钟)
   - 了解项目是什么、能做什么
   
2. ☑️ **[PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)** (本文档，15分钟)
   - 知道东西在哪、怎么找

3. ☑️ **[CHANGELOG.md](./CHANGELOG.md)** (15分钟)
   - 了解版本演进和重要变更

4. ☑️ **[tests/README.md](./tests/README.md)** (10分钟)
   - 学会运行测试

5. ☑️ **[deploy/README.md](./deploy/README.md)** (20分钟)
   - 能够本地部署运行

6. ☐ **实际动手** (2-4小时)
   - 启动服务、运行测试、尝试小改动

7. ☐ **深入源码** (按需)
   - 阅读 `core/llm_unified_analyzer.py` 理解核心逻辑
   - 阅读 `services/` 理解业务流程

**预计总时间**: ~4小时（含实践）

---

**维护者**: DevPartner Team  
**创建日期**: 2026-07-03  
**适用版本**: v5.2+  
**最后更新**: 2026-07-03