# DevPartner 项目记忆

## 📌 当前状态（v7.3.0 | 2026-07-09）

### 快速启动
```bash
python server.py 7860    # 正确方式（纯端口号）
```
- 废弃写法：`python server.py sse 7860`（仍兼容但提示废弃）
- 默认端口：**7860**
- Transport：**streamable-http**（sse 已废弃），端点 `/mcp`

### 技术栈
- FastMCP 框架（streamable-http transport）
- SQLite（WAL 模式，读操作无锁并发，写操作 _write_lock 串行化）
- Python 3.10+
- LLM：Ollama 本地 HTTP API（`ollama pull qwen3`），零 GGUF 文件管理（v7.3.0 起由 llama-cpp-python 迁移）
- 个人成长仪表盘：**已移除**（v7.3），交由 Obsidian 管理
- 运维面板：**保留**（`/api/system/*`, `/api/tasks/*`, `/api/health/*`, `/api/trends/*`）

---

## 🏗️ 架构概览

### 目录结构
```
devpartner/
├── server.py              # 唯一启动入口 FastMCP + Streamable HTTP
├── devpartner_tools/      # 纯工具层（无状态）16个工具
│   └── tools/             # filesystem, git, web, system
├── devpartner_agent/      # 智能管家层（有状态）
│   ├── core/              # LLM统一分析器 + 数据库 + 配置 + 规则引擎 + 身份识别
│   ├── services/          # 17个服务（对话分析、任务队列、知识图谱、用户画像、业务知识提取、Vault导出等）
│   └── skills/            # 3个技能（每日总结、自我迭代）
├── data/                  # 数据目录
│   ├── databases/         # SQLite 数据库（唯一数据源）
│   └── vault/             # Obsidian Vault Markdown 导出
└── models/                # LLM 模型文件（gitignore）
```

### 架构层次
```
server.py (FastMCP, /mcp 端点)
├── 工具层：16个（filesystem, git, web, system）
└── 智能层：（core引擎 + 17个service + 3个skill）
    ├── core/       LLM统一分析器 + 数据库 + 配置
    ├── services/   对话分析、任务队列、知识图谱、用户画像、业务知识提取、Vault导出...
    └── skills/     每日总结、自我迭代
```

### 关键决策
1. **目录命名**：`devpartner_tools` / `devpartner_agent`（Python 包名不能含连字符）
2. **包导入**：使用 `from devpartner_agent.core.xxx` 绝对导入，替代 `sys.path.insert` hack
3. **数据存储原则**：系统独立于客户端，所有数据写入 SQLite（`data/databases/devpartner.db`），客户端零写入
4. **唯一数据源**：SQLite conversations + conversation_archive 表（daily_log Markdown 已废弃 v6.2）

---

## 🔧 核心功能模块

### 1️⃣ 总分总对话录制（v7.0→v7.2）
**三步走模式**：
1. **总（开）**: `create_conversation()` → 创建会话获取 ID
2. **分（中）**: 每个子任务完成 → `record_step()` → 异步提交（知识点提取+技能标签+文件索引+started_at计时）
3. **总（尾）**: 对话结束 → `finalize_conversation()` → 全局多维度分析（技术决策链+用户画像+知识图谱+优化建议+improvement_log流转）

**强制约束**：每个 TODO 完成即调 record_step（旧行为：整个对话只用一次 record_dialogue）

**v7.2 增强**：
- `record_step()` 自动设置 `started_at` 时间戳
- `_execute_step_analysis()` 回写 `knowledge_point_ids` + `duration_ms`
- 孤儿步骤自动清理（pending>24h→orphaned, in_progress>10min→回退pending）

### 2️⃣ AutoLogMiddleware 自动日志（v2.3.0→v7.2）
- 利用 FastMCP 的 `Middleware.on_call_tool` hook
- 每次 MCP 工具调用自动记录（排除只读/诊断类工具）
- **智能触发**：用户反馈检测（纠正-10/追问+3/补充-5）、动态质量分、阈值自动标记优化
- **有意义对话计数器**：持久化在 `data/.conversation_counter.json`，每 20 次触发 self_iterate

### 3️⃣ Self Iterate 自我迭代（v4.0.0）
**触发链路**：
```
record_dialogue/record_conversation 调用
→ AutoLogMiddleware: 有意义对话计数器 +1
→ 累计 20 次 → optimization_hint.json 标记 pending
→ AI 客户端 check_optimization_needed → should_optimize=true
→ AI 客户端 self_iterate → 全维度分析（7维度）
→ AI 客户端 save_self_iterate_results → 写入 DB 各表
→ AI 客户端 mark_optimization_done → 重置计数器
```

