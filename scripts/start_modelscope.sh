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
        echo "       ℹ️ 未配置远程下载地址 (MODEL_URL)"
        echo ""

        # 🎯 尝试从 ModelScope 自动下载（使用 API Token）
        if [ -n "${MODELSCOPE_TOKEN}" ]; then
            echo "[INFO] 检测到 ModelScope Token，尝试自动下载模型..."
            echo "       模型ID: ${MODELSCOPE_MODEL_ID:-Pisces43/Dev-partner-model}"
            echo ""

            # 使用 Python 脚本下载（支持断点续传 + Token 认证）
            python3 << 'PYTHON_DOWNLOAD_SCRIPT'
import os
import sys

try:
    from modelscope import snapshot_download

    model_id = os.environ.get('MODELSCOPE_MODEL_ID', 'Pisces43/Dev-partner-model')
    token = os.environ.get('MODELSCOPE_TOKEN', '')
    target_dir = '/app/models'

    print(f"       📥 开始从 ModelScope 下载...")
    print(f"       模型: {model_id}")
    print(f"       目标: {target_dir}")
    print(f"       认证: {'✅ 已配置Token' if token else '❌ 未配置Token'}")
    print()

    # 下载模型（使用 Token 认证私有仓库）
    model_path = snapshot_download(
        model_id=model_id,
        token=token,
        cache_dir='/mnt/workspace/modelscope_cache',  # 持久化缓存目录
        revision='master'
    )

    print(f"\n       ✅ 模型下载完成！")
    print(f"       位置: {model_path}")

    # 查找 .gguf 文件并复制到 /app/models/
    import glob
    gguf_files = glob.glob(os.path.join(model_path, '*.gguf'))

    if gguf_files:
        gguf_file = gguf_files[0]
        dest_file = os.path.join(target_dir, os.path.basename(gguf_file))

        # 复制文件（如果不在目标位置）
        if gguf_file != dest_file:
            import shutil
            shutil.copy2(gguf_file, dest_file)
            print(f"       ✅ 已复制到: {dest_file}")

        # 输出成功标记
        print(f"\nDOWNLOAD_SUCCESS={dest_file}")
    else:
        print("       ⚠️ 未找到 .gguf 文件")
        sys.exit(1)

except ImportError:
    print("       ❌ modelscope SDK 未安装")
    print("       请检查 requirements.txt 是否包含 modelscope>=1.9.0")
    sys.exit(1)
except Exception as e:
    print(f"       ❌ 下载失败: {str(e)}")
    sys.exit(1)

PYTHON_DOWNLOAD_SCRIPT

            # 检查 Python 脚本执行结果
            if [ $? -eq 0 ]; then
                # 查找刚下载的 .gguf 文件
                DOWNLOADED_MODEL=$(find /app/models -name "*.gguf" -type f | head -1)

                if [ -n "${DOWNLOADED_MODEL}" ] && [ -f "${DOWNLOADED_MODEL}" ]; then
                    export MODEL_PATH="${DOWNLOADED_MODEL}"
                    MODEL_SIZE=$(du -h "${MODEL_PATH}" | cut -f1)
                    echo ""
                    echo "       🎉 模型已成功下载并就绪!"
                    echo "       路径: ${MODEL_PATH} (${MODEL_SIZE})"
                else
                    echo "       ❌ 下载完成但未找到模型文件"
                    export MODEL_PATH=""
                fi
            else
                echo "       ❌ ModelScope 下载失败"
                echo ""
                echo "       💡 可能的原因:"
                echo "         1. Token 无效或过期"
                echo "         2. 模型 ID 不正确"
                echo "         3. 网络连接问题"
                echo ""
                echo "       📖 解决方案:"
                echo "         1. 检查环境变量 MODELSCOPE_TOKEN 是否正确"
                echo "         2. 确认模型 ID: Pisces43/Dev-partner-model"
                echo "         3. 或手动上传模型到 Dataset 并挂载"
                echo ""
                export MODEL_PATH=""
            fi
        else
            echo "       ⚠️ 未配置 ModelScope Token (MODELSCOPE_TOKEN)"
            echo ""
            echo "       💡 可选操作:"
            echo "         1. 配置环境变量 MODELSCOPE_TOKEN (推荐) ⭐"
            echo "         2. 上传模型到 Dataset 并挂载到 /app/models/"
            echo "         3. 以降级模式运行（无 LLM 功能）"
            echo ""
            echo "       📖 如何获取 Token (30秒搞定):"
            echo "         ① 访问: https://modelscope.cn/my/myaccesstoken"
            echo "         ② 点击 \"创建令牌\""
            echo "         ③ 复制 Token 并添加到创空间环境变量:"
            echo "            变量名: MODELSCOPE_TOKEN"
            echo "            变量值: <你的Token>"
            echo ""
            export MODEL_PATH=""
        fi
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