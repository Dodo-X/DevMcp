# 团队技术提升计划 (Team Improvement Plan)

> 基于本次全面技术审查的发现制定。目标：用 3 个月把团队从“能跑”提升到“可持续、可审计、低风险”。

---

## 0. 现状基线（本次审查结论）

| 维度 | 结论 |
|------|------|
| 架构合理性 | **良好**：四层分层清晰、绝对导入、线程安全 DB、docstring 到位。无需重构。 |
| 流程规范性 | **薄弱**：无测试/lint CI、无 PR/Issue 模板、无 CODEOWNERS、无 pre-commit、pytest.ini 缺失。 |
| 生命周期完整性 | **缺失**：需求→设计→开发→测试→部署→运维 未闭环，缺需求模板与运维手册。 |
| 代码质量 | **有硬伤**：1 处裸 `except`、78 处 `print` 当日志、275 处 `except Exception`、乱码注释；**并发现 5 个真实运行时 bug**（见报告）。 |
| 团队提升 | **未制度化**：规范散落、无分享与评审节奏。 |

---

## 1. 第一阶段（第 1 月）：止血与基建

**目标**：把“能跑”变成“可验证、可合并”。

- [x] 引入 Ruff + pre-commit，统一 lint/format（`pyproject.toml`、`.pre-commit-config.yaml`、`.editorconfig` 已落地）
- [x] 建立 CI：lint + test + smoke（`.github/workflows/ci.yml`）
- [x] 建立 PR/Issue 模板 + CODEOWNERS（`.github/`）
- [ ] **全员**：本地 `pre-commit install`，合并前必须通过
- [ ] **清理**：78 处 `print` 当日志 → 统一 `logger`（排期 2 周）
- [ ] **收口**：275 处 `except Exception` 中“静默吞”的（如 MCP 工具、定时任务）补齐 `logger.exception`

**度量**：CI 通过率 100%；合并 PR 100% 带 approving review。

## 2. 第二阶段（第 2 月）：测试与规范内化

**目标**：关键路径有测试，规范成为习惯。

- [ ] 补关键模块单测：DB 封装、LLM 内核流式、统一响应、调度、业务服务（目标覆盖率 ≥ 70% 关键模块）
- [ ] 落地 `docs/CODING_STANDARDS.md`，新代码 100% 符合
- [ ] 双周技术债复盘，清理一批 Ruff 阶段性 ignore
- [ ] **分享会（第 1 场）**：主题“我们修过的 5 个真实 bug”（undefined name / 流式 done 失效 / 索引错建 / 裸 except / 乱码注释）

**度量**：关键模块覆盖率达标；技术债 issue 数环比下降。

## 3. 第三阶段（第 3 月）：生命周期闭环与文化建设

**目标**：从需求到运维可追溯，团队自驱提升。

- [ ] 推行 `docs/REQUIREMENTS_TEMPLATE.md`：需求须含背景/范围/验收，关联 Issue
- [ ] 推行 `docs/RUNBOOK.md`：部署、配置、故障排查、回滚有手册
- [ ] 季度全局技术评审，更新 ADR 与改进计划
- [ ] **分享会（第 2-3 场）**：主题“架构决策复盘”“性能与并发实战”
- [ ] 建立“代码即文档”文化：公共模块 docstring 覆盖率 ≥ 90%

**度量**：需求→上线平均周期可追踪；线上故障 MTTR 下降。

---

## 4. 分享与学习机制（长期）

- **双周 Tech Talk**：30 分钟，轮流主讲（含本次审查发现的典型缺陷案例库）
- **缺陷库**：每次 review/事故沉淀为 1 页 case（背景→根因→修复→预防），归入 `docs/TECH_REVIEW.md` 引用
- **新人 onboarding**：先读 `CODING_STANDARDS` + `ARCHITECTURE_DECISIONS` + `RUNBOOK`，再碰代码
- **奖励**：提出并落地一项规范/自动化改进者，记贡献。

## 5. 责任分工

| 事项 |  owner |
|------|--------|
| 规范与 CI 维护 | @devpartner/core |
| 测试补齐 | @devpartner/backend |
| 分享会组织 | @devpartner/maintainers |
| 文档更新 | 全体（CODEOWNERS 评审） |
