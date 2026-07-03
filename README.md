# DevPartner v5.2 - AI 驱动的开发者智能伴侣

<p align="center">
  <strong>基于本地 LLM (Qwen3.5-9B) 的全栈开发辅助系统</strong><br>
  <em>对话管理 · 知识沉淀 · 自我进化 · MCP 工具集成</em>
</p>

---

## ✨ 核心特性

### 🤖 LLM 驱动架构 (v6.0)
- **零硬编码**: 所有数据分析由 Qwen3.5-9B 智能推理
- **统一提示词工程**: 结构化 Prompt 确保输出精准可控
- **双模式运行**: LLM 可用时智能分析，不可用时优雅降级
- **代码精简 93%**: 从 3600+ 行硬编码 → ~150 行 LLM 调用

### 🎯 核心能力
1. **对话智能分析** - 自动识别技能领域、复杂度、用户反馈
2. **每日工作总结** - LLM 生成专业日报（非模板化）
3. **自我迭代优化** - 基于数据驱动的系统改进建议
4. **用户画像融合** - 动态构建开发者能力模型
5. **MCP 工具集成** - 20+ 开发工具无缝调用
6. **知识图谱** - 自动沉淀和关联知识点

### 🏗️ 技术栈
| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 推理引擎 | llama-cpp-python ≥0.2.79 | 本地 GGUF 模型加载 |
| LLM 模型 | Qwen3.5-9B-Q4_1 (~5.7GB) | 4-bit 量化，平衡性能与质量 |
| 数据库 | SQLite 3.x | 轻量级，零配置 |
| Web Dashboard | HTML + JavaScript | 实时监控面板 |
| 部署方案 | Docker / 本地运行 | 支持容器化和裸机部署 |

---

## 🚀 快速开始

### 前置要求
- Python 3.10+
- 内存 ≥ 8GB（模型加载需要 ~6GB）
- 磁盘空间 ≥ 10GB

### Step 1: 安装依赖

```bash
# 克隆项目
git clone https://github.com/your-repo/devpartner.git
cd devpartner

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装基础依赖
pip install -r requirements.txt

# 安装 LLM 引擎（二选一）

# 方案 A: CPU 推理（兼容性好）
pip install llama-cpp-python>=0.2.79

# 方案 B: GPU 加速（推荐，速度快 3-5 倍）
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

### Step 2: 准备模型文件

下载 Qwen3.5-9B-Q4_1 量化模型（~5.7GB）：

```bash
# 推荐下载地址（HuggingFace）
# https://huggingface.co/Qwen/Qwen3.5-9B-Instruct-GGUF/blob/main/qwen3.5-9b-q4_1.gguf

# 放置到指定路径
mkdir -p models
# 将下载的 gguf 文件移动到:
# D:\WorkSpace\AI_model\Qwen3.5-9B-Q4_1.gguf  (Windows)
# 或 ./models/qwen3.5-9b-q4_1.gguf  (跨平台)
```

### Step 3: 配置系统

编辑 `config.yaml`:

```yaml
llm:
  enabled: true
  model_path: "D:/WorkSpace/AI_model/Qwen3.5-9B-Q4_1.gguf"  # 修改为你的路径
  n_ctx: 8192        # 上下文长度
  n_gpu_layers: -1   # -1=全部GPU加速, 0=纯CPU
  n_threads: 8       # CPU线程数（建议设为核心数）
  max_tokens: 2048   # 最大生成长度
  temperature: 0.3   # 生成温度（低值更确定）
```

### Step 4: 启动服务

```bash
# 方式 A: 直接启动（开发模式）
python server.py

# 方式 B: Docker 部署（生产模式）
docker-compose up -d

# 方式 C: 仅启动 Agent（无 Web UI）
cd devpartner_agent
python -m server
```

**预期输出**:
```
============================================================
🚀 DevPartner v5.2 Agent Starting...
============================================================
✅ 配置加载成功
✅ 数据库连接正常
✅ LLM 模型加载中... (首次需 10-30 秒)
✅ LLM 服务就绪: Qwen3.5-9B-Q4_1
🌐 Web Dashboard: http://localhost:8082
📡 MCP Server: stdio mode
============================================================
```

### Step 5: 验证安装

访问 http://localhost:8082 查看 Dashboard，或运行测试：

```bash
# 运行核心功能测试
python tests/test_basic_functionality.py

