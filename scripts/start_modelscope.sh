#!/bin/bash
set -e

# 默认配置
export MODEL_PATH=${MODEL_PATH:-"/app/models/Qwen3.5-9B-Q4_1.gguf"}
export MCP_PORT=7860
export MODEL_SOURCE=${MODEL_SOURCE:-"auto"}

echo "DevPartner v6.0 | 端口=${MCP_PORT} | 模型=${MODEL_PATH##*/}"

# ── 模型检查 ──
if [ -f "${MODEL_PATH}" ]; then
    echo "[OK] 模型就绪: $(du -h "${MODEL_PATH}" | cut -f1)"
else
    echo "[WARN] 模型缺失: ${MODEL_PATH}"
    if [ -n "${MODELSCOPE_TOKEN}" ]; then
        echo "[INFO] 从 ModelScope 下载模型..."
        python3 -c "
import os, glob, shutil
from modelscope import snapshot_download
mid = os.environ.get('MODELSCOPE_MODEL_ID', 'Pisces43/Dev-partner-model')
path = snapshot_download(mid, token=os.environ.get('MODELSCOPE_TOKEN', ''), cache_dir='/mnt/workspace/modelscope_cache', revision='master')
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
