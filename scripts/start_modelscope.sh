#!/bin/bash
set -e

# 默认配置（v7.3.0: 推理由宿主机 Ollama 提供，不再管理 GGUF 文件）
export MCP_PORT=7860
export OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-"http://host.docker.internal:11434"}
export OLLAMA_MODEL=${OLLAMA_MODEL:-"qwen3"}

echo "DevPartner v7.3.0 | 端口=${MCP_PORT} | Ollama=${OLLAMA_BASE_URL} | 模型=${OLLAMA_MODEL}"

# ── Ollama 检查 ──
if curl -fsS "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1; then
    echo "[OK] Ollama 服务可连接: ${OLLAMA_BASE_URL}"
else
    echo "[WARN] 未检测到 Ollama 服务: ${OLLAMA_BASE_URL}"
    echo "[INFO] 请先在宿主机安装并启动 Ollama，并拉取模型: ollama pull ${OLLAMA_MODEL}"
    echo "[INFO] 系统将以降级模式运行（规则引擎兜底，无 LLM 推理）"
fi

# ── 数据目录 ──
mkdir -p /app/data/{databases,logs,reports,memories}
echo "[OK] 数据目录就绪"

# ── 启动 ──
echo "启动 MCP 服务..."
exec python server.py ${MCP_PORT}
