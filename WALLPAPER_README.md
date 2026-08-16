# DeepSeek Harness 壁纸插件

我已经为你创建了一个简单的壁纸插件！🎉

## 📁 创建的文件

1. **`frontend/public/wallpaper.js`** - 壁纸插件核心代码
2. **`frontend/src/app/layout.tsx`** - 已修改，自动加载插件
3. **`frontend/src/app/globals.css`** - 已添加壁纸样式
4. **`wallpaper-plugin.md`** - 详细使用说明

## 🚀 快速开始

### 方法 1: 使用你的图片（推荐）

由于你的图片还没有保存到本地，请先：

1. **保存图片**：右键点击你的动漫风景图 → "另存为" → 保存到 `frontend/public/` 目录，命名为 `wallpaper.jpg`

2. **在浏览器控制台运行**：
```javascript
// 设置壁纸
window.__DSH_WALLPAPER__.setWallpaper('/wallpaper.jpg', '/wallpaper.jpg');
```

### 方法 2: 使用在线图片

在浏览器控制台运行：
```javascript
// 使用在线图片 URL
window.__DSH_WALLPAPER__.setWallpaper('https://example.com/your-image.jpg');
```

## ⚙️ 功能特性

- ✅ 支持浅色/深色模式不同壁纸
- ✅ 响应式设计，自适应屏幕
- ✅ 设置保存到 localStorage
- ✅ 监听主题变化自动切换
- ✅ 零依赖，纯 JavaScript

## 🎨 使用命令

```javascript
// 设置壁纸
window.__DSH_WALLPAPER__.setWallpaper('浅色壁纸URL', '深色壁纸URL');

// 移除壁纸
window.__DSH_WALLPAPER__.removeWallpaper();

// 查看当前配置
console.log(window.__DSH_WALLPAPER__.config);
```

## 📝 注意事项

- 壁纸图片建议使用 1920x1080 或更高分辨率
- 过大的图片可能影响性能
- 深色模式下建议使用较暗的壁纸以保证可读性
- 插件会自动保存你的设置

## 🎯 下一步

1. 保存你的动漫风景图到 `frontend/public/wallpaper.jpg`
2. 重启开发服务器（如果正在运行）
3. 在浏览器控制台运行设置命令
4. 享受你的新壁纸！

---

由 MiMo-v2.5 创建 ❤️