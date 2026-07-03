# ============================================================
# DevPartner v6.0 - ModelScope 创空间专用 Dockerfile
# ============================================================
#
# ⚠️ 重要提示:
#   此 Dockerfile 仅供 ModelScope 云端部署使用！
#   本地开发请直接运行: python server.py 或 start.bat
#   本地不需要使用 Docker！
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
COPY models/*.gguf* /app/models/ 2>/dev/null || true

# ============================================================
# 步骤 6: 创建启动脚本（智能模型检测+服务启动）
# ============================================================
RUN cat > /app/start_modelscope.sh << 'EOF'
#!/bin/bash
set -e

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     ⚡ DevPartner v6.0 · ModelScope 创空间 启动器       ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║                                                           ║"
echo "║   🛠️ 工具层 (Tools): 21个纯工具                          ║"
echo "║   🤖 智能层 (Agent): 67+个智能工具                       ║"
echo "║   🌱 成长视角: 用户技能 + 系统进化                        ║"
echo "║   ⚙️ 运维视角: 系统监控 + 任务队列                        ║"
echo "║   🤖 LLM推理: ModelScope 云端统一部署                     ║"
echo "║   🔗 MCP协议: /mcp 端点 (Streamable HTTP)               ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# 设置默认值
export MODEL_PATH=${MODEL_PATH:-"/app/models/Qwen3.5-9B-Q4_1.gguf"}
export MCP_PORT=7860
export MODEL_SOURCE=${MODEL_SOURCE:-"auto"}

echo "[INFO] 环境信息:"
echo "       工作目录: $(pwd)"
echo "       MCP端口: ${MCP_PORT} (固定，ModelScope要求)"
echo "       MCP端点: http://localhost:${MCP_PORT}/mcp"
echo "       模型路径: ${MODEL_PATH}"
echo "       模型来源: ${MODEL_SOURCE}"
echo "       传输协议: Streamable HTTP (/mcp端点)"
echo ""

# ============================================================
# 模型文件检测与准备
# ============================================================
echo "[步骤 1/3] 检查模型文件..."

if [ -f "${MODEL_PATH}" ]; then
    MODEL_SIZE=$(du -h "${MODEL_PATH}" | cut -f1)
    echo "       ✅ 模型文件已存在: $(basename ${MODEL_PATH}) (${MODEL_SIZE})"
else
    echo "       ⚠️ 模型文件不存在: ${MODEL_PATH}"
    echo ""

    # 尝试自动下载（如果配置了 URL）
    if [ -n "${MODEL_URL}" ] && [ "${MODEL_SOURCE}" = "remote" ]; then
        echo "[INFO] 正在从远程下载模型..."
        echo "       URL: ${MODEL_URL}"

        # 创建目录
        mkdir -p "$(dirname ${MODEL_PATH})"

        # 下载文件（支持断点续传）
        curl -L -o "${MODEL_PATH}" "${MODEL_URL}" \
            --progress-bar \
            --retry 3 \
            --retry-delay 5 \
            --connect-timeout 30 || {
            echo "       ❌ 模型下载失败！"
            echo "       将以降级模式启动（LLM功能不可用）"
            export MODEL_PATH=""
        }

        if [ -f "${MODEL_PATH}" ]; then
            echo "       ✅ 模型下载完成"
        fi
    else
        echo "       ℹ️ 未配置远程下载地址"
        echo ""
        echo "       可选操作:"
        echo "         1. 上传模型到 Dataset 并挂载到 /app/models/"
        echo "         2. 设置环境变量 MODEL_URL 指定下载地址"
        echo "         3. 以降级模式运行（无 LLM 功能）"
        echo ""
        export MODEL_PATH=""
    fi
fi

echo ""

# ============================================================
# 数据库初始化
# ============================================================
echo "[步骤 2/3] 初始化数据目录..."

mkdir -p /app/data/databases \
     /app/data/logs \
     /app/data/reports \
     /app/data/memories

echo "       ✅ 数据目录已就绪"

echo ""

# ============================================================
# 启动服务（使用 Streamable HTTP + /mcp 端点）
# ============================================================
echo "[步骤 3/3] 启动 DevPartner MCP 服务..."
echo ""
echo "   ╔════════════════════════════════════════════════════╗"
echo "   ║  🚀 MCP服务正在启动...                             ║"
echo "   ╠════════════════════════════════════════════════════╣"
echo "   ║  🔗 MCP端点: http://localhost:${MCP_PORT}/mcp      ║"
echo "   ║  📊 Dashboard: http://localhost:${MCP_PORT}/dashboard║"
echo "   ║  🔧 API文档:   http://localhost:${MCP_PORT}/docs    ║"
echo "   ║  📈 健康检查: http://localhost:${MCP_PORT}/health   ║"
echo "   ║  🌐 协议:      Streamable HTTP                      ║"
echo "   ╚════════════════════════════════════════════════════╝"
echo ""
echo "   💡 客户端连接方式:"
echo "      POST http://localhost:${MCP_PORT}/mcp"
echo "      Content-Type: application/json"
echo ""

# ★ v6.0: 使用 Streamable HTTP 模式，通过 /mcp 端点对外提供服务
exec python server.py ${MCP_PORT}
EOF

# 设置执行权限
RUN chmod +x /app/start_modelscope.sh

# ============================================================
# 步骤 7: 暴露端口（ModelScope 要求）
# ============================================================
EXPOSE 7860

# ============================================================
# 步骤 8: 健康检查
# ============================================================
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "
import urllib.request
import sys
try:
    response = urllib.request.urlopen('http://localhost:7860/dashboard', timeout=5)
    print('✅ 服务正常运行')
    sys.exit(0)
except Exception as e:
    print(f'❌ 健康检查失败: {e}')
    sys.exit(1)
" || exit 1

# ============================================================
# 步骤 9: 设置启动命令
# ============================================================
CMD ["/bin/bash", "/app/start_modelscope.sh"]