**输出维度**：
1. 用户画像（技能领域分布、强弱项）
2. 技能评估（等级分布、成长趋势）
3. 批评指点（从反馈中提取纠正/不满信号）
4. 未来规划建议
5. MCP 工具优化（零使用禁用、高频增强）
6. 系统健康度（数据库膨胀、规则引擎）
7. 系统反馈（对话趋势、优化标记状态）

### 4️⃣ LLM 双层分析引擎（v7.1）
- **Step 级**：`analyze_step_content()` → 提取思考模式/命令/语法知识点（**按图索骥**）
- **Conversation 级**：`analyze_conversation_deep()` → 提取系统问题/根因/反复模式/不足/用户洞察（**大方向**）
- Prompt 模板：`_STEP_ANALYSIS_PROMPT` + `_CONVERSATION_DEEP_ANALYSIS_PROMPT`

### 5️⃣ 知识图谱引擎（v7.2 增强）
- 从 `knowledge_points` 表自动构建节点和边
- 5 种边类型：shared_domain / shared_tags / same_source / explicit / similar_content
- BFS 路径发现 + Jaccard 内容相似度
- 6 个 MCP 工具：build/get_stats/get_neighbors/find_path/get_cluster/export
- **v7.2 新增**：`sync_knowledge_relations()` 图谱共现关系写回 `knowledge_points.related_knowledge_ids`
- **v7.2 新增**：`get_stale_skills()` 技能复习提醒 + `get_forgetting_curve()` 遗忘曲线可视化

### 6️⃣ Obsidian Vault 集成（v7.3 新增）
- 个人成长仪表盘迁移至 Obsidian（Chart.js dashboard 已删除，复习交给 Obsidian Spaced Repetition 插件）
- 运维 API 保留：`/api/system/*`、`/api/tasks/*`、`/api/health/*`、`/api/trends/*`
- 项目业务知识查询 API：`GET /api/projects/list` + `POST /api/projects/query`（前端下拉框交互）
- 业务知识提取：`knowledge_extractor.py` 使用用户指定的通用 Prompt 模板，传入完整对话文本
- Vault 导出：`vault_exporter.py` 导出 Markdown 卡片到 `data/vault/`
  - `Efforts/{项目}/业务知识/` — 业务知识卡片（`category='business'`）
  - `Efforts/{项目}/Dialogs/` — 对话元数据
  - 技能卡片导出已移除（技能复习由 Obsidian 管理）
- 知识检索：`question_with_context()` MCP 工具支持 `project_name` + `category` 过滤（business/skill 数据层隔离）
- **数据层隔离**：`knowledge_points.category` 区分 `'business'`（项目业务知识）和 `'skill'`（技能知识）

### 7️⃣ 用户画像协同机制（v7.2）
- `record_dialogue` / `record_conversation` 必须传入 `user_traits` 参数
- **9 个维度**：skills_observed, behavior_notes, mistakes, strengths, communication_style, decision_pattern, tech_interests, areas_for_growth, emotional_state
- 映射到 DB 表：user_skills / improvement_log / user_skill_plan / optimization_feedback

---

## 🛠️ 重要 Bug 修复与经验教训

### 致命级 Bug
| 问题 | 根因 | 修复方案 |
|------|------|---------|
| MCP 连接后 0 个工具 | `mcp.tool()(func)` 错误语法 | 改为 `mcp.tool(func)` |
| ASGI Exception | 22 处 `from core.xxx` 相对导入 | 改为 `from devpartner_agent.core.xxx` |
| SSE ClosedResourceError | 客户端断开后 writer.send() 崩溃 | 三重防护补丁（handle_post_message/connect_sse/MemoryObjectSendStream）|
| conversation_steps FK 失败 | conversations.conversation_id 缺 UNIQUE INDEX | 启动时 CREATE UNIQUE INDEX + 三步自修复 |
| LLM 服务从未启动 | llama-cpp-python 版本 < 0.3.20 不支持 Qwen3.5 | conda install >= 0.3.20 |
| 容器崩溃重启循环 | `mcp._app.add_middleware()` 语法错误（0.3.x 无 _app）| 改为 `mcp.run(middleware=[...])` |
| CodeBuddy 不显示工具 | 缺少 `Accept: application/json` header | monkey-patch `_validate_accept_header` |
| LLM 引擎不兼容 | 预编译 llama-cpp-python wheel 内嵌 llama.dll 含 AVX-512 指令，AMD Ryzen 7 7730U 不支持 | **v7.3.0 根本解决**：推理引擎迁移至本地 Ollama HTTP API，彻底移除 llama-cpp-python 与 GGUF 文件依赖 |

