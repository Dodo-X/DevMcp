# DevPartner 项目结构规范 - CodeBuddy 规则

> **适用范围**: CodeBuddy 环境下的所有开发活动  
> **版本**: v5.2.0 | **最后更新**: 2026-07-03

---

## 📋 核心原则

### 1️⃣ 模块化架构 (Modular Architecture)
项目采用**三层分离**设计：
```
┌─────────────────────────────────────┐
│         devpartner_agent/           │  ← 决策层（大脑）
│  core/ → services/ → skills/       │     引擎 → 服务 → 技能
└─────────────────────────────────────┘
              ↓ 调用
┌─────────────────────────────────────┐
│        devpartner_tools/            │  ← 执行层（手部）
│         tools/                      │     具体工具实现
└─────────────────────────────────────┘
```

### 2️⃣ 关注点分离 (Separation of Concerns)
- **核心逻辑** (`agent/`): 业务规则、数据分析、LLM 推理
- **工具实现** (`tools/`): 文件操作、Git、HTTP、系统命令
- **质量保障** (`tests/`): 单元测试、集成测试、性能测试
- **部署运维** (`deploy/`): Docker、配置、环境管理

### 3️⃣ 约定优于配置 (Convention over Configuration)
遵循标准 Python 项目结构，减少配置开销：
```
✅ 推荐: tests/test_xxx.py（自动发现）
❌ 避免: 自定义测试路径需要额外配置
```

---

## 🎯 标准化目录树（强制执行）

### 顶级目录规范
```
devPartner/
│
├── 📄 README.md                   # [必须] 项目主文档
├── 📄 CHANGELOG.md                # [必须] 版本迭代记录
├── 📄 PROJECT_STRUCTURE.md        # [推荐] 项目导航地图
├── 🚀 server.py                   # [必须] 启动入口
├── ⚙️ .gitignore                  # [必须] Git 忽略规则
├── 📦 pyproject.toml              # [必须] 项目元数据
│
├── 🧠 devpartner_agent/           # [必须] 核心 Agent 系统
│   ├── core/                      # [强制] 核心引擎
│   ├── services/                  # [强制] 业务服务
│   ├── skills/                    # [强制] 技能模块
│   ├── config.yaml                # [强制] 配置文件
│   └── requirements.txt           # [强制] 依赖列表
│
├── 🔧 devpartner_tools/           # [必须] MCP 工具集
│   └── tools/                     # [强制] 工具实现
│
├── 🧪 tests/                      # [必须] 测试套件
│   └── README.md                  # [推荐] 测试指南
│
├── 📚 docs/                       # [必须] 技术文档
│
├── 🐳 deploy/                     # [必须] 部署配置
│   ├── Dockerfile                 # [推荐]
│   ├── docker-compose.yml         # [推荐]
│   └── README.md                  # [推荐] 部署指南
│
├── 💾 data/                       # [必须] 运行时数据
│   └── databases/                 # SQLite 数据库
│
└── 🤖 models/                     # [可选] LLM 模型文件
    └── *.gguf                     # GGUF 格式模型
```

---

## 📐 详细模块规范

### devpartner_agent/ - 核心引擎层

#### `core/` 目录（基础设施）
```python
# 必须包含的核心组件：
core/
├── __init__.py                    # 包初始化
├── config.py                      # 配置管理器（单例）
├── database.py                    # 数据库连接池（单例）
├── llm_unified_analyzer.py        # ⭐ LLM 统一分析引擎（核心！）
├── identity.py                    # 系统身份标识
├── evolution.py                   # 进化机制
├── rule_engine.py                 # 规则引擎（降级方案）
├── tool_registry.py               # 工具注册中心
├── capabilities.py                # 能力声明
└── approval_chain.py              # 审批链路
```

**职责边界**:
- ✅ **允许**: 底层抽象、通用工具、单例服务
- ❌ **禁止**: 具体业务逻辑、UI 相关代码、HTTP 路由

#### `services/` 目录（业务编排）
```python
# 服务层的组织原则：
services/
├── conversation_analyzer.py       # 对话分析服务
├── conversation_analyzer_v2.py    # LLM 驱动版（v6.0）
├── llm_service.py                 # LLM 推理服务封装
├── daily_summary.py               # 日报生成服务
├── dialogue_service.py            # 对话记录服务
├── user_profile_service.py        # 用户画像服务
├── knowledge_graph.py             # 知识图谱服务
├── log_service.py                 # 日志服务
├── file_watcher.py                # 文件监控服务
├── discovery_service.py           # MCP 发现服务
├── optimization_loop.py            # 优化循环控制
├── task_queue.py                  # 任务队列管理
├── ai_optimizer.py                # AI 优化器
├── auto_analyzer.py               # 自动分析器
├── callback_registry.py           # 回调注册表
├── cleanup_scheduler.py           # 清理调度器
└── data_integrity.py              # 数据完整性检查
```

**职责边界**:
- ✅ **允许**: 业务流程编排、数据处理、外部服务调用
- ❌ **禁止**: 直接的数据库 CRUD（应委托给 core/database.py）、底层算法实现

