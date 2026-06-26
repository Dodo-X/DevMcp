# devPartner v3.0 Dockerfile
# 适配 ModelScope 部署
FROM python:3.11-slim

LABEL maintainer="devPartner"
LABEL version="3.0.0"
LABEL description="全能 MCP 数据服务 - AI-Client-Driven 架构"

# 设置工作目录
WORKDIR /app

# 安装系统依赖（git 用于自我进化 PR 推送）
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p data/daily_logs data/logs_archive data/mindmaps data/backups data/reports

# 暴露端口（Render 自动注入 PORT 环境变量，config.py 兼容处理）
EXPOSE 10000

# 健康检查（TCP 端口探测，不依赖 HTTP 路由）
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import socket,os; s=socket.socket(); s.settimeout(3); s.connect(('localhost',int(os.environ.get('PORT','10000')))); s.close()"

# 环境变量（Render 通过 render.yaml / 控制台注入，此处为默认值）
ENV DEVPARTNER_HOST=0.0.0.0
ENV DEVPARTNER_TRANSPORT=sse
ENV DEVPARTNER_DATA_ROOT=data
ENV PYTHONUNBUFFERED=1
ENV DEVPARTNER_MODE=local
# PORT 由 Render 自动注入，config.py 已做 fallback 处理
# DEVPARTNER_MODE=local 强制自我进化走"本地模式"：只分析返回方案，不修改容器文件
# GITHUB_TOKEN 需在 Render 控制台环境变量中设置（用于自我进化 PR）

# 启动命令
CMD ["python", "server.py"]
