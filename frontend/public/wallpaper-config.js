/**
 * 壁纸配置示例
 * 将此文件中的配置复制到浏览器控制台执行
 */

// 示例 1: 使用你的动漫风景图
// 假设图片保存为 frontend/public/wallpaper.jpg
const config1 = {
  light: '/wallpaper.jpg',
  dark: '/wallpaper.jpg'
};

// 示例 2: 使用在线图片
const config2 = {
  light: 'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1920',
  dark: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?w=1920'
};

// 示例 3: 浅色和深色模式使用不同图片
const config3 = {
  light: 'https://example.com/light-wallpaper.jpg',
  dark: 'https://example.com/dark-wallpaper.jpg'
};

// 在浏览器控制台中执行以下代码来设置壁纸：
console.log(`
🎨 壁纸设置方法：

1. 保存你的图片到 frontend/public/wallpaper.jpg

2. 在浏览器控制台运行：
   window.__DSH_WALLPAPER__.setWallpaper('/wallpaper.jpg', '/wallpaper.jpg');

3. 或者使用在线图片：
   window.__DSH_WALLPAPER__.setWallpaper('图片URL');

4. 移除壁纸：
   window.__DSH_WALLPAPER__.removeWallpaper();
`);