#### `skills/` 目录（场景封装）
```python
# 技能模块的定义标准：
skills/
├── __init__.py
├── daily_summary.py               # 每日总结技能
│   ├── get_daily_work_data()      # 数据收集
│   └── generate_report()          # 报告生成
│
└── self_iterate.py                # 自我迭代技能
    ├── collect_system_data()      # 系统数据收集
    ├── generate_suggestions()     # 建议生成
    └── apply_improvements()       # 改进应用
```

**职责边界**:
- ✅ **允许**: 高层业务场景、用户触发的工作流
- ❌ **禁止**: 基础设施代码、通用工具函数

---

### devpartner_tools/ - 工具集层

#### `tools/` 目录（MCP 工具实现）
```python
# 每个 tool 文件的标准结构：
tools/
├── filesystem.py                  # 文件系统工具
│   ├── read_file()                # 读文件
│   ├── write_file()               # 写文件
│   ├── search_content()           # 搜索内容
│   └── list_directory()           # 列目录
│
├── git_operations.py              # Git 操作工具
│   ├── git_status()               # 状态查询
│   ├── git_commit()               # 提交代码
│   ├── git_branch()               # 分支管理
│   └── git_diff()                 # 差异对比
│
├── web_requests.py                # HTTP 请求工具
│   ├── fetch_url()                # GET 请求
│   ├── post_url()                 # POST 请求
│   └── download_file()            # 文件下载
│
├── system_utils.py                # 系统工具
│   ├── execute_command()          # 执行命令
│   ├── get_system_info()          # 系统信息
│   └── check_process()            # 进程检查
│
├── reasoning.py                   # 推理增强工具
│   ├── logical_analysis()         # 逻辑分析
│   └── chain_of_thought()         # 思维链
│
└── mcp_discovery.py               # MCP 发现工具
    ├── list_available_tools()     # 列出可用工具
    └── get_tool_schema()          # 获取工具 Schema
```

**工具开发规范**:
1. 每个工具独立一个文件
2. 函数必须有类型注解和 docstring
3. 错误处理要完善（try-except + 日志）
4. 支持异步调用（async/await）

---

## 🚫 违规模式检测（Anti-Patterns）

### ❌ 常见错误示例

#### 错误 1: 循环依赖
```python
# ❌ 错误：services 导入 tools
# devpartner_agent/services/conversation_analyzer.py
from devpartner_tools.tools.filesystem import read_file  # 禁止！

# ✅ 正确：通过接口解耦
# 应使用依赖注入或在运行时动态加载
```

#### 错误 2: 测试位置错误
```python
# ❌ 错误：测试混入业务代码
devpartner_agent/services/
├── conversation_analyzer.py
└── test_conversation_analyzer.py  # 禁止！

# ✅ 正确：测试在独立目录
tests/
└── test_conversation_analyzer.py
```

#### 错误 3: 配置散落
```python
# ❌ 错误：多个配置文件
devpartner_agent/config.yaml
devpartner_agent/config_dev.yaml    # 禁止！
devpartner_agent/config_prod.yaml   # 禁止！

# ✅ 正确：单一配置 + 环境变量
devpartner_agent/config.yaml        # 唯一配置源
# 环境差异通过环境变量覆盖
```

#### 错误 4: 文档碎片化
```python
# ❌ 错误：根目录大量 md 文件
devPartner/
├── README.md
├── USAGE.md           # 禁止！合并到 README
├── INSTALL.md         # 禁止！合并到 README
├── API.md             # 禁止！移到 docs/
├── DEPLOY.md          # 禁止！移到 deploy/
└── FAQ.md             # 禁止！合并到 README
```

---

## ✅ CodeBuddy 特定工作流

### 场景 1: 新功能开发
```
用户: "我想添加一个新的分析功能"

CodeBuddy 执行步骤：
1. 确认功能归属
   ├─ 是核心引擎？ → devpartner_agent/core/
   ├─ 是业务服务？ → devpartner_agent/services/
   ├─ 是技能场景？ → devpartner_agent/skills/
   └─ 是 MCP 工具？ → devpartner_tools/tools/

2. 创建文件模板
   - 添加 docstring（说明职责）
   - 定义类/函数签名（带类型注解）
   - 实现基础框架

3. 编写对应测试
   - 在 tests/ 下创建 test_xxx.py
   - 至少覆盖正常路径和异常路径

4. 更新文档
   - 如修改 API → 更新 README.md
   - 如破坏性变更 → 记录到 CHANGELOG.md
```

### 场景 2: Bug 修复
```
用户: "对话分析结果不准确"

CodeBuddy 执行步骤：
1. 定位问题代码
   - 根据 stack trace 或日志定位
   - 确认属于哪个模块

2. 分析根因
   - 是 LLM 输出解析问题？→ core/llm_unified_analyzer.py
   - 是业务逻辑缺陷？→ services/conversation_analyzer.py
   - 是数据质量问题？→ core/database.py

3. 编写修复
   - 最小改动原则（不引入新问题）
   - 添加回归测试

4. 验证修复
   - 运行相关测试: pytest tests/ -k "conversation" -v
   - 手动验证业务场景
```

