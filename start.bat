@echo off
chcp 65001 >nul
title DevPartner v6.0 - 双向成长仪表盘
color 0A

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║     ⚡ DevPartner v6.0 · 双向成长仪表盘 启动器          ║
echo ╠═══════════════════════════════════════════════════════════╣
echo ║                                                           ║
echo ║   🌱 成长视角: 用户技能 + 系统进化                        ║
echo ║   ⚙️ 运维视角: 系统监控 + 任务队列                        ║
echo ║                                                           ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未安装或未添加到 PATH
    pause
    exit /b 1
)

REM 检查必要依赖
echo [INFO] 检查依赖...
python -c "import fastapi; import uvicorn; import llama_cpp; print('[OK] 核心依赖已安装')" 2>nul
if errorlevel 1 (
    echo [WARN] 部分依赖未安装，正在自动安装...
    pip install -q -r requirements.txt
)

REM 检查模型文件
echo.
echo [INFO] 检查模型文件...
if exist "models\Qwen3.5-9B-Q4_1.gguf" (
    for %%A in ("models\Qwen3.5-9B-Q4_1.gguf") do set MODEL_SIZE=%%~zA
    set /a MODEL_SIZE_MB=%MODEL_SIZE% / 1048576
    echo [OK] 模型文件存在 (约 %MODEL_SIZE_MB% MB)
) else (
    echo [WARN] 模型文件不存在！
    echo       请下载 Qwen3.5-9B-Q4_1.gguf 到 models/ 目录
    echo       或访问 models/README.md 获取下载链接
    echo.
    echo       是否继续启动？（LLM 功能将不可用）
    choice /C YN /M "继续"
    if errorlevel 2 exit /b 0
)

echo.
echo [INFO] 启动 DevPartner 服务...
echo        访问地址: http://localhost:7860/dashboard
echo        按 Ctrl+C 停止服务
echo.

REM 启动服务器（标准模式，非 SSE）
python server.py

pause