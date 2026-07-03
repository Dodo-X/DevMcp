# DevPartner MCP Server v5.1.0
# ModelScope 创空间部署用 Docker 镜像
#
# 构建: docker build -t devpartner .
# 运行: docker run -p 7860:7860 -v $(pwd)/data:/app/data devpartner

# ============================================================
# 阶段 1: 构建阶段
# ============================================================
FROM python:3.10-slim AS builder

WORKDIR /app

# 安装构建依赖
COPY pyproject.toml .
COPY devpartner_agent/pyproject.toml devpartner_agent/
COPY devpartner_agent/requirements.txt devpartner_agent/
COPY devpartner_tools/pyproject.toml devpartner_tools/
COPY devpartner_tools/requirements.txt devpartner_tools/

# 安装 Python 依赖到 /install 目录
RUN pip install --no-cache-dir --target=/install \
    fastmcp>=0.3.0 \
    httpx>=0.24.0 \
    pyyaml>=6.0 \
    watchdog>=3.0.0

# ============================================================
# 阶段 2: 运行阶段
# ============================================================
FROM python:3.10-slim

# 元数据
LABEL org.opencontainers.image.title="DevPartner MCP Server"
LABEL org.opencontainers.image.version="5.2.0"
LABEL org.opencontainers.image.description="DevPartner MCP 统一服务器 v5.2 - 会话管理 + 知识图谱 + Web Dashboard"
LABEL org.opencontainers.image.authors="DevPartner Team"

WORKDIR /app

# 从构建阶段复制依赖
COPY --from=builder /install /usr/local/lib/python3.10/site-packages/

# 复制应用代码
COPY server.py .
COPY pyproject.toml .
COPY devpartner_tools/ devpartner_tools/
COPY devpartner_agent/ devpartner_agent/

# 创建运行时数据目录（容器启动时会挂载 volume）
RUN mkdir -p /app/data/databases \
    /app/data/daily_logs \
    /app/data/logs \
    /app/data/logs_archive \
    /app/data/backups \
    /app/data/reports \
    /app/data/temp \
    /app/data/memories

# ModelScope 创空间要求暴露 7860 端口
EXPOSE 7860

# 健康检查：每 60 秒检查进程是否存活
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# ModelScope 创空间通过环境变量指定端口
# 默认 SSE 模式在 7860 端口启动
ENV MCP_PORT=7860

# 启动命令
CMD ["sh", "-c", "python server.py sse ${MCP_PORT}"]
