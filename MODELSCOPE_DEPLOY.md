# devPartner ModelScope 部署指南 v3.0

## 概述

devPartner 是一个全能 MCP 数据服务，提供 70+ 工具给 AI 客户端（CodeBuddy/Trae/Cursor 等）使用。

v3.0 核心架构：**MCP = 数据层，AI客户端 LLM = 分析层**
- 不依赖本地 Ollama（太慢、不支持远程）
- AI 客户端用自己的 LLM（Claude/GPT）分析数据，比 7B 模型强大得多

## ModelScope 部署步骤

### 1. 代码准备

```bash
# 克隆或上传代码到 ModelScope
git clone <your-repo> devPartner
cd devPartner
```

### 2. 创建 ModelScope 应用

在 ModelScope 控制台：
1. 创建新应用 → 选择 "自定义镜像" 或 "Python 应用"
2. 设置启动命令：`python server.py`
3. 设置端口：`8080`
4. 设置环境变量（见下方）

### 3. 环境变量配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DEVPARTNER_HOST` | 绑定地址 | `0.0.0.0` |
| `DEVPARTNER_PORT` | 服务端口 | `8080` |
| `DEVPARTNER_DATA_ROOT` | 数据存储路径 | `data` |
| `DEVPARTNER_SHARED_DB` | 共享数据库路径 | (留空则不用) |
| `DEVPARTNER_REPORT_DIR` | 报告输出目录 | `data/reports` |

### 4. Docker 部署（推荐）

```bash
# 构建镜像
docker build -t devpartner:latest .

# 本地测试
docker run -d -p 8080:8080 --name devpartner devpartner:latest

# 推送到 ModelScope
docker tag devpartner:latest registry.modelscope.cn/<namespace>/devpartner:latest
docker push registry.modelscope.cn/<namespace>/devpartner:latest
```

### 5. 直接 Python 部署

```bash
# ModelScope 环境
pip install -r requirements.txt
python server.py --host 0.0.0.0 --port $PORT
```

## AI 客户端连接配置

部署成功后，在 CodeBuddy/Trae 的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "devpartner": {
      "type": "sse",
      "url": "https://your-app.modelscope.cn/sse"
    }
  }
}
```

### CodeBuddy 配置路径
- Windows: `%USERPROFILE%\.codebuddy\mcp.json`
- macOS/Linux: `~/.codebuddy/mcp.json`

### Trae 配置路径
- 项目目录下 `.trae/mcp.json`

## 首次使用

AI 客户端连接后，按以下顺序操作：

```
1. devpartner_register("codebuddy", "work/space/path")
   注册客户端身份

2. devpartner_setup()
   运行配置向导

3. get_work_schema_guide()
   了解数据接口

4. 日常使用：
   - log_conversation() 记录每次对话
   - get_daily_work_data() 获取工作数据做分析
   - save_daily_analysis() 保存分析结果
```

## 数据持久化

ModelScope 免费版数据不持久化，建议：
- 使用坚果云/阿里云盘的 WebDAV 接口
- 定期导出数据到本地
- 或使用付费版的持久化存储

## 免费部署方案对比

| 平台 | 免费额度 | 数据持久化 | 适用场景 |
|------|---------|-----------|---------|
| ModelScope | 免费 | ❌ 临时 | 开发测试 |
| Railway | $5/月额度 | ✅ | 个人使用 |
| Render | 750h/月 | ✅ | 个人使用 |
| Fly.io | 免费额度 | ✅ | 个人使用 |
| 本地 | 无限 | ✅ | 开发主力 |
