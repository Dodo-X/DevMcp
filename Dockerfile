# DevPartner v7.3.0 - 容器镜像
# 自动构建 → 启动 python server.py 7860 → MCP (Streamable HTTP)
# 推理由宿主机 Ollama 提供（HTTP API），镜像内不再包含 GGUF 模型

FROM python:3.10-slim

LABEL org.opencontainers.image.title="DevPartner v7.3.0"
LABEL org.opencontainers.image.version="7.3.0"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（Ollama 推理通过标准库 urllib，无需额外推理库）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY server.py pyproject.toml ./
COPY devpartner_tools/ devpartner_tools/
COPY devpartner_agent/ devpartner_agent/

# 数据目录
RUN mkdir -p /app/data/{databases,logs,reports,memories}

# 模型由宿主机 Ollama 管理，容器内不存放 GGUF 文件。
# 启动前请确保宿主机已运行 Ollama 并拉取所需模型（如 ollama pull qwen3）。
# 如 Ollama 不在本机，设置环境变量 OLLAMA_BASE_URL 指向其地址。

# 启动脚本 + 健康检查
COPY scripts/start_modelscope.sh /app/start_modelscope.sh
COPY scripts/healthcheck.py /app/healthcheck.py
RUN chmod +x /app/start_modelscope.sh /app/healthcheck.py

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python /app/healthcheck.py

CMD ["/bin/bash", "/app/start_modelscope.sh"]