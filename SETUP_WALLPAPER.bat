@echo off
echo ========================================
echo DeepSeek Harness 壁纸插件设置工具
echo ========================================
echo.

echo 步骤 1: 检查图片是否存在...
if exist "frontend\public\wallpaper.jpg" (
    echo ✅ 找到壁纸图片: frontend\public\wallpaper.jpg
) else (
    echo ❌ 未找到壁纸图片
    echo.
    echo 请将你的动漫风景图保存到:
    echo C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\frontend\public\wallpaper.jpg
    echo.
    pause
    exit /b 1
)

echo.
echo 步骤 2: 检查插件文件...
if exist "frontend\public\wallpaper.js" (
    echo ✅ 壁纸插件已安装
) else (
    echo ❌ 壁纸插件文件不存在
    pause
    exit /b 1
)

echo.
echo 步骤 3: 检查布局文件...
if exist "frontend\src\app\layout.tsx" (
    echo ✅ 布局文件已配置
) else (
    echo ❌ 布局文件不存在
    pause
    exit /b 1
)

echo.
echo ========================================
echo 设置完成！
echo ========================================
echo.
echo 下一步:
echo 1. 重启开发服务器（如果正在运行）
echo 2. 打开浏览器访问 http://localhost:3000
echo 3. 打开浏览器控制台 (F12)
echo 4. 运行以下命令设置壁纸:
echo.
echo    window.__DSH_WALLPAPER__.setWallpaper('/wallpaper.jpg', '/wallpaper.jpg');
echo.
echo 5. 刷新页面享受新壁纸！
echo.
pause
