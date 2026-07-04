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
echo ""
echo "   📍 本地开发:"
echo "      POST http://127.0.0.1:${MCP_PORT}/mcp"
echo ""
echo "   ☁️ ModelScope 云端:"
echo "      POST https://modelscope.cn/studios/Pisces43/Dev-partner/mcp"
echo ""
echo "   ⚙️ 配置示例 (mcp.json):"
echo '      { "url": "http://127.0.0.1:'"${MCP_PORT}"'/mcp" }'
echo ""

# ★ v6.0: 使用 Streamable HTTP 模式，通过 /mcp 端点对外提供服务
exec python server.py ${MCP_PORT}