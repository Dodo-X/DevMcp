# DevPartner Web + MCP 对接功能测试实测报告

> 测试时间：2026-07-23 ｜ 测试人：端测测（Web 应用测试专家）
> 测试对象：`devPartner` 本地进程（FastMCP + Starlette 单进程，REST 路由与 MCP 协议挂载在同一 `http_app()`）
> 环境：Windows 11 ｜ Python 3.13.12（隔离 venv）｜ fastmcp 3.4.4 ｜ Playwright 1.x + Chromium ｜ pytest 8.x

---

## 1. 执行摘要

**核心结论：Web 与 MCP 两部分对接均已成功建立，核心业务流程功能正常；测试过程中发现的全部真实错误已修复，最终 32 项用例全部通过。**

| 维度 | 结果 |
|---|---|
| 用例总数 | **32** |
| 通过（PASSED） | **32** |
| 失败 / 已知缺陷（xfail） | **0** |
| 运行时长 | ~6.9s（全量，含真实 HTTP / 浏览器级 E2E） |

- ✅ **Web 对接**：连通性、请求/响应数据正确性、页面结构与浏览器级交互（Dashboard 加载+渲染+切页）全部通过。
- ✅ **MCP 对接**：协议连接通过**真实 streamable-http 客户端**建立成功；3 个工具 + 5 个 prompt 发现正常；`start/record/finalize` 三件套调用与响应符合预期；参数校验生效。
- ✅ **集成验证**：Web 与 MCP 互不干扰，联合运行时数据流转一致（MCP 创建的会话能被 Web 各状态接口查到）。
- 🔧 **测试过程中发现并修复的错误（共 5 类，详见第 8 节）**：
  - 报告生成端点 500（周/月/年报导入失败）→ 已修复
  - `bootstrap.py` 裸文本 SyntaxError（潜伏）→ 已修复
  - `mcp_server.py` 缺 `logger` 定义 NameError（潜伏）→ 已修复
  - `daily_summary`↔`reports` 循环导入 → 已修复（延迟包装）
  - beartype claw 误导性 SyntaxError + `.pyc` 缓存掩盖（测试环境陷阱）→ 已在 conftest 禁用 claw

---

## 2. 测试范围与方法

### 2.1 覆盖范围
1. **Web 对接测试**：接口连通性、请求/响应数据正确性、页面交互功能（含浏览器级 E2E）。
2. **MCP 对接测试**：协议连接建立、消息收发、工具调用与响应。
3. **集成验证**：两部分各自独立运行正常、联合运行数据流转无误。

### 2.2 架构关键点
- Web（REST 路由）与 MCP（工具/prompt）运行在**同一进程、共用单例 DB**（`backend/core/database/base_conn.py`）。集成验证本质是验证同进程内两个入口对同一份数据的可见性。
- 测试**不依赖外部服务**：LLM 在无 Ollama 时自动降级（`cfg.llm.enabled=False`），对话分析后台静默失败但不阻塞工具返回。
- MCP 协议层用 `fastmcp.Client` 两种通道验证：① 内存传输；② **真实 streamable-http**（uvicorn 启动 `http_app()` 于真实端口）。

### 2.3 测试分层（测试金字塔）
- **集成/协议层**：21 项 Web+MCP 集成用例 + 4 项报告端点回归。
- **浏览器级 E2E**：2 项 Playwright 真实加载 Dashboard 并验证 JS 渲染与导航。
- **底层单元**：5 项原有 `test_smoke.py`（版本单源、DB schema、线程安全、响应信封、异常码）。

### 2.4 稳定策略
- 每个用例独立：临时 `root_dir` + 单例 DB 指向临时库，测试间零状态耦合。
- 调度器/清理服务用 `MagicMock` 替换，避免后台线程噪音。
- **修复了测试环境陷阱**：在 `conftest.py` 顶部禁用 beartype `claw`（自动类型装饰导入钩子），避免其对含中文日志的源码产生误导性 SyntaxError、并借 `.pyc` 缓存掩盖真实 bug（详见 8.5）。

