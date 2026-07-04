# DevPartner v6.0 - ModelScope 创空间
# 自动构建 → 启动 python server.py 7860 → MCP (Streamable HTTP) + Dashboard

FROM python:3.10-slim

LABEL org.opencontainers.image.title="DevPartner v6.0"
LABEL org.opencontainers.image.version="6.0.2"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY server.py pyproject.toml ./
COPY devpartner_tools/ devpartner_tools/
COPY devpartner_agent/ devpartner_agent/

# 数据目录
RUN mkdir -p /app/data/{databases,logs,reports,memories} /app/models

# 模型文件（打包进镜像，避免容器崩溃后重复下载）
# 如果你需要在构建时从 ModelScope 下载模型，取消下面注释并设置 MODELSCOPE_TOKEN：
# RUN pip install modelscope && \
#     MODELSCOPE_TOKEN="your_token" python3 -c "
# import os, glob, shutil
# from modelscope import snapshot_download
# path = snapshot_download('Pisces43/Dev-partner-model', token=os.environ['MODELSCOPE_TOKEN'], cache_dir='/tmp/msc_cache', revision='master')
# for g in glob.glob(os.path.join(path, '*.gguf')):
#     shutil.copy2(g, '/app/models/')
#     print(f'Model: {os.path.basename(g)}')
# " && rm -rf /tmp/msc_cache

# 启动脚本 + 健康检查
COPY scripts/start_modelscope.sh /app/start_modelscope.sh
COPY scripts/healthcheck.py /app/healthcheck.py
RUN chmod +x /app/start_modelscope.sh /app/healthcheck.py

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python /app/healthcheck.py

CMD ["/bin/bash", "/app/start_modelscope.sh"]