# 测试 LLM 分析引擎
python tests/test_llm_analyzer.py
```

---

## 📁 项目结构

```
devPartner/
├── README.md                      # ← 你在这里（主文档）
├── CHANGELOG.md                   # 版本迭代记录
│
├── devpartner_agent/              # 🎯 核心 Agent 系统
│   ├── core/                      #    ├─ 核心引擎层
│   │   ├── llm_unified_analyzer.py #    │  ⭐ LLM 统一分析引擎
│   │   ├── database.py             #    │  数据库操作
│   │   ├── config.py               #    │  配置管理
│   │   └── ...                     #    └─ 其他核心组件
│   │
│   ├── services/                  #    ├─ 业务服务层
│   │   ├── conversation_analyzer.py#    │  对话分析（v6.0 LLM驱动）
│   │   ├── llm_service.py          #    │  LLM 推理服务
│   │   ├── daily_summary.py        #    │  每日总结生成
│   │   └── ...                     #    └─ 其他服务
│   │
│   ├── skills/                    #    ├─ 技能模块
│   │   ├── daily_summary.py        #    │  日报生成技能
│   │   └── self_iterate.py         #    │  自我迭代技能
│   │
│   ├── config.yaml                #    Agent 配置文件
│   ├── pyproject.toml             #    Agent 依赖
│   └── requirements.txt           #    Agent 依赖列表
│
├── devpartner_tools/              # 🔧 MCP 工具集
│   └── tools/                     #    ├─ 工具实现
│       ├── filesystem.py          #    │  文件系统操作
│       ├── git_operations.py      #    │  Git 命令封装
│       ├── web_requests.py        #    │  HTTP 请求
│       └── ...                    #    └─ 其他工具
│
├── scripts/                       # 📜 运维 & 部署脚本
│   ├── upgrade_to_v5.py           #    数据库升级工具
│   ├── backfill_conversation.py   #    数据回填脚本
│   └── *.sql                     #    SQL 升级脚本
│
├── tests/                         # 🧪 测试套件
│   ├── test_llm_analyzer.py       #    LLM 引擎测试
│   ├── test_v5_core.py            #    核心功能测试
│   └── test_integration.py        #    集成测试
│
├── docs/                          # 📚 深度技术文档
│   ├── architecture.md            #    系统架构设计
│   ├── api-reference.md           #    API 接口文档
│   └── troubleshooting.md         #    故障排查指南
│
├── data/                          # 💾 运行时数据（gitignore）
│   ├── databases/                 #    SQLite 数据库
│   ├── daily_logs/               #    历史日志
│   ├── memories/                 #    对话记忆
│   └── reports/                  #    生成的报告
│
├── deploy/                        # 🐳 部署配置
│   ├── Dockerfile                 #    容器镜像定义
│   ├── docker-compose.yml         #    编排配置
│   └── .env.example              #    环境变量模板
│
├── server.py                      # 🚀 主入口文件
├── pyproject.toml                 # 项目元数据
├── requirements.txt              # 全局依赖
└── .gitignore                    # Git 忽略规则
```

### 📂 模块职责说明

#### `devpartner_agent/` - 大脑 🧠
**定位**: 核心业务逻辑，承载所有智能分析能力  
**关键组件**:
- `core/llm_unified_analyzer.py`: ⭐ **LLM 统一引擎**（v6.0 新增）
- `services/conversation_analyzer.py`: 对话深度分析
- `services/llm_service.py`: Qwen3.5-9B 推理服务
- `services/daily_summary.py`: 智能日报生成

**何时修改**: 
- 新增分析场景 → 修改 Prompt 或添加分析方法
- 调整业务逻辑 → 修改 services 层

#### `devpartner_tools/` - 手部 👐
**定位**: MCP 工具集，提供具体的操作能力  
**关键组件**:
- `tools/filesystem.py`: 读写文件、搜索内容
- `tools/git_operations.py`: Git 操作（commit/branch/PR）
- `tools/web_requests.py`: HTTP API 调用
- `tools/reasoning.py`: 逻辑推理增强

**何时修改**:
- 新增工具 → 在 tools/ 下新建文件
- 修改工具行为 → 编辑对应工具文件

#### `scripts/` - 运维工具 🛠️
**定位**: 一次性运维任务，非核心业务  
**典型用途**:
- 数据库升级/迁移
- 数据回填/修复
- 批量数据处理

**何时使用**:
- 版本升级时运行 `upgrade_to_v5.py`
- 数据异常时运行 `backfill_conversation.py`

#### `tests/` - 质量保障 ✅
**定位**: 确保系统稳定性和正确性  
**分类**:
- 单元测试 (`test_*.py`)
- 集成测试 (`test_integration.py`)
- 性能测试 (`test_performance.py`)

**何时运行**:
- 提交代码前: `pytest tests/`
- CI/CD 流水线自动执行

---

## 🎮 使用指南

### 基础用法

#### 1️⃣ 对话记录与分析

```python
from devpartner_agent.services.conversation_analyzer import get_analyzer