---

## 3. 用例总览（全部 PASSED）

| # | 用例 | 类别 | 预期结果 | 实际结果 |
|---|---|---|---|---|
| 1 | `test_web_root_endpoint` | Web-连通性 | `GET /` → 200 含 DevPartner | ✅ PASS |
| 2 | `test_web_health_endpoint` | Web-连通性 | `GET /health` → 200, `healthy`, `llm_available=False` | ✅ PASS |
| 3 | `test_web_mcp_health_get` | Web/MCP-连通性 | `GET /mcp` 被协议层接管，返回 200/400/406 之一且不崩溃 | ✅ PASS（返回 406，见观察项 B） |
| 4 | `test_web_system_status` | Web-数据 | `/api/system/status` → 结构化状态 | ✅ PASS |
| 5 | `test_web_growth_apis` | Web-数据 | `/api/growth/list`+`/api/growth/trends` → 200 数组 | ✅ PASS |
| 6 | `test_web_tasks_and_knowledge_apis` | Web-数据 | `/api/tasks/stats`+`/api/knowledge/*` → 200 | ✅ PASS |
| 7 | `test_web_projects_list_fallback` | Web-数据 | `/api/projects/list` → 200（降级返回默认） | ✅ PASS |
| 8 | `test_web_trends_and_daily` | Web-数据 | `/api/trends/*`+`/api/daily/*` → 200 | ✅ PASS |
| 9 | `test_web_post_reports_generate_validation` | Web-边界 | `POST /api/reports/generate` 缺 `type` → 400 | ✅ PASS |
| 10 | `test_web_dashboard_page_structure` | Web-页面 | `GET /dashboard` → 200，含 API 端点与挂载点 | ✅ PASS |
| 11 | `test_dashboard_page_loads_and_renders_data` | Web-E2E | 浏览器加载 Dashboard，JS 拉取渲染，无页面错误 | ✅ PASS |
| 12 | `test_dashboard_navigates_to_projects_tab` | Web-E2E | 点击"项目"tab → 项目区可见 | ✅ PASS |
| 13 | `test_mcp_connect_and_discover_tools` | MCP-协议 | 连接成功，发现 3 工具 | ✅ PASS |
| 14 | `test_mcp_discover_prompts` | MCP-协议 | 发现 5 个 prompt | ✅ PASS |
| 15 | `test_mcp_core_flow_start_record_finalize` | MCP-功能 | start→record→finalize 全链路成功 | ✅ PASS |
| 16 | `test_mcp_record_step_idempotent` | MCP-功能 | 重复 record 同 step 幂等 | ✅ PASS |
| 17 | `test_mcp_record_step_missing_params` | MCP-边界 | 缺 `conversation_id` → 校验报错 | ✅ PASS |
| 18 | `test_mcp_finalize_missing_id` | MCP-边界 | 缺 `conversation_id` → 校验报错 | ✅ PASS |
| 19 | `test_mcp_real_streamable_http` | MCP-协议 | 真实 streamable-http 连接+调用+响应 | ✅ PASS |
| 20 | `test_integration_mcp_writes_web_reads` | 集成 | MCP 建会话后 Web 能查到 | ✅ PASS |
| 21 | `test_integration_web_traffic_does_not_break_mcp` | 集成 | 大量 Web 请求后 MCP 仍可用 | ✅ PASS |
| 22 | `test_integration_mcp_activity_does_not_break_web` | 集成 | MCP 活动期间 Web 仍正常 | ✅ PASS |
| 23 | `test_integration_joint_data_consistency` | 集成 | 联合操作后两入口数据一致 | ✅ PASS |
| 24 | `test_reports_generate_daily_works` | Web-报告 | `POST /api/reports/generate-daily` → 200, success | ✅ PASS |
| 25 | `test_reports_generate_weekly_returns_200` | Web-报告 | `POST /api/reports/generate {weekly}` → 200, success | ✅ PASS（缺陷 A 已修复） |
| 26 | `test_reports_generate_monthly_returns_200` | Web-报告 | `POST /api/reports/generate {monthly}` → 200, success | ✅ PASS（缺陷 A 已修复） |
| 27 | `test_reports_generate_annual_returns_200` | Web-报告 | `POST /api/reports/generate {annual}` → 200, success | ✅ PASS（缺陷 A 已修复） |
| 28–32 | `test_smoke.py` ×5 | 单元 | 版本单源 / DB 建表 / 线程安全 / 响应信封 / 业务异常码 | ✅ PASS |

