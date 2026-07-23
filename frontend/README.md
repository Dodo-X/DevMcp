# Frontend（预留）

本目录为 **前后端分离** 架构预留的前端位置。

## 当前状态

DevPartner 当前以 **MCP 服务** 形态对外提供能力（`mcp_service/`），并复用
`backend/` 底层业务逻辑。前端 Web 应用尚未构建。

## 与 MCP 的关系

- MCP 工具通过注解暴露，**仅被 MCP 客户端调用**，与 Web 网关互不冲突。
- 前端（未来）与 `backend/api_gateway/` 共享同一套 `foundation/` + `backend/core/` + `backend/business/` 底层能力。

## 规划

- 技术栈待定（React / Vue 均可）。
- 共享 `backend/api_gateway/` 提供的 REST 接口与 `foundation/api_response/` 统一返回体。
- 知识卡片、用户画像、成长雷达等可视化面板可在此实现。
