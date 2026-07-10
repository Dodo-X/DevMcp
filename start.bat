@echo off
chcp 65001 >nul
for /f "tokens=2 delims= " %%v in ('python -c "from devpartner_agent.core.config import get_project_version; print(get_project_version())" 2^>nul') do set DEV_VERSION=%%v
if "%DEV_VERSION%"=="" set DEV_VERSION=6.0.0
title DevPartner v%DEV_VERSION% - 运维面板 + MCP 服务
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║       ⚡ DevPartner v%DEV_VERSION% · 运维面板 + MCP 服务        ║
echo ╠══════════════════════════════════════════════════════════════╣
echo ║                                                              ║
echo ║   🖥️ 运维视角: 系统监控 + 异步任务队列                        ║
echo ║   🤖 LLM推理: 本地 Ollama HTTP API                            ║
echo ║   🔌 MCP服务: streamable-http /mcp 端点                       ║
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
python -c "import fastapi; import uvicorn; import ollama; print('   ✅ 核心依赖已安装')" 2>nul
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
REM 步骤 3: 检查 Ollama 服务（v7.3.0 核心：本地 Ollama HTTP API）
REM ============================================================
echo.
echo [步骤 3/4] 检查 Ollama 服务...
echo   📍 Ollama 地址: %OLLAMA_BASE_URL%

python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen((os.environ.get('OLLAMA_BASE_URL') or 'http://localhost:11434')+'/api/tags',timeout=3) else 1)" 2>nul
set CHECK_RESULT=%errorlevel%

if %CHECK_RESULT% equ 0 (
    echo   ✅ Ollama 服务可连接
) else (
    echo   ⚠️ 未检测到 Ollama 服务！
    echo.
    echo   请选择操作：
    echo     1. 继续启动（LLM 推理不可用，自动降级到规则引擎）
    echo     2. 退出并查看 Ollama 安装指南
    echo.
    choice /C 12 /N /M "请选择 [1-2]: "
    if errorlevel 2 (
        echo.
        echo   📥 Ollama 安装方法：
        echo     方式一: 访问 https://ollama.com/download 安装并启动 Ollama
        echo     方式二: ollama pull qwen3   （拉取推理模型）
        echo     方式三: 设置 OLLAMA_BASE_URL 指向远程 Ollama
        echo.
        pause
        exit /b 0
    )
    echo   ⚠️ 将以降级模式启动（无 LLM 推理能力，规则引擎兜底）
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
echo   ║  🔧 API文档:   http://localhost:7860/docs               ║
echo   ║  🔌 MCP端点:   http://localhost:7860/mcp                ║
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