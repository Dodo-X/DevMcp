# DevPartner 项目参考

> **当前版本**: v9.5.5 | **日期**: 2026-07-23 | **架构**: 分层重构完成（foundation/backend/mcp_service/frontend）
> 数据存储: SQLite `data/databases/devpartner.db`

## 快速启动

```bash
python main.py 7860          # 统一入口，代理到 mcp_service.mcp_server
python -m mcp_service.mcp_server 7860   # 或直接启动 MCP 模块
```
- 端口: **7860**，Transport: **streamable-http**，端点 `/mcp`
- 技术栈: FastMCP + SQLite(WAL) + Python 3.10+ + Ollama(qwen2.5)
- 配置: `foundation/config/config.yaml`（已从 `devpartner_agent/config.yaml` 迁移至此）

## 架构（v9.5.5 分层）

```
main.py → runpy 代理 → mcp_service/mcp_server.py (MCP 薄壳, 注解暴露工具)

foundation/        全局基础框架（与业务解耦，可独立复用）
  config/ logger_framework/ trace_tracker/ exception_framework/ api_response/ common_utils/
backend/           后端业务层（核心大脑）
  core/            conversation_mgr / llm_kernel / task_queue_kernel / database / bootstrap / scheduler / task_recovery / data_types
  business/        system_ops / knowledge_extractor / data_cleanup / vault_export / analytics / task_handlers
  api_gateway/     rest_api(server/lifespan) + dashboard.html + middlewares/routes/dependencies(预留)
  templates/       llm_prompt/ (LLM 提示词) + md_render/ (预留)
frontend/          前端（预留，尚未构建）
```

**分层原则**:
- MCP 工具通过注解暴露，仅被 MCP 客户端调用，与 Web 网关互不冲突，共用 foundation + backend 底层。
- **绝对导入**: 所有模块用 `from backend.xxx` / `from foundation.xxx`，禁止跨包相对导入。
- `foundation/` 不得反向依赖 `backend/` 或 `mcp_service/`。

## 关键决策 / 坑点（长期有效）

1. **数据唯一源**: SQLite `data/databases/devpartner.db`，客户端零写入。
2. **LLM**: Ollama HTTP API（非 GGUF）。
3. **总分总录制**: `start_conversation` → `record_step`(每步立即) → `finalize_conversation`。
4. **Prompt 不可裁切**: 必须专业完整，可慢不能丢（v9.5.0）。
5. **LLM 超时取消机制**: 线程局部 cancel_event + infer() 自动检测。
6. **状态回写原则**: 流程真正走完后才更新状态，不"提前标记"。
7. **Ponytail 原则**: 最短路径即正确路径，删除优于添加。
8. ⚠️ **`mcp` 包名冲突**: 绝不能把新包命名为 `mcp`（会遮蔽已安装的 `mcp` pip 库，FastMCP 依赖它）。统一用 `mcp_service/`。
9. ⚠️ **路径脆弱文件**: 迁移后需修正 `Path(__file__).resolve().parent` 链深度 —— `foundation/config/app_settings.py`(config.yaml 同目录)、`vault_export`(多一层到 data/)、`api_gateway`(dashboard.html 同目录)。
10. ⚠️ **预存在 bug（已修）**: `backend/templates/llm_prompt/__init__.py` 曾导入 4 个从未定义的 Prompt 名（TASK_WEEKLY_REPORT 等），导致包级 import 失败；已移除并加 NOTE。

## 核心表结构

| 表 | 用途 |
|----|------|
| conversations / conversation_steps | 对话主表 / 子任务步骤（FK） |
| task_queue | 异步任务队列 |
| knowledge_points | 知识点库 |
| improvement_log | 改进记录 |
| user_skills / user_skill_plan / user_profile | 用户画像 |
| connected_systems / optimization_feedback / growth_analysis / evolution_log | 连接/反馈/进化日志 |

## 任务恢复流水线

`run_recovery_pipeline()` 统一入口：**门A**(ensure_ready 末尾启动恢复) / **门B**(定时每300s)。两阶段：扫描 task_queue 去重排序入队 → 交叉扫描补缺失 finalize。日报兜底每日 17:30。

## 已知待修复

| 问题 | 状态 |
|------|------|
| `output_data` 只存统计计数，LLM 分析结果未写入 DB | ⚠️ 待修复 |
| P0 修正清单（steps_summary、user_traits、key_decisions） | ⚠️ 待实施 |
| knowledge_points domain 值不一致 | ⚠️ step_analysis 提取时需归一化 |

## 用户偏好

- Prompt 必须专业完整，宁慢勿丢；不砍分析质量换速度。
- 偏好 Python 脚本诊断而非 GUI。
- 代码风格: Ponytail 原则（最短路径即正确路径）；架构原则: 代码与模板严格分离。