analyzer = get_analyzer()

# 记录一段对话
result = analyzer.analyze_and_store(
    content="我在用 React 开发前端项目...",
    source="trae",
    client="vscode"
)

print(f"识别领域: {[d['domain'] for d in result['skill_domains']]}")
print(f"复杂度评估: {result['complexity']}")
print(f"置信度: {result['confidence']}")
```

#### 2️⃣ 生成每日总结

```python
from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
from devpartner_agent.skills.daily_summary import get_daily_work_data

analyzer = get_unified_analyzer()

# 获取今日工作数据
work_data = get_daily_work_data()  # 从数据库读取

# LLM 智能生成日报
report = analyzer.generate_daily_summary(work_data)

if report:
    print(f"📊 今日摘要: {report['summary']}")
    print(f"💡 明日计划: {report['tomorrow_plan']}")
```

#### 3️⃣ 触发自我优化

```python
from devpartner_agent.skills.self_iterate import execute_self_iterate

# 执行完整的自我迭代流程
result = await execute_self_iterate(mode="auto")

print(f"生成建议: {len(result['suggestions_generated'])} 条")
print(f"应用改进: {len(result['improvements_applied'])} 个")
print(f"报告:\n{result['report']}")
```

#### 4️⃣ 使用 MCP 工具

通过 MCP 协议调用工具（已集成到 Cursor/Windsurf/Trae 等 IDE）：

```json
{
  "tool": "read_file",
  "params": {
    "path": "./src/main.py"
  }
}
```

**可用工具列表**:
- `read_file` / `write_file` - 文件读写
- `search_content` - 内容搜索
- `execute_system_command` - 执行命令
- `git_status` / `git_commit` - Git 操作
- `fetch_url` - HTTP 请求
- `record_dialogue` - 记录对话

---

## 🔧 高级配置

### LLM 引擎调优

编辑 `devpartner_agent/config.yaml`:

```yaml
llm:
  # 模型参数
  model_path: "./models/qwen3.5-9b-q4_1.gguf"
  n_ctx: 8192              # 上下文窗口（增大可处理更长文本）
  n_gpu_layers: -1         # GPU 加速层数
  n_batch: 512             # 批处理大小
  
  # 生成参数
  max_tokens: 2048          # 最大输出长度
  temperature: 0.3          # 创造性（0=确定性, 1=随机）
  top_p: 0.9               # 核采样
  repeat_penalty: 1.1       # 重复惩罚
  
  # 功能开关
  enhance_analysis: true     # 对话分析增强 ⭐ 推荐
  enhance_daily_summary: true  # LLM 日报生成 ⭐ 强烈推荐
  enhance_self_improvement: true  # 自我改进建议 ⭐ 推荐
  fallback_to_rules: true    # LLM 失败时降级到规则
```

### 性能优化建议

| 场景 | 推荐配置 | 预期效果 |
|------|---------|---------|
| **内存有限** (< 8GB) | `n_ctx: 4096`, `n_gpu_layers: 0` | 内存占用降低 50% |
| **追求速度** | `n_ctx: 4096`, `n_gpu_layers: -1` | 推理速度提升 3-5x |
| **质量优先** | `n_ctx: 8192`, `temperature: 0.2` | 输出更确定、更精准 |
| **批量处理** | `n_batch: 1024`, `n_threads: 16` | 吞吐量提升 2x |

---

## 📊 监控与维护

### Web Dashboard

启动后访问: **http://localhost:8082**

功能概览:
- 📈 实时统计（对话数、活跃用户、工具调用）
- 🧠 LLM 状态（模型加载、推理延迟、缓存命中率）
- 📋 最近对话列表
- ⚙️ 配置管理界面

### 日志查看

```bash
# 实时日志
tail -f data/logs/agent.log

