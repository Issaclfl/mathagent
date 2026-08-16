@echo off
echo ========================================
echo 启动 DeepSeek Harness 前端服务器
echo ========================================
echo.

cd /d "C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\frontend"

echo 检查依赖是否安装...
if not exist "node_modules" (
    echo 安装依赖中...
    call node ..\node_modules\npm\bin\npm-cli.js install
)

echo 启动开发服务器...
echo.
echo 服务器启动后，请访问: http://localhost:3000
echo 按 Ctrl+C 停止服务器
echo.

call node ..\node_modules\npm\bin\npm-cli.js run dev
