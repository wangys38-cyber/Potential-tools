@echo off
chcp 65001 >nul 2>&1
title Potential Tools - 本地运行
color 0A

echo ════════════════════════════════════════════════════════════
echo         Potential Tools - 启动中...
echo ════════════════════════════════════════════════════════════
echo.

cd /d "%~dp0"

:: 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [错误] 未找到虚拟环境，请先运行 deploy_D_drive.bat
    pause
    exit /b 1
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 设置环境变量
set "ALLOW_GUEST=true"
set "PORT=5001"
set "DB_DIR=%~dp0data"

:: 数据库配置（留空使用 SQLite，设置 DATABASE_URL 使用 PostgreSQL）
:: set "DATABASE_URL=postgresql://user:password@host:port/dbname"

:: OAuth 配置（如需飞书/Google 登录，请取消注释并填入真实值）
:: set "FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx"
:: set "FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
:: set "FEISHU_REDIRECT_URI=http://localhost:5001/auth/feishu/callback"

:: AI 配置（如需 AI 功能，请填入 DashScope API Key）
:: set "AI_API_KEY=sk_xxxxxxxxxxxxxxxx"

echo [配置] 端口: %PORT%
echo [配置] 访客模式: 已开启
echo [配置] 数据目录: %DB_DIR%
echo [配置] 数据库: SQLite (如需 PostgreSQL 请设置 DATABASE_URL)
echo.
echo [启动] 访问地址: http://localhost:%PORT%
echo [提示] 按 Ctrl+C 停止服务
echo.

:: 创建数据目录
if not exist "%DB_DIR%" mkdir "%DB_DIR%"

:: 启动应用
python app.py

pause