# 错误日志
grep ERROR data/logs/agent.log

# 性能指标
grep "inference_time" data/logs/agent.log
```

### 数据库维护

```bash
# 备份数据库
cp data/databases/devpartner.db backups/devpartner_$(date +%Y%m%d).db

# 清理旧日志（保留最近 90 天）
python scripts/cleanup_old_logs.py

# 数据库完整性检查
python scripts/check_db_integrity.py
```

---

## 🔄 版本迭代记录

详见 [CHANGELOG.md](./CHANGELOG.md)

### v5.2.0 (2026-07-03) - LLM 驱动架构重构 ⭐
**重大变更**:
- ✅ 新增 `LLMUnifiedAnalyzer` 统一分析引擎
- ✅ 废弃 3600+ 行硬编码规则，代码精简 93%
- ✅ 对话分析、日报生成、自我改进全面 LLM 化
- ✅ 项目结构标准化重组

**新增文件**:
- `core/llm_unified_analyzer.py` - 核心引擎
- `services/conversation_analyzer_v2.py` - 精简版示例

**废弃文件**（已移至 legacy/）:
- 旧版 `conversation_analyzer.py` 中的硬编码逻辑
- 旧版 `daily_summary.py` 中的 Markdown 模板

### v5.1.0 (2026-06-28) - 性能优化
- LLM 服务预加载和缓存机制
- 数据库连接池优化
- 异步任务队列改进

### v5.0.0 (2026-06-20) - 架构升级
- Schema 升级到 v5.0
- 新增 knowledge_points 表
- 任务队列系统引入

[查看完整历史 →](./CHANGELOG.md)

---

## 🐛 故障排查

### 常见问题

#### Q1: LLM 服务启动失败？

**症状**: `❌ LLM 模型加载失败`

**解决方案**:
1. 检查模型文件路径是否正确
2. 确认 llama-cpp-python 已安装: `pip show llama-cpp-python`
3. 验证模型文件完整性: `ls -lh [model_path]`
4. 查看详细错误: `cat data/logs/agent.log | grep -i error`

#### Q2: 内存不足（OOM）？

**症状**: `Killed` 或 `MemoryError`

**解决方案**:
```yaml
# 降低内存占用
llm:
  n_ctx: 4096            # 减半上下文
  use_mmap: true         # 启用内存映射
  use_mlock: false       # 不锁定内存
```

#### Q3: 推理速度太慢？

**症状**: 单次分析 > 30 秒

**优化方案**:
1. 启用 GPU: `n_gpu_layers: -1`
2. 减少 token 数: `max_tokens: 1024`
3. 使用缓存: 相同输入会命中缓存

#### Q4: 数据库锁定？

**症状**: `database is locked`

**解决方案**:
1. 检查是否有其他进程占用: `lsof data/databases/devpartner.db`
2. 重启服务释放锁
3. 启用 WAL 模式（默认已启用）

---

## 🤝 贡献指南

### 开发流程

1. Fork 并克隆仓库
2. 创建特性分支: `git checkout -b feature/new-feature`
3. 编写代码并添加测试
4. 运行测试: `pytest tests/`
5. 提交变更: `git commit -m "feat: add new feature"`
6. 推送分支: `git push origin feature/new-feature`
7. 创建 Pull Request

### 代码规范

- 遵循 PEP 8 风格指南
- 类型注解（Python 3.10+）
- 中文注释（面向中文开发者）
- 所有公开函数必须有 docstring

### 测试要求

- 新功能必须包含单元测试
- 测试覆盖率 > 80%
- 集成测试覆盖主要流程

---

## 📄 许可证

MIT License

Copyright (c) 2026 DevPartner Team

---

## 🙏 致谢

- [Qwen](https://qwenlm.github.io/) - 强大的开源大语言模型
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) - 高效的本地推理框架
- [Model Context Protocol](https://modelcontextprotocol.io/) - 标准化的工具调用协议

---

## 📞 联系我们

- 📧 Email: devpartner@example.com
- 💬 Issues: [GitHub Issues](https://github.com/your-repo/devpartner/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/your-repo/discussions)

---

<p align="center">
  <strong>⭐ 如果这个项目对你有帮助，请给一个 Star！⭐</strong><br>
  <em>Made with ❤️ by DevPartner Team</em>
</p>