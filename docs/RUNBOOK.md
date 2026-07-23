# 运维手册 (Runbook)

> 补齐“生命周期-部署/运维”环节缺口。覆盖本地运行、部署、配置、故障排查、回滚。

---

## 1. 环境要求

- Python 3.10+（开发 3.13）
- 本地 Ollama（可选，用于真实 LLM 推理）；不可用时走规则兜底
- 依赖：`pip install -r requirements.txt`

## 2. 本地启动

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 安装 pre-commit（开发必装）
pre-commit install

# 3) 启动 MCP 服务（默认端口 7860；允许 7860/8000/8080/3000）
python -m mcp_service.mcp_server

# 4) （可选）启动 REST 网关
python main.py
```

## 3. 关键配置 (`foundation/config/app_settings.py`)

- `DataConfig.root_dir`：数据根目录（默认 `./data`），其余路径动态推导
- LLM 模式：`LLM_TEST_MODE=mock` 用于测试隔离
- 测试环境：`TEST_ENV=true`、`TEST_DB=:memory:`

## 4. 常用运维命令

```bash
# 静态检查与格式化
ruff check .
ruff format .

# 测试（mock LLM，内存库）
TEST_ENV=true LLM_TEST_MODE=mock TEST_DB=:memory: pytest -q

# 冒烟（无重型依赖）
pytest tests/test_smoke.py -q
```

## 5. 故障排查 (Troubleshooting)

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| MCP 工具报错但无日志 | 异常被静默吞 | 检查 `devpartner.mcp` logger（已加 `_mcp_logger.exception`） |
| 启动报 `no such table` | DDL 顺序错/索引在表前 | 核对 `base_conn.py` 建表顺序，禁止在表前建索引 |
| 流式响应不结束 | Ollama `done` 未检测 | 确认 `_parse_ollama_response` 返回 `is_done` 且循环 `break`（已修复） |
| `NameError: datetime`/`logger`/`chunk` | 未导入/未定义 | 补 `from datetime import datetime` 或 `logger` 定义（已修复多处） |
| `F821` 运行期报错 | 未定义名 | `ruff check` 已卡，CI 拦截 |

## 6. 数据库

- 引擎：`backend/core/database/base_conn.py`（线程安全 + WAL）
- **禁止**业务层直接 `sqlite3.connect`
- 新增表：DDL 集中在 `base_conn`，建表后再建索引

## 7. 部署

- 镜像：`Dockerfile` + `docker-compose.yml`
- 模型同步：`.github/workflows/deploy-modelScope.yml`（GitHub→ModelScope）
- **模型权重与密钥禁止入库**（pre-commit 拦截；见 `CODING_STANDARDS.md`）

## 8. 回滚

- 代码：回退到上一个通过 CI 的 tag / commit
- 配置：以 `app_settings` 默认值为基准，环境变量覆盖
- 数据：SQLite WAL 提供一定崩溃恢复；重大 schema 变更需先备份 `data/*.db`

## 9. 监控与告警（建议）

- 关键 logger：`devpartner.diag`（诊断）、`devpartner.mcp`（MCP 工具）
- 建议采集：MCP 工具失败率、定时任务 pending 积压、LLM 不可用次数
