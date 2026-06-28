# ModelScope 创空间部署指南

> DevPartner MCP Server v2.2.0 — ModelScope Studio 部署

## 创空间信息

- **Studio URL**: https://modelscope.cn/studios/Pisces43/Dev-partner
- **Git 仓库**: `https://www.modelscope.cn/studios/Pisces43/Dev-partner.git`
- **端口**: 7860（ModelScope 要求）

## 前置条件

创空间需包含以下文件：

| 文件 | 说明 |
|------|------|
| `Dockerfile` | Docker 镜像构建文件 |
| `server.py` | MCP 服务入口 |
| `devpartner_tools/` | 纯工具层 |
| `devpartner_agent/` | 智能管家层 |
| `pyproject.toml` | 项目依赖配置 |

## 自动部署

代码推送到 GitHub `master` 分支后，GitHub Actions 自动同步到 ModelScope：

```
GitHub (master) → GitHub Actions → ModelScope 创空间 → Docker 构建 → 上线
```

详见 `.github/workflows/deploy-modelScope.yml`

## Docker 构建流程

ModelScope 创空间检测到 Dockerfile 后自动执行：

```bash
# 1. ModelScope 自动构建
docker build -t devpartner .

# 2. 启动容器（SSE 模式，端口 7860）
docker run -p 7860:7860 devpartner
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_PORT` | 7860 | MCP SSE 服务端口（仅支持 7860 / 8080） |
| `TZ` | Asia/Shanghai | 时区 |

## 数据持久化

**重要**：ModelScope 创空间容器重启后数据会丢失，如需持久化需联系 ModelScope 配置存储卷。

当前数据目录：
```
/app/data/
├── databases/       # SQLite 数据库
├── logs/            # 对话日志
├── backups/         # 进化备份
├── temp/            # 临时文件
└── memories/        # 记忆存储
```

## 手动部署

```bash
# 1. 克隆仓库
git clone https://www.modelscope.cn/studios/Pisces43/Dev-partner.git
cd Dev-partner

# 2. 构建镜像
docker build -t devpartner .

# 3. 本地测试
docker run -p 7860:7860 -v $(pwd)/data:/app/data devpartner

# 4. 推送到 ModelScope（需登录）
git add -A
git commit -m "deploy: update docker config"
git push origin master
```

## 验证部署

```bash
# 检查容器状态
docker ps | grep devpartner

# 查看日志
docker logs devpartner-mcp

# SSE 端点测试
curl http://localhost:7860/sse
```
