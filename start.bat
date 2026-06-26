@echo off
REM ========================================
REM  devPartner 启动脚本
REM ========================================

echo.
echo ========================================
echo   devPartner - 自我进化 MCP 服务
echo ========================================

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查依赖
echo [检查] 依赖安装状态...
pip show fastmcp >nul 2>&1
if %errorlevel% neq 0 (
    echo [安装] 正在安装依赖...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

REM 检查 Ollama
echo [检查] Ollama 服务状态...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] Ollama 服务未运行，AI分析功能将不可用
    echo         请先启动: ollama serve
) else (
    echo [就绪] Ollama 已连接
)

REM 启动服务
echo.
echo [启动] devPartner 服务...
echo         地址: http://0.0.0.0:8080
echo         协议: SSE (MCP)
echo         按 Ctrl+C 停止服务
echo ========================================
echo.

python server.py

pause
