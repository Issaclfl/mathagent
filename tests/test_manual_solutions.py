from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import main
from utils import manual_solutions as ms


def _make_checkpoint(tmp: Path, sub_problem_text: str) -> Path:
    data = {
        "problem_path": str(tmp / "problem.txt"),
        "problem_text": "测试物理题：外延层厚度测定。",
        "sub_problems": [sub_problem_text],
        "algorithms": {sub_problem_text: "回归分析"},
        "models": [
            {"status": "ok", "sub_problem": sub_problem_text, "algorithm": "回归分析",
             "math_model": "错误模型", "code": "print('LLM错误代码')",
             "error": None, "missing_deps": None},
        ],
        "executions": [],
        "review": {"status": "ok", "warnings": [], "review": "ok"},
    }
    cp = tmp / "checkpoint.json"
    cp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return cp


def _patch(msdir: Path):
    """将 manual_solutions 指向临时目录，并打桩写文件函数。"""
    orig = (
        ms.MANIFEST_PATH, ms.MANUAL_DIR,
        main._save_summary, main.record_from_summary,
        main.CHECKPOINT_FILE,
    )
    ms.MANIFEST_PATH = msdir / "manifest.json"
    ms.MANUAL_DIR = msdir
    # 断点隔离：求解后 main.py 会写固定路径 CHECKPOINT_FILE，
    # 必须改到临时目录，否则测试会覆盖用户真实的 data/results/pipeline_checkpoint.json
    main.CHECKPOINT_FILE = msdir / "checkpoint.json"

    def _fake_save(s, t):
        s["elapsed_seconds"] = round(time.time() - t, 1)
        return None

    main._save_summary = _fake_save
    main.record_from_summary = lambda s: None
    return orig


def _restore(orig):
    (
        ms.MANIFEST_PATH, ms.MANUAL_DIR,
        main._save_summary, main.record_from_summary,
        main.CHECKPOINT_FILE,
    ) = orig


def test_find_manual_matching():
    manifest = [
        {"sub_problem": "外延层厚度", "file": "a.py"},
        {"sub_problem": "预测销量", "file": "b.py"},
    ]
    # 精确
    assert ms.find_manual("外延层厚度", manifest)["file"] == "a.py"
    # 子串（子问题包含关键词，关键词 ≥4 字）
    assert ms.find_manual("计算碳化硅外延层厚度", manifest)["file"] == "a.py"
    # 模糊（中文相似度 ≥0.6）
    assert ms.find_manual("预测未来销量", manifest)["file"] == "b.py"
    # 无匹配
    assert ms.find_manual("完全无关的内容", manifest) is None
    # 空输入
    assert ms.find_manual("", manifest) is None
    print("[PASS] test_find_manual_matching")


def test_short_keyword_no_overmatch():
    """短关键词（<4 字，如"厚度"）不得子串匹配，防止多子问题被同一人工代码覆盖。"""
    manifest = [{"sub_problem": "厚度", "file": "a.py"}]
    # "厚度" 只有 2 字，不再子串匹配任何含"厚度"的子问题
    assert ms.find_manual("计算碳化硅外延层厚度", manifest) is None
    # difflib 兜底：与"厚度"相似度 0.6 以下也不匹配
    assert ms.find_manual("分析多光束干涉对厚度计算精度的影响", manifest) is None
    # 精确匹配仍生效
    assert ms.find_manual("厚度", manifest)["file"] == "a.py"
    print("[PASS] test_short_keyword_no_overmatch")


def test_load_manual_files():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "solve.py").write_text("print('x')", encoding="utf-8")
        (d / "m.md").write_text("数学推导", encoding="utf-8")
        msdir = d
        orig = (ms.MANUAL_DIR,)
        ms.MANUAL_DIR = msdir
        try:
            assert ms.load_manual_code({"file": "solve.py"}) == "print('x')"
            assert ms.load_manual_math({"math_model": "m.md"}) == "数学推导"
            # 缺失文件返回空串
            assert ms.load_manual_code({"file": "nope.py"}) == ""
            assert ms.load_manual_math({}) == ""
        finally:
            ms.MANUAL_DIR = orig[0]
    print("[PASS] test_load_manual_files")


def test_manual_override_executes_manual_code():
    """人工代码应替代 Builder 代码被执行，算法名被覆盖，结果进入 executions。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        msdir = tmp / "manual_solutions"
        msdir.mkdir()
        (msdir / "solve.py").write_text("print('厚度_um=10.47')", encoding="utf-8")
        manifest = [{"sub_problem": "外延层厚度", "file": "solve.py", "algorithm": "FFT干涉分析"}]
        (msdir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        orig = _patch(msdir)
        try:
            cp = _make_checkpoint(tmp, "计算碳化硅外延层厚度")
            summary = main.run_pipeline(
                str(tmp / "problem.txt"),
                skip_solve=False,
                skip_write=True,
                resume_from=str(cp),
                skip_hil=True,  # 测试走全自动模式（不触发策略门控/HIL 暂停）
            )
        finally:
            _restore(orig)
        assert len(summary["executions"]) == 1
        ex = summary["executions"][0]
        assert ex["status"] == "ok"
        assert ex["manual_solution"] == "solve.py"
        assert "10.47" in ex.get("output", "")
        assert summary["algorithms"]["计算碳化硅外延层厚度"] == "FFT干涉分析"
    print("[PASS] test_manual_override_executes_manual_code")


def test_no_manifest_uses_builder_code():
    """无 manifest 时正常执行 Builder 代码（不覆盖）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        msdir = tmp / "manual_solutions"
        msdir.mkdir()  # 无 manifest.json
        orig = _patch(msdir)
        try:
            cp = _make_checkpoint(tmp, "预测销量")
            summary = main.run_pipeline(
                str(tmp / "problem.txt"),
                skip_solve=False,
                skip_write=True,
                resume_from=str(cp),
                skip_hil=True,  # 测试走全自动模式（不触发策略门控/HIL 暂停）
            )
        finally:
            _restore(orig)
        assert len(summary["executions"]) == 1
        assert not summary["executions"][0].get("manual_solution")
        assert "LLM错误代码" in summary["executions"][0].get("output", "")
    print("[PASS] test_no_manifest_uses_builder_code")


if __name__ == "__main__":
    test_find_manual_matching()
    test_short_keyword_no_overmatch()
    test_load_manual_files()
    test_manual_override_executes_manual_code()
    test_no_manifest_uses_builder_code()
    print("\n所有测试通过！")