---

## 4–7. Web / MCP / 集成 / E2E 详情（同前，均 PASS）

- **Web 连通性/数据**（#1–#10）：`/`、`/health` 稳定 200；系统状态、成长分析、任务/知识统计、项目列表、趋势/日报接口返回约定结构（`{code,message,data}`）；边界校验生效（缺 `type` → 400）；降级路径正确。
- **Web 页面交互**（#11–#12）：静态 `dashboard.html` 引用真实 API 端点；Playwright 真实 Chromium 加载后验证 JS 渲染与"项目"tab 导航，全程无 `pageerror`。
- **MCP 协议/功能**（#13–#19）：内存 + 真实 streamable-http 双通道验证；3 工具 + 5 prompt 发现正常；`start/record/finalize` 全链路成功；参数校验生效。
- **集成验证**（#20–#23）：同进程单例 DB 下 Web/MCP 数据一致、互不干扰，联合运行数据流转无误。

---

## 8. 测试过程中发现并修复的错误

### 8.1 缺陷 A（高，已修复）：周/月/年报生成端点 500
- **根因**：项目整改时把 `generate_weekly/monthly/annual_report` 从 `daily_summary.py` **拆分到 `reports.py`**，`daily_summary.py` 末尾注释明说"以下为向后兼容的重导出"，但那段重导出**是空的**。`rest_api.py` 与 `scheduler.py` 仍从 `daily_summary` 导入这三个函数 → `ImportError` → 500。
- **用户提示**：经用户提醒"先看看项目中有没有需要的方法，再决定下一步"，全局搜索确认函数在 `backend/business/task_handlers/reports.py`（130/285/453 行），实现完整。
- **修复**：在 `daily_summary.py` 补上向后兼容重导出。为避免 `daily_summary`↔`reports` 循环导入（导入顺序敏感），采用**延迟导入包装函数**（调用时才 `from reports import ...`），而非模块级 import。
- **验证**：`POST /api/reports/generate {weekly|monthly|annual}` 现返回 200 且 `success=true`（无数据/无 LLM 时降级为 `method=none/pending`，不抛错）。

### 8.2 缺陷 C（中，已修复）：调度器后台导入失败
- **根因**：与 8.1 同一根因——`scheduler.py` 定时触发的周/月/年报任务从 `daily_summary` 导入失败，后台线程 `ImportError`。
- **修复**：随 8.1 的重导出一并解决（延迟包装对 `scheduler` 透明）。

### 8.3 潜伏 bug（已修复）：`bootstrap.py` 裸文本 SyntaxError
- **现象**：`bootstrap.py` 第 201–208 行是一段**丢失 `#` 注释符的裸文本**（含裸 `except ImportError:`），构成真实 `SyntaxError`。
- **为何之前没暴露**：被旧的 `.pyc` 字节码缓存掩盖；且 beartype claw（见 8.5）未激活时标准 importlib 也未重新编译到该段。清理缓存 + 禁用 claw 后暴露。
- **修复**：将裸文本修正为合法注释。

