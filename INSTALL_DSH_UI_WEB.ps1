# DeepSeek Harness dsh-ui-web 插件安装脚本
# PowerShell 版本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DeepSeek Harness dsh-ui-web 插件安装程序" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查当前目录
$currentDir = Get-Location
Write-Host "当前目录: $currentDir" -ForegroundColor Yellow

# 检查 package.json 是否存在
$packageJsonPath = "frontend\package.json"
if (Test-Path $packageJsonPath) {
    Write-Host "✅ 找到 package.json: $packageJsonPath" -ForegroundColor Green
} else {
    Write-Host "❌ 未找到 package.json" -ForegroundColor Red
    Write-Host ""
    Write-Host "请确保在正确的目录下运行此脚本" -ForegroundColor Yellow
    Write-Host "按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# 检查 node_modules 是否存在
$nodeModulesPath = "frontend\node_modules"
if (Test-Path $nodeModulesPath) {
    Write-Host "✅ 找到 node_modules: $nodeModulesPath" -ForegroundColor Green
} else {
    Write-Host "❌ 未找到 node_modules" -ForegroundColor Red
    Write-Host ""
    Write-Host "请先运行: npm install 或 pnpm install" -ForegroundColor Yellow
    Write-Host "按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "安装 dsh-ui-web 插件" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "正在安装 @captain1275/dsh-ui-web 插件..." -ForegroundColor Yellow

# 安装插件
Set-Location "frontend"
try {
    npm install @captain1275/dsh-ui-web --save
    Write-Host "✅ 插件安装成功！" -ForegroundColor Green
} catch {
    Write-Host "❌ 插件安装失败: $_" -ForegroundColor Red
    Write-Host "按任意键退出..." -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

Set-Location $currentDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "安装完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步操作:" -ForegroundColor Yellow
Write-Host "1. 重启开发服务器（如果正在运行）" -ForegroundColor White
Write-Host "2. 打开浏览器访问 http://localhost:3000" -ForegroundColor White
Write-Host "3. 打开浏览器控制台 (F12)" -ForegroundColor White
Write-Host "4. 运行以下命令启用插件:" -ForegroundColor White
Write-Host ""
Write-Host "   window.__DSH_UI_WEB__ = require('@captain1275/dsh-ui-web');" -ForegroundColor Green
Write-Host ""
Write-Host "5. 刷新页面享受新功能！" -ForegroundColor White
Write-Host ""
Write-Host "按任意键退出..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
