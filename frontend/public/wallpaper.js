/**
 * DeepSeek Harness 壁纸插件
 * 为 DSH 添加自定义壁纸功能
 */

// 默认壁纸配置
const defaultConfig = {
  light: '',
  dark: '',
  enabled: false
};

// 壁纸插件类
class WallpaperPlugin {
  constructor() {
    this.config = this.loadConfig();
    this.init();
  }

  loadConfig() {
    try {
      const saved = localStorage.getItem('dsh-wallpaper-config');
      return saved ? { ...defaultConfig, ...JSON.parse(saved) } : defaultConfig;
    } catch {
      return defaultConfig;
    }
  }

  saveConfig() {
    localStorage.setItem('dsh-wallpaper-config', JSON.stringify(this.config));
  }

  init() {
    if (this.config.enabled) {
      this.applyWallpaper();
    }
  }

  applyWallpaper() {
    const isDark = document.body.hasAttribute('data-ds-dark-theme');
    const url = isDark ? this.config.dark : this.config.light;

    if (url) {
      document.body.style.backgroundImage = `url("${url}")`;
      document.body.style.backgroundSize = 'cover';
      document.body.style.backgroundPosition = 'center';
      document.body.style.backgroundRepeat = 'no-repeat';
      document.body.classList.add('wallpaper-active');
    }
  }

  setWallpaper(lightUrl, darkUrl) {
    this.config.light = lightUrl || '';
    this.config.dark = darkUrl || lightUrl || '';
    this.config.enabled = !!(lightUrl || darkUrl);
    this.saveConfig();
    this.applyWallpaper();
  }

  removeWallpaper() {
    this.config = { ...defaultConfig };
    this.saveConfig();
    document.body.style.backgroundImage = '';
    document.body.classList.remove('wallpaper-active');
  }
}

// 创建全局实例
const wallpaperPlugin = new WallpaperPlugin();

// 暴露到全局
if (typeof window !== 'undefined') {
  window.__DSH_WALLPAPER__ = wallpaperPlugin;
}

// 监听主题变化
if (typeof MutationObserver !== 'undefined') {
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'attributes' && mutation.attributeName === 'data-ds-dark-theme') {
        wallpaperPlugin.applyWallpaper();
      }
    });
  });

  observer.observe(document.body, {
    attributes: true,
    attributeFilter: ['data-ds-dark-theme']
  });
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = wallpaperPlugin;
}
