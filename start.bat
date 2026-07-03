@echo off
chcp 65001 >nul
title DevPartner v6.0 - 双向成长仪表盘
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║       ⚡ DevPartner v6.0 · 双向成长仪表盘 启动器            ║
echo ╠══════════════════════════════════════════════════════════════╣
echo ║                                                              ║
echo ║   🌱 成长视角: 用户技能 + 系统进化                           ║
echo ║   ⚙️ 运维视角: 系统监控 + 任务队列                           ║
echo ║   🤖 LLM推理: 本地/Docker/云端统一加载                       ║
echo ║                                                              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

REM ============================================================
REM 步骤 1: 检查 Python 环境
REM ============================================================
echo [步骤 1/4] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo   ❌ Python 未安装或未添加到 PATH
    echo      请安装 Python 3.10+ 并添加到系统 PATH
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do echo   ✅ Python 版本: %%v

REM ============================================================
REM 步骤 2: 检查并安装依赖
REM ============================================================
echo.
echo [步骤 2/4] 检查项目依赖...
python -c "import fastapi; import uvicorn; import llama_cpp; print('   ✅ 核心依赖已安装')" 2>nul
if errorlevel 1 (
    echo   ⚠️ 部分依赖未安装，正在自动安装...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo   ❌ 依赖安装失败！请手动执行: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo   ✅ 依赖安装完成
)

REM ============================================================
REM 步骤 3: 检查模型文件（v6.0 核心：统一从 models/ 加载）
REM ============================================================
echo.
echo [步骤 3/4] 检查模型文件...
echo   📍 模型目录: .\models\
echo   🎯 目标文件: Qwen3.5-9B-Q4_1.gguf (~5.7GB)

REM 使用专门的检查脚本
python scripts/check_model.py
set CHECK_RESULT=%errorlevel%

if %CHECK_RESULT% equ 0 (
    echo   ✅ 模型检查通过
) else (
    echo   ⚠️ 模型文件不存在或损坏！
    echo.
    echo   请选择操作：
    echo     1. 继续启动（LLM 推理功能将不可用）
    echo     2. 退出并查看下载指南
    echo.
    choice /C 12 /N /M "请选择 [1-2]: "
    if errorlevel 2 (
        echo.
        echo   📥 模型下载方法：
        echo     方式一: python scripts/check_model.py （查看完整指南）
        echo     方式二: 打开 models\README.md 查看详细说明
        echo     方式三: 访问 ModelScope 手动下载
        echo.
        pause
        exit /b 0
    )
    echo   ⚠️ 将以降级模式启动（无 LLM 推理能力）
)

REM ============================================================
REM 步骤 4: 启动服务
REM ============================================================
echo.
echo [步骤 4/4] 启动 DevPartner 服务...
echo.
echo   ╔═════════════════════════════════════════════════════════╗
echo   ║  🚀 服务启动中...                                      ║
echo   ╠═════════════════════════════════════════════════════════╣
echo   ║  📊 Dashboard: http://localhost:7860/dashboard          ║
echo   ║  🔧 API文档:   http://localhost:7860/docs               ║
echo   ║  🛑 停止服务:   Ctrl+C                                   ║
echo   ╚═════════════════════════════════════════════════════════╝
echo.

REM 启动服务器（v6.0: Streamable HTTP + /mcp 端点，端口7860）
python server.py 7860

echo.
echo ═══════════════════════════════════════════════════════════
echo   服务已停止
echo   如需重启，请再次运行此脚本
echo ═══════════════════════════════════════════════════════════
pause