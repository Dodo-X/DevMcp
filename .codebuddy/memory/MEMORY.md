# DevPartner 项目记忆

## 项目结构（2026-06-28 重构后）
- **server.py** — 唯一启动入口，同时注册 tools + agent 共 67 个 MCP 工具
- **devpartner_tools/** — 纯工具层（无状态），6 大类 25 个工具
- **devpartner_agent/** — 智能管家层（有状态），42 个工具（审批链、规则引擎、Git、清理调度等）
- 端口限制：仅 7860 和 8080

## 关键决策
- 目录名从 `devpartner-tools`/`devpartner-agent` 改为 `devpartner_tools`/`devpartner_agent`（Python 包名不能含连字符）
- 使用包导入替代 `sys.path.insert` hack，IDE 能正确识别
- 修复了 `get_rule_engine` → `get_engine`、`get_dialogue_service` → `get_dialogue` 等函数名不一致问题
- 每个子包有 `pyproject.toml`，项目根也有 `pyproject.toml`

## 技术栈
- FastMCP 框架
- SQLite（WAL 模式）
- Python 3.10+