### 经验教训
1. **不要在 `_AUTO_LOG_SKIP_TOOLS` 中放有副作用的工具**（会导致计数链断裂）
2. **replace_in_file + 非 unique old_str = 文件炸弹**（匹配 20+ 处导致损坏）
3. **aliyun mirror 缺少关键包**（llama-cpp-python 需指定 pypi.org 或 conda-forge）
4. **Python 3.13 + pip = 原生扩展包地狱**（conda-forge 是最佳选择）
5. **FastMCP 不同 transport 默认路径不同**（SSE=`/sse`, Streamable HTTP=`/mcp`）
6. **MCP 项目不能指望客户端主动调用日志工具**（必须服务端 Middleware 拦截）
7. **SQLite ALTER TABLE ADD COLUMN 不支持 UNIQUE**（需分步迁移）

---

## 📊 数据库 Schema 要点

### 核心表结构（14 张表）
- **conversations**：主对话表（conversation_id UNIQUE, skill_domains, complexity, feedback_type）
- **conversation_archive**：完整存档（关联 conversations.id）
- **conversation_steps**：子任务步骤（FK → conversations.conversation_id）
- **user_skills**：技能画像（skill_domain, skill_level, timestamp）
- **optimization_feedback**：优化反馈（conversations_id FK, confidence, false_positive）
- **mcp_tool_registry**：工具注册表（自动 INSERT OR IGNORE）
- **knowledge_points**：知识点库
- **task_queue**：异步任务队列（step_analysis / conversation_finalize）
- **evolution_log / improvement_log / version_history / user_skill_plan**

### 并发策略
- **读操作**：无锁（利用 SQLite WAL 原生多读并发）
- **写操作**：`_write_lock` 串行化（SQLite 单写限制）
- **初始化**：`_local_lock` 仅保护 init_local 一次性初始化

---

## 🚀 版本演进关键节点

| 版本 | 日期 | 核心变更 |
|------|------|---------|
| v2.0.0 | 06-27 | 双服务架构（tools + agent），43 个工具 |
| v2.1.0 | 06-28 | 合并双服务端口 + Git 工具 + 包导入规范化 |
| v2.2.0 | 06-28 | Docker 部署配置 |
| v2.3.0 | 06-30 | AutoLogMiddleware 智能触发 + 规则引擎 v3.0 |
| v2.4.0 | 06-30 | 对话经验沉淀系统（7 个新工具） |
| v4.0.0 | 07-01 | self_iterate 对话驱动 + 7 维度分析 |
| v5.1.0 | 07-02 | 版本号统一 + README 重写 |
| v5.2.0 | 07-02 | 异步后台任务队列 + 代码清理 |
| v5.3.0 | 07-02 | 数据库读写锁分离 |
| v6.0.0 | 07-03 | LLM 驱动架构 + Dashboard + 知识图谱 + 总分总录制 |
| v6.0.3 | 07-04 | ModelScope 容器崩溃修复 |
| v6.0.4 | 07-04 | CodeBuddy Accept header 兼容 |
| v7.0.0 | 07-07 | 总分总对话分析架构 + Schema 收敛（conversation_id 双FK） |
| v7.1.0 | 07-07 | Step→Task 链式 + 系统 LLM 双层分析 |
| v7.2.0 | 07-08 | 四阶段优化：数据写入修复 + 生命周期兜底 + 文档规范 + 技能复习/遗忘曲线/知识关联 |
| v7.3.0 | 07-10 | ★ LLM 引擎迁移至 Ollama（移除 llama-cpp-python/GGUF）；同期：删除个人成长 Dashboard + growth_analytics；新增业务知识提取（通用Prompt模板）+ Obsidian Vault 导出；新增项目业务知识查询API（下拉框）；question_with_context 添加 category 数据隔离；运维面板保留 |

---

## 🐳 部署与运维

### Docker 策略
- **根目录 Dockerfile** → ModelScope 云端自动构建
- **docker-compose.yml** → 本地开发编排
- **端口映射**：7860:7860（ModelScope 只支持 7860/8080）
- **数据持久化**：Volume 挂载 `./data/` 目录
- **健康检查**：HEALTHCHECK 指令 + `/health` 端点

### ModelScope 部署要点
1. CORS 中间件（`CORSMiddleware`）
2. 根路径 `/` + `/health` 端点（探测需求）
3. Accept header 兼容（monkey-patch）
4. 模型缓存 `/mnt/workspace/modelscope_cache`（避免重复下载）
5. conda-forge 安装 llama-cpp-python（Python 3.13 兼容）

### 启动脚本
- **本地**：`python server.py 7860`
- **ModelScope**：`scripts/start_modelscope.sh`（36 行，含模型下载+缓存恢复）
- **健康检查**：`scripts/healthcheck.py`（多端点回退探测）

