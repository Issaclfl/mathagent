@echo off
echo ========================================
echo DeepSeek Harness dsh-ui-web 插件安装程序
echo ========================================
echo.

echo 检查 package.json 是否存在...
if exist "frontend\package.json" (
    echo ✅ 找到 package.json: frontend\package.json
) else (
    echo ❌ 未找到 package.json
    echo 请确保在正确的目录下运行此脚本
    pause
    exit /b 1
)

echo.
echo 检查 node_modules 是否存在...
if exist "frontend\node_modules" (
    echo ✅ 找到 node_modules: frontend\node_modules
) else (
    echo ❌ 未找到 node_modules
    echo 请先运行: npm install 或 pnpm install
    pause
    exit /b 1
)

echo.
echo ========================================
echo 安装 dsh-ui-web 插件
echo ========================================
echo.
echo 正在安装 @captain1275/dsh-ui-web 插件...

cd frontend
call npm install @captain1275/dsh-ui-web --save
if %errorlevel% neq 0 (
    echo ❌ 插件安装失败
    pause
    exit /b 1
)
cd ..

echo.
echo ========================================
echo 安装完成！
echo ========================================
echo.
echo 下一步操作:
echo 1. 重启开发服务器（如果正在运行）
echo 2. 打开浏览器访问 http://localhost:3000
echo 3. 打开浏览器控制台 (F12)
echo 4. 运行以下命令启用插件:
echo.
echo    window.__DSH_UI_WEB__ = require('@captain1275/dsh-ui-web');
echo.
echo 5. 刷新页面享受新功能！
echo.
pause
