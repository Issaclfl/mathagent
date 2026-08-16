from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_config: dict | None = None


def load_config(path: Path | None = None) -> dict:
    """加载配置文件，支持缓存。"""
    global _config
    if _config is not None and path is None:
        return _config

    path = path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)

    return _config


def get(key: str, default=None):
    """获取配置项，支持点号分隔的嵌套键。"""
    config = load_config()
    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
        if value is None:
            return default
    return value
