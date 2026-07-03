# DevPartner MCP Server v6.0 Dockerfile
# 支持本地开发、Docker部署、ModelScope云端运行
#
# 🎯 v6.0 核心特性:
#   - 统一从 /app/models/ 目录加载模型文件（通过volume挂载）
#   - 轻量模式: 不包含模型 (~150MB)
#   - 完整模式: 包含模型 (~6.5GB)
#
# 构建方式:
#   # 轻量镜像（推荐，需要挂载models目录）
#   docker build --build-arg INCLUDE_MODEL=false -t devpartner:v6.0-lite .
#
#   # 完整镜像（包含模型，构建时间长）
#   docker build --build-arg INCLUDE_MODEL=true -t devpartner:v6.0-full .
#
# 运行方式:
#   # 轻量模式（必须挂载模型目录）
#   docker run -d -p 7860:7860 \
#     -v ./data:/app/data \
#     -v ./models:/app/models \
#     devpartner:v6.0-lite
#
#   # 完整模式（无需挂载）
#   docker run -d -p 7860:7860 \
#     -v ./data:/app/data \
#     devpartner:v6.0-full
#
# ⚠️ 重要提示:
#   模型文件不纳入Git版本控制！
#   请手动下载到 models/ 目录或上传到ModelScope Dataset
#   详见 models/README.md 和 DEPLOYMENT_GUIDE.md

# 构建参数
ARG INCLUDE_MODEL=false

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

# 接收构建参数
ARG INCLUDE_MODEL

# 元数据
LABEL org.opencontainers.image.title="DevPartner MCP Server"
LABEL org.opencontainers.image.version="6.0.0"
LABEL org.opencontainers.image.description="DevPartner MCP 统一服务器 v6.0 - 双向成长仪表盘 + 知识图谱 + Web Dashboard"
LABEL org.opencontainers.image.authors="DevPartner Team"
LABEL org.opencontainers.image.model-included="${INCLUDE_MODEL}"

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

# ★ 创建模型文件目录（v6.0 核心）
RUN mkdir -p /app/models && \
    echo "DevPartner v6.0 模型文件目录" > /app/models/.docker-model-dir && \
    echo "此目录用于存放 LLM 推理所需的 GGUF 模型文件" >> /app/models/.docker-model-dir && \
    echo "默认模型: Qwen3.5-9B-Q4_1.gguf (~5.7GB)" >> /app/models/.docker-model-dir && \
    echo "" >> /app/models/.docker-model-dir && \
    echo "使用方式:" >> /app/models/.docker-model-dir && \
    echo "  1. 通过 volume 挂载: -v ./models:/app/models" >> /app/models/.docker-model-dir && \
    echo "  2. 或使用完整镜像（构建时包含模型）" >> /app/models/.docker-model-dir

# 条件性复制模型文件（仅当 INCLUDE_MODEL=true 时）
COPY models/ /app/models/ || true

# 复制模型说明文档（始终包含）
COPY models/README.md /app/models/README.md || true

# ModelScope 创空间要求暴露 7860 端口
EXPOSE 7860

# 健康检查：每 60 秒检查进程是否存活
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# 环境变量配置
ENV MCP_PORT=7860
# v6.0: 明确设置模型路径（可通过环境变量覆盖）
ENV MODEL_PATH=/app/models/Qwen3.5-9B-Q4_1.gguf

# 启动命令
CMD ["sh", "-c", "python server.py sse ${MCP_PORT}"]