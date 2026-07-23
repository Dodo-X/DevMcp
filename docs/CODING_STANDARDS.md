# 编码规范 (Coding Standards)

> 适用范围：DevPartner 全部 Python 代码（`backend/`、`foundation/`、`mcp_service/`、`scripts/`、`tests/`）。
> 目标：一致性、可读性、可维护性、低风险合并。本规范与 `pyproject.toml` 中的 Ruff 配置、`pre-commit` 钩子联动，CI 强制校验。

---

## 1. 语言与运行时

- Python **3.10+**（当前开发用 3.13）。禁止依赖仅存在于 3.13 的破坏性特性；如使用 3.10 之后才有的语法需显式标注最低版本。
- 仅使用项目声明依赖（`pyproject.toml` / `requirements.txt`），禁止隐式依赖未声明的包。
- 统一绝对导入（`from backend.core.xxx import yyy`），禁止从包根相对导入泄漏到旧模块（`devpartner_agent/` 已废弃）。

## 2. 代码风格（由 Ruff 自动执行）

| 维度 | 规则 | 工具 |
|------|------|------|
| 行宽 | 100 字符 | `ruff format` |
| 缩进 | 4 空格，禁止 Tab | `ruff` / `.editorconfig` |
| 引号 | 字符串默认双引号；docstring 用三双引号 | `ruff` |
| 导入 | isort 排序，标准库→第三方→本地，禁止无效导入 | `ruff` (I) |
| 格式化 | 运行 `ruff format .` | `ruff format` |
| 静态检查 | `ruff check .` 0 error 才允许合并 | `ruff check` |

启用的规则集：`E,F,W,I,UP,B,C4,SIM`（见 `pyproject.toml` `[tool.ruff]`）。
**分阶段技术债**（已知、允许暂不修，但禁止新增）：`E501` 长行、`B008` 函数调用默认参数、`SIM105` 等已在 ignore 中标注，后续按季度清理。

## 3. 命名约定

- 模块/包：`snake_case`（如 `conversation_mgr.py`）
- 类：`PascalCase`（如 `CallbackRegistry`）
- 函数/变量/属性：`snake_case`
- 常量：`UPPER_SNAKE_CASE`
- 类型别名：`PascalCase` + 可选 `T` 后缀
- 布尔变量以 `is_`/`has_`/`should_` 等前缀增强可读性

## 4. 类型注解（强制）

- 所有公开函数、方法签名必须带类型注解（参数 + 返回值）。
- 对外 API / MCP 工具参数必须有默认值或明确类型，便于契约稳定。
- 避免在热点路径使用 `Any`；确需时使用 `# type: ignore` 并加原因注释（CI 禁止裸 `# type: ignore`）。

## 5. 注释与文档

- 公共模块、类、函数必须含 **docstring**（中文即可），说明**意图与约束**，而非复述代码。
- 复杂逻辑、算法边界、性能权衡处加 `# NOTE:` 行内注释；**禁止无意义注释与乱码注释**（历史 `PONYTATIL:` 乱码已全部清理）。
- 删除代码用 `git` 历史管理，**不要**用注释保留大段死代码。

## 6. 异常处理（关键红线）

- **禁止裸 `except:`**（已修复 1 处 `E722`）。至少捕获 `Exception`，并区分可恢复/不可恢复。
- 业务可预期错误使用统一异常 `BizException`（带错误码），由 `foundation/exception` 统一管理。
- **禁止静默吞异常**：`except` 块必须 `logger.exception(...)` 或至少 `logger.error(...)`。MCP 工具层已补齐 `_mcp_logger.exception(...)`。
- 解析类操作显式捕获 `(ValueError, TypeError)` 等具体异常，提供降级默认值（参考 `growth_analytics.py` 的 `first_time` 解析修复）。
- 不要在循环内重复创建异常对象；不要把异常用于正常控制流。

## 7. 日志规范

- 统一使用 `logging.getLogger(__name__)`（已补齐 `base_conn.py` / `rest_api.py` / `growth_analytics.py` 缺失的 `logger` 定义）。
- 级别：DEBUG 调试细节、INFO 关键流程、WARNING 可恢复异常、ERROR 失败。禁止 `print()` 作为日志（存量 78 处 `print` 已列入清理 backlog）。
- 日志带上下文（会话 id、任务 id），便于线上定位；**严禁记录密钥、token、用户明文敏感信息**。

## 8. 并发与资源

- 数据库访问经 `backend/core/database/base_conn.py` 的线程安全封装（读写锁 + WAL），**禁止**在各业务模块自行 `sqlite3.connect`。
- 异步/并发统一走 `anyio`；避免阻塞调用卡死事件循环。
- 长任务进入 `task_queue` / `scheduler`，不在请求路径内同步执行。

## 9. 提交与评审

- 提交信息遵循 **Conventional Commits**：`feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:`。
- 单次提交粒度小、意图清晰；禁止 “fix bug” 之类无信息提交。
- 合并需通过 CI（lint + test + smoke）且至少 1 名 CODEOWNERS 评审通过。
- 见 `docs/TECH_REVIEW.md` 与 `.github/pull_request_template.md`。

## 10. 安全与合规

- 密钥、模型权重（`*.gguf`/`*.bin`/`*.safetensors`/`*.pth`/`*.onnx`）**禁止入库**（pre-commit 强制拦截，`.gitignore` 覆盖）。
- 用户输入经参数化查询，禁止字符串拼接 SQL。
- 外部命令调用受白名单约束，避免命令注入。
