from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.verified_results import load_verified_results


def test_load_verified_results(tmp_dir: Path):
    """应加载文件名含'厚度计算结果'的csv，忽略无关csv。"""
    (tmp_dir / "厚度计算结果.csv").write_text(
        "附件,厚度_um\n附件1.xlsx,10.471\n", encoding="utf-8"
    )
    (tmp_dir / "无关数据.csv").write_text("a,1\n", encoding="utf-8")

    text = load_verified_results(tmp_dir)
    assert "厚度_um" in text
    assert "10.471" in text
    assert "无关数据" not in text
    print("[PASS] test_load_verified_results")


def test_no_verified_file(tmp_dir: Path):
    """无命中文件时返回空字符串。"""
    (tmp_dir / "普通.csv").write_text("a,1\n", encoding="utf-8")
    assert load_verified_results(tmp_dir) == ""
    print("[PASS] test_no_verified_file")


def test_missing_dir():
    """目录不存在时不抛异常。"""
    assert load_verified_results(Path(tempfile.gettempdir()) / "_不存在_xyz") == ""
    print("[PASS] test_missing_dir")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td1:
        test_load_verified_results(Path(td1))
    with tempfile.TemporaryDirectory() as td2:
        test_no_verified_file(Path(td2))
    test_missing_dir()
    print("\n所有测试通过！")
