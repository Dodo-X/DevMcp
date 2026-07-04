#!/bin/bash
set -e

# 默认配置
export MODEL_PATH=${MODEL_PATH:-"/app/models/Qwen3.5-9B-Q4_1.gguf"}
export MCP_PORT=7860
export MODEL_SOURCE=${MODEL_SOURCE:-"auto"}
# ModelScope 创空间持久化缓存目录（容器崩溃后不丢失）
MODELSCOPE_CACHE=${MODELSCOPE_CACHE:-"/mnt/workspace/modelscope_cache"}

echo "DevPartner v6.0.3 | 端口=${MCP_PORT} | 模型=${MODEL_PATH##*/}"

# ── 模型检查 ──
if [ -f "${MODEL_PATH}" ]; then
    echo "[OK] 模型就绪: $(du -h "${MODEL_PATH}" | cut -f1)"

# 优先检查持久化缓存中是否有已下载的模型
elif [ -d "${MODELSCOPE_CACHE}" ] && ls "${MODELSCOPE_CACHE}"/**/*.gguf 2>/dev/null | head -1; then
    echo "[INFO] 从持久化缓存恢复模型..."
    mkdir -p /app/models
    find "${MODELSCOPE_CACHE}" -name "*.gguf" -exec cp {} /app/models/ \; 2>/dev/null
    if [ -f "${MODEL_PATH}" ]; then
        echo "[OK] 模型从缓存恢复: $(du -h "${MODEL_PATH}" | cut -f1)"
    fi

else
    echo "[WARN] 模型缺失: ${MODEL_PATH}"
    if [ -n "${MODELSCOPE_TOKEN}" ]; then
        echo "[INFO] 从 ModelScope 下载模型..."
        python3 -c "
import os, glob, shutil
from modelscope import snapshot_download
mid = os.environ.get('MODELSCOPE_MODEL_ID', 'Pisces43/Dev-partner-model')
path = snapshot_download(mid, token=os.environ.get('MODELSCOPE_TOKEN', ''), cache_dir='${MODELSCOPE_CACHE}', revision='master')
for g in glob.glob(os.path.join(path, '*.gguf')):
    dest = os.path.join('/app/models', os.path.basename(g))
    if g != dest: shutil.copy2(g, dest)
    print(f'DOWNLOAD_SUCCESS={dest}')
" && echo "[OK] 模型下载完成" || { echo "[WARN] 下载失败，LLM功能降级"; export MODEL_PATH=""; }
    else
        echo "[INFO] 未配置 MODELSCOPE_TOKEN，LLM功能降级"
        export MODEL_PATH=""
    fi
fi

# ── 数据目录 ──
mkdir -p /app/data/{databases,logs,reports,memories}
echo "[OK] 数据目录就绪"

# ── 启动 ──
echo "启动 MCP 服务..."
exec python server.py ${MCP_PORT}
