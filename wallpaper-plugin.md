# DeepSeek Harness 壁纸插件

这是一个简单的客户端插件，可以为 DSH 添加自定义壁纸功能。

## 功能

- 支持自定义背景图片
- 支持浅色/深色模式不同的壁纸
- 可通过设置页面配置壁纸 URL
- 响应式设计，自适应不同屏幕尺寸

## 安装方法

### 方法 1: 直接修改 CSS（推荐）

在 `frontend/src/app/globals.css` 文件末尾添加：

```css
/* 壁纸插件样式 */
body.wallpaper-active {
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  background-attachment: fixed;
}

[data-ds-dark-theme] body.wallpaper-active {
  /* 深色模式壁纸（可选） */
}
```

### 方法 2: 通过控制台注入

在浏览器控制台中运行：

```javascript
// 设置壁纸
document.body.style.backgroundImage = 'url("你的图片URL")';
document.body.style.backgroundSize = 'cover';
document.body.style.backgroundPosition = 'center';
document.body.style.backgroundRepeat = 'no-repeat';
document.body.classList.add('wallpaper-active');
```

## 配置

在 DSH 的设置 → 插件配置中可以添加以下设置项：

```yaml
wallpaper:
  light: "浅色模式壁纸 URL"
  dark: "深色模式壁纸 URL"
  enabled: true
```

## 示例

### 使用在线图片

```javascript
// 在控制台执行
document.body.style.backgroundImage = 'url("https://example.com/wallpaper.jpg")';
document.body.style.backgroundSize = 'cover';
```

### 使用本地图片

1. 将图片放到 `frontend/public/` 目录
2. 使用相对路径：`/your-image.jpg`

## 注意事项

- 壁纸图片建议使用 1920x1080 或更高分辨率
- 过大的图片可能影响性能
- 深色模式下建议使用较暗的壁纸以保证可读性

## 创建者

由 MiMo-v2.5 创建