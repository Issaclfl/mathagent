# 🎨 DeepSeek Harness 壁纸插件 - 完整总结

## 📋 已创建的文件

### 核心插件文件
1. **`frontend/public/wallpaper.js`** - 壁纸插件核心代码（JavaScript）
2. **`frontend/public/wallpaper-config.js`** - 配置示例文件

### 配置文件
3. **`frontend/src/app/layout.tsx`** - 已修改，自动加载插件脚本
4. **`frontend/src/app/globals.css`** - 已添加壁纸样式类

### 文档文件
5. **`WALLPAPER_README.md`** - 详细使用说明
6. **`wallpaper-plugin.md`** - 插件技术文档

### 安装脚本
7. **`SETUP_WALLPAPER.bat`** - Windows 批处理安装脚本
8. **`INSTALL_WALLPAPER.ps1`** - PowerShell 安装脚本

---

## 🚀 快速开始（3步完成）

### 第1步：保存你的图片
将你的动漫风景图保存到：
```
C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\frontend\public\wallpaper.jpg
```

### 第2步：重启开发服务器
```bash
cd frontend
npm run dev
# 或
pnpm dev
```

### 第3步：在浏览器控制台设置壁纸
打开 http://localhost:3000，按 F12 打开控制台，运行：
```javascript
window.__DSH_WALLPAPER__.setWallpaper('/wallpaper.jpg', '/wallpaper.jpg');
```

---

## 🎯 功能特性

| 功能 | 说明 |
|------|------|
| ✅ 自定义壁纸 | 支持任意图片 URL 或本地图片 |
| ✅ 主题适配 | 浅色/深色模式可使用不同壁纸 |
| ✅ 设置持久化 | 保存到 localStorage，刷新后保留 |
| ✅ 响应式设计 | 自适应不同屏幕尺寸 |
| ✅ 零依赖 | 纯 JavaScript，无额外依赖 |
| ✅ 自动加载 | 通过 Next.js 布局自动注入 |

---

## 📝 常用命令

```javascript
// 设置壁纸（浅色和深色模式使用同一张图）
window.__DSH_WALLPAPER__.setWallpaper('/wallpaper.jpg', '/wallpaper.jpg');

// 设置壁纸（浅色和深色模式使用不同图）
window.__DSH_WALLPAPER__.setWallpaper('/light.jpg', '/dark.jpg');

// 使用在线图片
window.__DSH_WALLPAPER__.setWallpaper('https://example.com/image.jpg');

// 移除壁纸
window.__DSH_WALLPAPER__.removeWallpaper();

// 查看当前配置
console.log(window.__DSH_WALLPAPER__.config);
```

---

## 🔧 技术实现

### 工作原理
1. **自动加载**：在 `layout.tsx` 中通过 `<script>` 标签加载 `wallpaper.js`
2. **主题监听**：使用 `MutationObserver` 监听 `data-ds-dark-theme` 属性变化
3. **设置存储**：使用 `localStorage` 保存用户配置
4. **样式应用**：通过 CSS 类 `.wallpaper-active` 控制背景样式

### 文件结构
```
frontend/
├── public/
│   ├── wallpaper.js          # 插件核心
│   └── wallpaper.jpg         # 你的壁纸图片（需要你保存）
├── src/
│   └── app/
│       ├── layout.tsx        # 已修改，加载插件
│       └── globals.css       # 已添加壁纸样式
```

---

## ❓ 常见问题

### Q: 图片不显示？
A: 检查：
1. 图片是否保存在 `frontend/public/wallpaper.jpg`
2. 文件名是否正确（区分大小写）
3. 浏览器控制台是否有错误

### Q: 刷新后壁纸消失？
A: 插件会自动保存设置到 localStorage，刷新后会自动应用。如果消失，请检查控制台是否有错误。

### Q: 如何更换壁纸？
A: 运行：
```javascript
window.__DSH_WALLPAPER__.setWallpaper('/new-wallpaper.jpg');
```

### Q: 如何恢复默认？
A: 运行：
```javascript
window.__DSH_WALLPAPER__.removeWallpaper();
```

---

## 🎨 图片建议

- **分辨率**：1920x1080 或更高
- **格式**：JPG、PNG、WebP
- **文件大小**：建议小于 5MB
- **深色模式**：建议使用较暗的图片以保证可读性

---

## 📞 技术支持

如有问题，请查看：
- `WALLPAPER_README.md` - 详细使用说明
- `wallpaper-plugin.md` - 技术文档
- 浏览器控制台日志

---

**创建者**: MiMo-v2.5  
**创建时间**: 2026年  
**版本**: 1.0