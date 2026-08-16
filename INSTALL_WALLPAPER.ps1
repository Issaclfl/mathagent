# DeepSeek Harness 壁纸插件安装脚本
# PowerShell 版本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DeepSeek Harness 壁纸插件安装程序" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查当前目录
$currentDir = Get-Location
Write-Host "当前目录: $currentDir" -ForegroundColor Yellow

# 检查图片是否存在
$imagePath = "frontend\public\wallpaper.jpg"
if (Test-Path $imagePath) {
    Write-Host "✅ 找到壁纸图片: $imagePath" -ForegroundColor Green
} else {
    Write-Host "❌ 未找到壁纸图片" -ForegroundColor Red
    Write-Host ""
    Write-Host "请将你的动漫风景图保存到:" -ForegroundColor Yellow
    Write-Host "  $currentDir\$imagePath" -ForegroundColor White
    Write-Host ""
    Write-Host "按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# 检查插件文件
$pluginPath = "frontend\public\wallpaper.js"
if (Test-Path $pluginPath) {
    Write-Host "✅ 壁纸插件已安装: $pluginPath" -ForegroundColor Green
} else {
    Write-Host "❌ 壁纸插件文件不存在: $pluginPath" -ForegroundColor Red
    Write-Host "按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# 检查布局文件
$layoutPath = "frontend\src\app\layout.tsx"
if (Test-Path $layoutPath) {
    Write-Host "✅ 布局文件已配置: $layoutPath" -ForegroundColor Green
} else {
    Write-Host "❌ 布局文件不存在: $layoutPath" -ForegroundColor Red
    Write-Host "按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "安装完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步操作:" -ForegroundColor Yellow
Write-Host "1. 重启开发服务器（如果正在运行）" -ForegroundColor White
Write-Host "2. 打开浏览器访问 http://localhost:3000" -ForegroundColor White
Write-Host "3. 打开浏览器控制台 (F12)" -ForegroundColor White
Write-Host "4. 运行以下命令设置壁纸:" -ForegroundColor White
Write-Host ""
Write-Host "   window.__DSH_WALLPAPER__.setWallpaper('/wallpaper.jpg', '/wallpaper.jpg');" -ForegroundColor Green
Write-Host ""
Write-Host "5. 刷新页面享受新壁纸！" -ForegroundColor White
Write-Host ""
Write-Host "按任意键退出..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
