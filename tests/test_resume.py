from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import main


def _make_checkpoint(tmp: Path) -> Path:
    data = {
        "problem_path": str(tmp / "problem.txt"),
        "problem_text": "测试赛题：预测某指标。",
        "sub_problems": ["子问题1", "子问题2"],
        "algorithms": {"子问题1": "回归分析", "子问题2": "聚类分析"},
        "models": [
            {"status": "ok", "sub_problem": "子问题1", "algorithm": "回归分析",
             "math_model": "y=ax+b", "code": "print('ok')", "error": None, "missing_deps": None},
            {"status": "ok", "sub_problem": "子问题2", "algorithm": "聚类分析",
             "math_model": "kmeans", "code": "print('ok2')", "error": None, "missing_deps": None},
        ],
        "executions": [
            {"sub_problem": "子问题1", "status": "ok", "output": "done", "metrics": {}, "attempts": 1},
            {"sub_problem": "子问题2", "status": "ok", "output": "done", "metrics": {}, "attempts": 1},
        ],
        "review": {"status": "ok", "warnings": [], "review": "全部成功"},
    }
    cp = tmp / "checkpoint.json"
    cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return cp


def test_resume_from_file():
    """应完整恢复各阶段数据（含 review，不丢键）。"""
    with tempfile.TemporaryDirectory() as td:
        cp = _make_checkpoint(Path(td))
        base = {"problem_path": "default.txt", "problem_text": "", "sub_problems": [],
                "algorithms": {}, "models": [], "executions": []}
        ok = main._resume_from_file(str(cp), base)
        assert ok
        assert base["sub_problems"] == ["子问题1", "子问题2"]
        assert base["algorithms"]["子问题1"] == "回归分析"
        assert base["review"]["review"] == "全部成功"
    print("[PASS] test_resume_from_file")


def test_resume_invalid_file():
    """无效断点应返回 False，不抛异常。"""
    base = {"sub_problems": []}
    assert main._resume_from_file("C:/不存在/文件.json", base) is False
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert main._resume_from_file(str(bad), base) is False
    print("[PASS] test_resume_invalid_file")


def test_save_checkpoint_roundtrip():
    """检查点 JSON 往返，保留审计循环状态。"""
    with tempfile.TemporaryDirectory() as td:
        orig = main.CHECKPOINT_FILE
        main.CHECKPOINT_FILE = Path(td) / "cp.json"
        try:
            summary = {"sub_problems": ["a"],
                       "_checkpoint": {"round": 2, "feedback": "改摘要"}}
            main._save_checkpoint(summary, time.time())
            loaded = json.loads(main.CHECKPOINT_FILE.read_text(encoding="utf-8"))
            assert loaded["_checkpoint"]["round"] == 2
            assert loaded["_checkpoint"]["feedback"] == "改摘要"
        finally:
            main.CHECKPOINT_FILE = orig
    print("[PASS] test_save_checkpoint_roundtrip")


def test_run_pipeline_resume_skips_stages():
    """resume 时应跳过已完成的阶段（无 LLM 调用）。"""
    with tempfile.TemporaryDirectory() as td:
        cp = _make_checkpoint(Path(td))
        orig_save, orig_record = main._save_summary, main.record_from_summary

        def _fake_save(s, t):
            s["elapsed_seconds"] = round(time.time() - t, 1)
            return None

        main._save_summary = _fake_save
        main.record_from_summary = lambda s: None
        try:
            summary = main.run_pipeline(
                str(Path(td) / "problem.txt"),
                skip_solve=True,
                skip_write=True,
                resume_from=str(cp),
            )
        finally:
            main._save_summary, main.record_from_summary = orig_save, orig_record
        assert summary["sub_problems"] == ["子问题1", "子问题2"]
        assert len(summary["executions"]) == 2
        assert summary["review"]["status"] == "ok"
    print("[PASS] test_run_pipeline_resume_skips_stages")


if __name__ == "__main__":
    test_resume_from_file()
    test_resume_invalid_file()
    test_save_checkpoint_roundtrip()
    test_run_pipeline_resume_skips_stages()
    print("\n所有测试通过！")
