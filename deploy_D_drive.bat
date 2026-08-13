@echo off
chcp 65001 >nul 2>&1
title Potential Tools - D盘部署脚本
color 0A

echo ════════════════════════════════════════════════════════════
echo         Potential Tools - 一键部署到 D 盘
echo ════════════════════════════════════════════════════════════
echo.

:: ===== 配置区 =====
set "DEPLOY_DIR=D:\Potential-tools"
set "REPO_URL=https://github.com/wangys38-cyber/Potential-tools.git"
set "PORT=5001"
:: ==================

:: 检查 Python
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
echo [OK] Python %PY_VER% 已安装

:: 检查 Git
echo.
echo [2/6] 检查 Git 环境...
git --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Git，请先安装 Git
    echo 下载地址: https://git-scm.com/download/win
    pause
    exit /b 1
)
echo [OK] Git 已安装

:: 创建部署目录
echo.
echo [3/6] 创建部署目录 %DEPLOY_DIR% ...
if exist "%DEPLOY_DIR%" (
    echo [提示] 目录已存在，将更新代码...
    cd /d "%DEPLOY_DIR%"
    git pull origin main 2>nul || git pull origin master 2>nul
) else (
    mkdir "%DEPLOY_DIR%"
    echo [OK] 目录已创建
    echo.
    echo [4/6] 克隆仓库代码...
    git clone %REPO_URL% "%DEPLOY_DIR%"
    if errorlevel 1 (
        echo [错误] 克隆失败，请检查网络连接
        pause
        exit /b 1
    )
)
echo [OK] 代码已就位
cd /d "%DEPLOY_DIR%"

:: 创建虚拟环境
echo.
echo [5/6] 创建虚拟环境并安装依赖...
if not exist "venv" (
    python -m venv venv
    echo [OK] 虚拟环境已创建
) else (
    echo [提示] 虚拟环境已存在，跳过创建
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 升级 pip
python -m pip install --upgrade pip >nul 2>&1

:: 安装依赖
echo [正在] 安装 Python 依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo [OK] Python 依赖安装完成

:: 安装 Playwright Chromium
echo.
echo [正在] 安装 Playwright Chromium（PDF生成需要，可能需要几分钟）...
playwright install chromium
if errorlevel 1 (
    echo [警告] Playwright Chromium 安装失败，PDF转换功能将不可用
    echo [提示] 可稍后手动运行: playwright install chromium
) else (
    echo [OK] Playwright Chromium 安装完成
)

:: 创建启动脚本
echo.
echo [6/6] 生成启动脚本...
(
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title Potential Tools - 本地运行
    echo color 0A
    echo echo ════════════════════════════════════════════════════════════
    echo echo         Potential Tools - 启动中...
    echo echo ════════════════════════════════════════════════════════════
    echo echo.
    echo cd /d "%%~dp0"
    echo call venv\Scripts\activate.bat
    echo set "ALLOW_GUEST=true"
    echo set "PORT=%PORT%"
    echo echo [启动] 访问地址: http://localhost:%PORT%
    echo echo [提示] 按 Ctrl+C 停止服务
    echo echo.
    echo python app.py
    echo pause
) > "%DEPLOY_DIR%\start_app.bat"
echo [OK] 启动脚本已生成: %DEPLOY_DIR%\start_app.bat

:: 完成
echo.
echo ════════════════════════════════════════════════════════════
echo         部署完成！
echo ════════════════════════════════════════════════════════════
echo.
echo  部署目录: %DEPLOY_DIR%
echo  访问地址: http://localhost:%PORT%
echo.
echo  启动方式: 双击 start_app.bat
echo.
echo  注意事项:
echo    - 首次启动后访问 http://localhost:%PORT%
echo    - 默认开启访客模式 (ALLOW_GUEST=true)
echo    - 如需 OAuth 登录，请编辑 config_oauth.json 配置飞书/Google
echo    - PDF转换功能需要 Chromium（已自动安装）
echo.
pause
