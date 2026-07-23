# 技术评审机制 (Tech Review)

> 目的：把“代码审查”制度化，避免依赖个人自觉，持续保障质量与技术债可控。

---

## 1. 评审类型与节奏

| 类型 | 频率 | 主持 | 产出 |
|------|------|------|------|
| 代码评审 (PR) | 每次合并 | CODEOWNERS 指派评审人 |  approving review |
| 架构评审 (ADR) | 按需（涉及跨层/新模块） | @devpartner/core | 新 ADR 或更新 |
| 技术债复盘 | 每双周 | @devpartner/maintainers | 清理 backlog 更新 |
| 全局技术评审 | 每季度 | 全体核心 | 本文件 + 改进计划更新 |

## 2. PR 评审清单（Reviewer 必查）

- [ ] 意图清晰，与 Issue/ADR 对齐
- [ ] `ruff check` / `ruff format` 通过（CI 已卡）
- [ ] 有测试覆盖关键路径；`pytest` 通过（CI 已卡）
- [ ] 无 `print()` 当日志、无裸 `except:`、无静默吞异常
- [ ] 无密钥/模型权重入库
- [ ] 数据库 DDL 顺序正确（`base_conn` 单点）
- [ ] 公共接口有类型注解与 docstring
- [ ] 性能热点无同步阻塞、无 N+1

## 3. 评审文化

- **对事不对人**：评论聚焦代码与风险，不评价作者。
- **及时响应**：评审请求 1 个工作日内给出首轮意见。
- **小步合并**：大 PR（>400 行）要求拆分，降低评审负担与回归风险。
- **学习型复盘**：典型缺陷（如本次发现的 `undefined name`、`done` 检测失效、索引错建）纳入 `TEAM_IMPROVEMENT_PLAN.md` 的分享主题。

## 4. 质量门禁（CI 强制）

- lint 门：`ruff check .` + `ruff format --check .`
- 测试门：`pytest`（含 `--cov` 覆盖率门禁，目标 ≥ 70% 关键模块）
- 冒烟门：`tests/test_smoke.py` 在无重型依赖下也必须通过
- 任一失败**禁止合并**。

## 5. 技术债登记

- 新发现的技术债在 `pyproject.toml` 的 Ruff ignore（阶段性）或本仓库 Issue 登记。
- 每季度评审会清理一批阶段性 ignore，控制“允许不修”的边界不无限扩大。