---

## ⚠️ 强制约束规则

### AI 行为强制约束（v7.2）
1. **每次对话结束后必须调用 `record_dialogue`**（否则对话不记录、self_iterate 无法触发）
2. **调用时机**：完成用户请求并给出最终回复之后立即调用
3. **必须传入 `user_traits` 参数**（9 维度用户特征）

### 数据写入路径（v7.2）
- ✅ **唯一数据源**：SQLite `data/databases/devpartner.db`
- ❌ **已废弃**：Markdown 日志文件 `data/daily_logs/conversation_YYYY-MM-DD.md`
- ❌ **已废弃**：`conversation_archive` 表（v7.0 不再创建新表，仅兼容旧数据查询）
- ❌ **禁止**：CodeBuddy 客户端写任何本地文件（`.codebuddy/memory/`、`data/`）
- ✅ **跨会话记忆**：通过 MCP 工具 `update_memory` / `get_memory`

### 安全白名单（永不自动禁用的核心工具）
```
check_optimization_needed, mark_optimization_done, self_iterate,
save_self_iterate_results, record_dialogue, record_conversation,
log_conversation, get_tool_registry, system_diagnose,
get_capabilities, check_rule, get_rules, process_user_feedback
```

---

## 📝 文档同步状态（v7.2.0）

以下文档已在 v7.2.0 中同步更新：
- [x] **pyproject.toml**：version → 7.2.0（版本单一来源）
- [x] **config.yaml**：version → 7.2.0
- [x] **server.py**：启动 banner + version_changelogs + 分析版本标记
- [x] **conversation_analyzer.py**：analysis_version → v7.2_llm / v7.2_fallback
- [x] **auto_analyzer.py**：version → 7.2.0
- [x] **user_profile_service.py**：schema version → 7.2
- [x] **project-structure.md**：版本 → v7.2.0
- [x] **MEMORY.md**：当前状态 → v7.2.0
- [ ] **CHANGELOG.md**：需补充 v7.x 记录
- [ ] **README.md**：版本迭代记录需更新

---

## 🔍 子系统详细说明

### 异步任务队列（v7.2）
- **后台线程**：`_background_task_queue` + `_enqueue_background_task()`
- **懒启动**：首次 `record_dialogue` 时自动启动 worker 线程
- **任务类型**：step_analysis / conversation_finalize
- **v7.0 增强**：启动恢复（processing/running→pending）+ 重试调度（failed→pending）
- **v7.2 增强**：孤儿步骤清理 + knowledge_point_ids/duration_ms 回写 + actual_memory_mb 回写
- **优势**：不阻塞主线程，数据完整性校验+自动分析+用户特征融合+写入追踪全部后台执行

### 安全审计引擎
- **规则**：security-audit（priority=2, auto_trigger=True）
- **扫描项（9 条）**：HARDCODED_SECRET / DANGEROUS_EVAL_EXEC / SQL_INJECTION / DANGEROUS_IMPORT_PICKLE / UNSAFE_SUBPROCESS / SENSITIVE_LOG / WEAK_HASH / INSECURE_DESERIALIZE / DEBUG_MODE
- **MCP 工具**：`run_security_audit(path)` → 按严重度分级输出（critical/high/medium/low）

### subprocess 编码修复（全局）
- **问题**：Windows 下 GBK 解码 UTF-8 字符 → UnicodeDecodeError
- **修复**：7 个文件 27 处 `subprocess.run()` 统一添加 `encoding='utf-8', errors='replace'`

### 版本号动态化（v7.2）
- **单一来源**：`pyproject.toml` → 环境变量 → 默认值
- **函数**：`get_project_version()`
- **注入**：dashboard.html 用 `{{VERSION}}` 模板变量
- **迁移控制**：`meta` 表跟踪 schema_version，相同版本跳过迁移
- **启动记录**：`_record_version_on_startup()` 仅在版本升级时写入，相同版本重启跳过

---

## 🎯 项目规则融合（2026-07-06）

### Ponytail 简约原则集成
- **YAGNI 梯子**：6 步决策框架（前两步有效即停）
- **代码审查规范**：5 标签体系（delete/stdlib/native/yagni/shrink）
- **技术债务追踪**：`# ponytail:` 注释自动扫描
- **边界说明**：何时不应用 Ponytail（安全关键/性能热点/合规要求）

### 核原则优先级
1. **最短路径优先**（解决当前问题即可）
2. **SRP**（单一职责）
3. **清晰层次结构**
4. **命名一致性**

---

**维护者**: DevPartner Team
**最后更新**: 2026-07-09
**适用版本**: v7.2.0+