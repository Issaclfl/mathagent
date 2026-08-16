@echo off
chcp 65001 >nul
title ModAgent 数学建模智能体
cd /d "%~dp0"

echo ============================================
echo   ModAgent 数学建模智能体 - 一键启动
echo ============================================
echo.

REM ── 检查 Python 依赖 ──────────────────────────
python -c "import fastapi, uvicorn, requests, yaml" 2>nul
if errorlevel 1 (
    echo [1/3] 安装 Python 依赖...
    pip install -r requirements.txt
) else (
    echo [1/3] Python 依赖已就绪
)

REM ── 检查前端依赖 ──────────────────────────────
if not exist "frontend\node_modules" (
    echo [2/3] 安装前端依赖...
    pushd frontend
    call npm install
    popd
) else (
    echo [2/3] 前端依赖已就绪
)

echo [3/3] 启动服务...
echo.
echo   前端: http://localhost:3000
echo   后端: http://localhost:8000
echo.
echo   按 Ctrl+C 可停止服务
echo.

REM ── 启动后端（新窗口）─────────────────────────
start "ModAgent API" cmd /k "cd /d "%~dp0" && python api.py"

REM ── 启动前端（当前窗口）───────────────────────
pushd frontend
call npm run dev
popd
