# ============================================================
# DevPartner v6.0 - ModelScope 创空间专用 Dockerfile
# ============================================================
#
# ⚠️ 重要提示:
#   此 Dockerfile 用于 ModelScope 云端部署！
#   本地开发和云端部署的启动方式完全相同，都是 MCP 服务！
#
# 📍 区别仅在于访问地址:
#   - 本地:  http://127.0.0.1:7860/mcp
#   - 云端:  https://modelscope.cn/studios/Pisces43/Dev-partner/mcp
#
# 🎯 适用环境:
#   ModelScope Docker 创空间（云端部署）
#   ModelScope 会自动从项目根目录读取此文件并构建镜像
#
# 📋 部署要求:
#   ✅ 必须位于项目根目录（ModelScope 要求）
#   ✅ 端口固定为 7860（ModelScope 标准）
#   ✅ MCP 端点: /mcp (Streamable HTTP 协议)
#
# 🔄 v6.0 核心变更:
#   ❌ 不再使用 SSE 协议
#   ✅ 改用 Streamable HTTP + /mcp 端点
#   ✅ 客户端通过 POST http://host:7860/mcp 调用服务
#
# 📦 系统架构（两层）:
#   devpartner_tools/   → 工具层 (21个纯工具, 无状态)
#   devpartner_agent/   → 智能管家层 (67+个智能工具, 有状态)
#   server.py          → MCP 服务入口 (统一对外接口)
#
# ✨ 特性:
#   - 使用 Streamable HTTP + /mcp 端点（非 SSE）
#   - 自动检测并加载 /app/models/ 下的模型文件
#   - 支持 Dataset volume 挂载
#   - 内置健康检查和智能启动脚本
#   - 优雅的错误处理和降级模式
#
# 🔧 客户端调用方式:
#   POST http://localhost:7860/mcp
#   Content-Type: application/json
#   Body: { "jsonrpc": "2.0", "method": "tools/list", ... }
#
# 📦 构建方式:
#   ModelScope 平台自动构建（无需手动操作）
#
# 作者: DevPartner Team
# 版本: v6.0 | 更新: 2026-07-03


# ============================================================
# 基础镜像：Python 3.10 Slim（轻量级，适合云端部署）
# ============================================================
FROM python:3.10-slim

# 元数据标签
LABEL org.opencontainers.image.title="DevPartner v6.0 - ModelScope"
LABEL org.opencontainers.image.version="6.0.0"
LABEL org.opencontainers.image.description="DevPartner 双向成长仪表盘 + LLM 推理服务 (Streamable HTTP)"
LABEL org.opencontainers.image.authors="DevPartner Team"
LABEL org.opencontainers.image.platform="ModelScope Docker Space"
LABEL org.opencontainers.image.transport="streamable-http"

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# ============================================================
# 步骤 1: 安装系统依赖
# ============================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# 步骤 2: 安装 Python 依赖
# ============================================================

# 先复制依赖文件（利用Docker缓存层优化）
COPY requirements.txt .
COPY devpartner_agent/requirements.txt devpartner_agent/
COPY devpartner_tools/requirements.txt devpartner_tools/

# 安装核心依赖
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r devpartner_agent/requirements.txt && \
    pip install --no-cache-dir -r devpartner_tools/requirements.txt

# ============================================================
# 步骤 3: 复制应用代码
# ============================================================

# 复制所有源代码
COPY server.py .
COPY pyproject.toml .
COPY devpartner_tools/ devpartner_tools/
COPY devpartner_agent/ devpartner_agent/
COPY models/README.md models/

# ============================================================
# 步骤 4: 创建必要的目录结构
# ============================================================
RUN mkdir -p /app/data/databases \
    /app/data/daily_logs \
    /app/data/logs \
    /app/data/logs_archive \
    /app/data/backups \
    /app/data/reports \
    /app/data/temp \
    /app/data/memories \
    /app/models

# 创建模型目录说明文件
RUN echo "========================================" > /app/models/.modelspace-info && \
    echo "DevPartner v6.0 - ModelScope 创空间" >> /app/models/.modelspace-info && \
    echo "========================================" >> /app/models/.modelspace-info && \
    echo "" >> /app/models/.modelspace-info && \
    echo "此目录用于存放 LLM 推理所需的 GGUF 模型文件" >> /app/models/.modelspace-info && \
    echo "" >> /app/models/.modelspace-info && \
    echo "模型文件来源（按优先级）:" >> /app/models/.modelspace-info && \
    echo "  1. Dataset volume 挂载（推荐）" >> /app/models/.modelspace-info && \
    echo "  2. 运行时下载（需配置 MODEL_URL）" >> /app/models/.modelspace-info && \
    echo "" >> /app/models/.modelspace-info && \
    echo "当前配置:" >> /app/models/.modelspace-info && \
    echo "  默认模型路径: /app/models/Qwen3.5-9B-Q4_1.gguf" >> /app/models/.modelspace-info && \
    echo "  端口: 7860" >> /app/models/.modelspace-info && \
    echo "  传输协议: Streamable HTTP" >> /app/models/.modelspace-info

# ============================================================
# 步骤 5: 条件性复制模型文件（如果存在）
# ============================================================
RUN if [ -f "models/*.gguf" ] || [ -f "models/*.gguf.part" ]; then \
        cp models/*.gguf* /app/models/ 2>/dev/null || true; \
    fi

# ============================================================
# 步骤 6: 复制启动脚本和健康检查脚本
# ============================================================
COPY scripts/start_modelscope.sh /app/start_modelscope.sh
COPY scripts/healthcheck.py /app/healthcheck.py
RUN chmod +x /app/start_modelscope.sh /app/healthcheck.py

# ============================================================
# 步骤 7: 暴露端口（ModelScope 要求）
# ============================================================
EXPOSE 7860

# ============================================================
# 步骤 8: 健康检查（使用独立脚本）
# ============================================================
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python /app/healthcheck.py

# ============================================================
# 步骤 9: 设置启动命令
# ============================================================
CMD ["/bin/bash", "/app/start_modelscope.sh"]