### 8.4 潜伏 bug（已修复）：`mcp_server.py` 缺 `logger` 定义
- **现象**：`mcp_server.py` 的 `_register_prompts` 使用 `logger`，但模块级只定义了 `_diag_logger` / `_mcp_logger`，**没有 `logger`**（`NameError`）。
- **根因**：整改时把工具里的 `logger` 统一改名 `_mcp_logger`，漏改 `_register_prompts` 这一处；同样被旧 `.pyc` 缓存掩盖。
- **修复**：补回模块级 `logger = logging.getLogger(__name__)`。

### 8.5 测试环境陷阱（已处理）：beartype claw 误导性 SyntaxError + 缓存掩盖
- **现象**：隔离测试 venv（fastmcp 依赖链）会自动激活 beartype `claw` 导入钩子，其对含中文日志字符串的源码做类型装饰变换时，抛出**行号/内容均对不上的误导性 SyntaxError**（如把 `print(f"[INFO]...")` 误报为 `info"..."`）。
- **为何棘手**：该误报只在源码被重新编译时触发（`.pyc` 缓存命中时走缓存不报错），因此**真实存在的语法/NameError bug 被缓存长期掩盖**，一旦缓存失效（如文件被修改）就集中爆发。
- **处理**：在 `conftest.py` 顶部禁用 beartype claw（移除其 meta_path finder + 将 `install` 置为 no-op），让所有模块用标准导入加载。这一操作同时**暴露并促成修复了 8.3 / 8.4 两个真实潜伏 bug**，是让测试回归可靠的关键。

---

## 9. 保留观察项（非阻塞，无需拦截发版）

- **观察项 B（低）**：`GET /mcp` 自定义健康检查路由被 Streamable HTTP 会话管理器遮蔽，直接 GET 返回 **406**。真实 MCP 客户端连接完全正常（#19 通过），仅"简单 GET 探测"这一便捷方式不可用。建议以 `/health` 为准做存活探测。
- **观察项（低）**：fixture 多次 `ensure_ready()` 时出现 `⚠️ 覆盖已注册的 handler` WARNING（20+ 条）。建议在 handler 注册逻辑加幂等保护（已注册则跳过），避免生产中重复注册覆盖业务 handler。
- **LLM 降级符合预期**：无 Ollama 时 `analyze_conversation` 后台静默失败、工具调用不受影响，属设计内降级（用例已断言 `llm_available=False`）。

---

## 10. 结论与发布建议

**核心对接：通过 ✅** —— Web 与 MCP 均已成功对接并正常运行，集成验证数据一致、互不干扰。

**已修复的错误（本轮）**：报告端点 500（A/C）、`bootstrap.py` 裸文本、mcp_server 缺 logger、循环导入、claw 缓存陷阱——均不影响核心对接，但属于应修的真实缺陷，现已闭环。

**发布门槛建议**：
- 报告中心的周/月/年报功能现已可用（A/C 已修复），无阻塞性缺陷。
- 观察项 B（GET /mcp 406）非阻塞，建议以 `/health` 为存活探测，无需拦截发版。

**后续建议**：
1. 对 `handler` 注册加幂等保护，消除 WARNING。
2. 生产环境同样建议确认 beartype claw 不会对含中文日志的源码产生问题（测试 venv 已禁用并验证）。

---

## 附：交付物与运行方式

- 测试文件：`tests/test_web_mcp_integration.py`（21）、`tests/test_dashboard_e2e.py`（2）、`tests/test_report_endpoints_anomaly.py`（4，已转为回归断言）、`tests/test_smoke.py`（5）。
- 修复文件：`backend/business/task_handlers/daily_summary.py`（延迟重导出）、`backend/core/bootstrap.py`（裸文本注释化）、`mcp_service/mcp_server.py`（`logger` 定义）、`conftest.py`（禁用 beartype claw）。
- 运行命令（隔离 venv）：
  ```bash
  D:/Users/hebing_ot/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
    -m pytest tests/ -p no:cacheprovider -rA
  ```
- 当前结果：**32 passed**。
