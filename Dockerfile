# devPartner v3.0 Dockerfile
# 适配 ModelScope 部署
FROM python:3.11-slim

LABEL maintainer="devPartner"
LABEL version="3.0.0"
LABEL description="全能 MCP 数据服务 - AI-Client-Driven 架构"

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN pip install --no-cache-dir --upgrade pip

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p data/daily_logs data/logs_archive data/mindmaps data/backups data/reports

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# 环境变量（ModelScope 部署时可覆盖）
ENV DEVPARTNER_HOST=0.0.0.0
ENV DEVPARTNER_PORT=8080
ENV DEVPARTNER_TRANSPORT=sse
ENV DEVPARTNER_DATA_ROOT=data
ENV PYTHONUNBUFFERED=1

# 启动命令
CMD ["python", "server.py"]
