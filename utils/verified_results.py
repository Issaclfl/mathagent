"""已验证结果加载：扫描 data 下的独立验证 CSV，供数据审核比对。

约定：文件名含 '验证' 或 '厚度计算结果' 的 csv，作为人工/独立验证的真实结果，
其优先级高于 Builder 自动生成的执行记录（数据审核以此为准）。
"""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 文件名需包含的关键词之一才视为已验证结果
_VERIFIED_KEYWORDS = ("验证", "厚度计算结果")


def load_verified_results(data_dir: str | Path | None = None) -> str:
    """扫描数据目录下的已验证结果文件，返回格式化文本。

    Args:
        data_dir: 当前赛题的数据目录。**必须传**——全局扫描会把别的赛题的
            验证真值（如 b2025 的厚度计算结果.csv）注入当前赛题的论文审核，
            造成"折射率=3.4 vs 论文最近值 3"（站点编号被误判）一类跨赛题误报。
            为兼容旧调用，缺省时回退全局扫描（仅测试/脚本使用）。

    Returns:
        所有命中文件的表格文本拼接；无命中时返回空字符串。
    """
    import pandas as pd

    base = Path(data_dir) if data_dir else DATA_DIR
    if not base.exists():
        return ""
    # 只扫数据目录顶层（约定：验证文件与赛题附件同目录存放）。
    # 不递归——递归会把其它赛题子目录的验证文件扫进来造成跨赛题污染。
    candidates = sorted(base.glob("*.csv"))
    if data_dir is None:
        # 旧行为：顶层 + b2025 子目录（保持兼容）
        candidates = sorted(base.glob("*.csv")) + sorted(base.glob("b2025/*.csv"))

    hits = []
    for f in candidates:
        if not any(kw in f.stem for kw in _VERIFIED_KEYWORDS):
            continue
        try:
            df = pd.read_csv(f, encoding="utf-8")
        except Exception:
            try:
                df = pd.read_csv(f, encoding="utf-8-sig")
            except Exception:
                continue
        hits.append(f"{f.stem}:\n{df.to_string(index=False)}")
    return "\n\n".join(hits)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    text = load_verified_results()
    print(text if text else "（未找到已验证结果文件）")