### 场景 3: 重构优化
```
用户: "这段代码太复杂了，简化一下"

CodeBuddy 执行步骤：
1. 评估重构范围
   - 仅当前文件？→ 局部重构
   - 涉及多个模块？→ 架构级重构

2. 保持行为不变
   - 先写测试锁定当前行为
   - 重构后测试必须通过

3. 应用设计模式
   - 单例模式？→ 用于全局服务
   - 策略模式？→ 用于多算法切换
   - 工厂模式？→ 用于对象创建

4. 清理废弃代码
   - 删除未使用的导入
   - 移除注释掉的旧代码
   - 更新相关文档
```

---

## 📊 质量门禁（Quality Gates）

### 提交前自动检查
```bash
# 1. 目录结构验证
python scripts/check_structure.py

# 2. Import 排序检查
isort --check-only --diff devpartner_agent/ devpartner_tools/

# 3. 代码风格检查
flake8 devpartner_agent/ devpartner_tools/ --max-line-length=120

# 4. 类型检查（可选）
mypy devpartner_agent/core/

# 5. 运行测试
pytest tests/ -v --tb=short
```

### 代码覆盖率要求
| 模块 | 最低覆盖率 | 目标覆盖率 |
|------|-----------|-----------|
| `core/` | 90% | 95% |
| `services/` | 80% | 90% |
| `skills/` | 75% | 85% |
| `tools/` | 85% | 90% |

---

## 🔧 CodeBuddy 配置建议

### .codebuddy/rules/ 目录下的其他规则文件
```
.codebuddy/rules/
├── task_pipeline.md              # 任务管道规范（已有）
├── user-profile-analysis.md      # 用户画像分析规则（已有）
└── project-structure.md          # 项目结构规范（本文件）✨ 新增
```

### 推荐的 CodeBuddy 设置
```yaml
# .codebuddy/config.yml（如支持）
project:
  name: DevPartner
  version: 5.2.0
  
rules:
  enforce_structure: true         # 强制执行目录结构
  auto_format: true               # 自动格式化代码
  test_on_save: true              # 保存时运行测试
  
paths:
  source:
    - devpartner_agent/
    - devpartner_tools/
  tests: tests/
  docs: docs/
  
exclude_patterns:
  - "__pycache__"
  - "*.pyc"
  - ".venv/"
  - "data/"
```

---

## 📝 快速参考卡（Cheat Sheet）

### 我想要添加...
| 目标 | 位置 | 模板 |
|------|------|------|
| 新分析方法 | `core/llm_unified_analyzer.py` | `def analyze_xxx(self, ...) -> dict:` |
| 新业务服务 | `services/new_service.py` | `class NewService:` |
| 新技能 | `skills/new_skill.py` | `async def execute_skill(...)` |
| 新 MCP 工具 | `tools/new_tool.py` | `def tool_function(params) -> Result:` |
| 新测试 | `tests/test_new_feature.py` | `def test_xxx_scenario():` |
| 新文档 | `docs/new_doc.md` | Markdown 格式 |
| 部署配置 | `deploy/` | Dockerfile / docker-compose.yml |

### 常用命令速查
```bash
# 开发调试
python server.py                          # 启动服务
pytest tests/ -v                          # 运行测试
pytest tests/ -k "keyword" -v             # 运行特定测试

# 代码质量
isort devpartner_agent/ devpartner_tools/  # 排序 import
flake8 devpartner_agent/ devpartner_tools/  # 代码风格
mypy devpartner_agent/core/               # 类型检查

# 部署运维
docker-compose up -d                      # 启动容器
docker-compose logs -f                     # 查看日志
docker exec -it agent bash                 # 进入容器
```

---

## 🔄 版本兼容性

### v5.2 vs v5.0 结构变化
| 变更项 | v5.0 | v5.2 | 说明 |
|--------|------|------|------|
| 测试位置 | `devpartner_agent/tests/` | `tests/` | 独立出来 |
| 部署文件 | 根目录散落 | `deploy/` | 集中管理 |
| 文档数量 | 8+ 个 md | 3 个核心 | 大幅精简 |
| LLM 引擎 | 无 | `core/llm_unified_analyzer.py` | 新增核心组件 |

### 迁移指南
如果从旧版本升级：
```bash
# 1. 移动测试文件
mv devpartner_agent/tests/* tests/

# 2. 移动部署文件
mv Dockerfile docker-compose.yml deploy/

# 3. 删除冗余文档
rm V5.1_OPTIMIZATION_SUMMARY.md MODELSCOPE_DEPLOY.md

# 4. 验证结构
python scripts/check_structure.py
```

---

## 📞 问题与反馈

发现规范问题或有改进建议？

1. 查看本文档的相关资源章节
2. 在团队内部讨论
3. 提交 PR 更新本规则文件

---

**维护者**: DevPartner Team  
**创建日期**: 2026-07-03  
**适用工具**: CodeBuddy (所有版本)  
**适用版本**: DevPartner v5.2+  
**状态**: ✅ 生效中