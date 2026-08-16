"""人工求解注入：物理推导题由人工写核心求解代码，系统只负责执行与论文。

用法：
1. 在 data/manual_solutions/ 下放置人工求解脚本（.py）与可选数学模型说明（.md）
2. 在 data/manual_solutions/manifest.json 登记：
   [
     {"sub_problem": "子问题关键词/原文", "file": "solve_b2025.py",
      "algorithm": "FFT干涉分析", "math_model": "model_b2025.md"}
   ]
3. 流水线（main.py）会对匹配的子问题用人工代码替代 Builder 生成的代码，
   并只执行一次（不做 LLM 自动修复，人工代码视为可信）。
"""
from __future__ import annotations

import difflib
import json
from pathlib import Path

MANUAL_DIR = Path(__file__).resolve().parent.parent / "data" / "manual_solutions"
MANIFEST_PATH = MANUAL_DIR / "manifest.json"


def load_manifest(manifest_path: str | Path | None = None) -> list[dict]:
    """加载人工求解登记表；无 manifest 或解析失败时返回空列表。"""
    p = Path(manifest_path) if manifest_path else MANIFEST_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def find_manual(sub_problem: str, manifest: list[dict] | None = None) -> dict | None:
    """按子问题文本匹配人工求解条目。

    匹配顺序：精确 → 子串（关键词至少 4 字，取最长命中）→ difflib 模糊（阈值 0.6）。
    短关键词（如"厚度"）会过度匹配任意含该词的子问题，导致多子问题被同一
    人工代码覆盖，故子串匹配要求关键词长度 ≥ 4。无命中返回 None。
    """
    if manifest is None:
        manifest = load_manifest()
    if not sub_problem or not manifest:
        return None

    best, best_score = None, 0.0
    for entry in manifest:
        key = str(entry.get("sub_problem", "")).strip()
        if not key:
            continue
        if sub_problem == key:
            return entry
        if len(key) >= 4 and (key in sub_problem or sub_problem in key):
            # 子串命中：越长越精确
            if len(key) > best_score:
                best, best_score = entry, len(key)
            continue
        score = difflib.SequenceMatcher(None, sub_problem, key).ratio()
        if score > best_score:
            best, best_score = entry, score
    if best is not None and best_score >= 0.6:
        return best
    return None


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else MANUAL_DIR / p


def load_manual_code(entry: dict) -> str:
    """加载人工求解代码；文件缺失返回空字符串。"""
    f = entry.get("file", "")
    if not f:
        return ""
    p = _resolve(str(f))
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_manual_math(entry: dict) -> str:
    """加载人工求解的数学模型说明（可选）；无或缺失返回空字符串。"""
    f = entry.get("math_model", "")
    if not f:
        return ""
    p = _resolve(str(f))
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    manifest = load_manifest()
    print(f"manifest 条目: {len(manifest)}")
    for e in manifest:
        print(f"  - {e.get('sub_problem')} -> {e.get('file')}")
