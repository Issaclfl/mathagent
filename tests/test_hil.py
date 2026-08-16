from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import hil
from utils.verification import STATUS_HUMAN, STATUS_METRICS, STATUS_UNVERIFIED


def _summary():
    return {
        "sub_problems": ["子问题A", "子问题B"],
        "executions": [
            {"status": "ok", "sub_problem": "子问题A",
             "metrics_json": {"RMSE": 0.1}, "verification_status": STATUS_METRICS},
            {"status": "ok", "sub_problem": "子问题B",
             "metrics_json": {"RMSE": 0.2}, "verification_status": STATUS_METRICS},
        ],
    }


def test_should_pause():
    orig = hil.hil_enabled
    hil.hil_enabled = lambda: False
    try:
        assert hil.should_pause(_summary()) is False
    finally:
        hil.hil_enabled = orig

    hil.hil_enabled = lambda: True
    try:
        assert hil.should_pause(_summary()) is True            # 无验证结果 → 暂停
        assert hil.should_pause({"executions": []}) is False    # 无执行记录 → 不暂停
        s = _summary(); s["_verified_results"] = "有验证结果"
        assert hil.should_pause(s) is False                     # 有真值 → 不暂停
    finally:
        hil.hil_enabled = orig
    print("[PASS] test_should_pause")


def test_write_and_apply_confirm():
    with tempfile.TemporaryDirectory() as td:
        orig = hil.HIL_DIR
        hil.HIL_DIR = Path(td)
        try:
            s = _summary()
            path = hil.write_pending(s, s["executions"], s["sub_problems"])
            p = hil.load_pending(path)
            assert len(p["items"]) == 2
            for it in p["items"]:
                it["decision"] = "confirm"
            out = hil.apply_decisions(_summary(), p)
            assert all(e["verification_status"] == STATUS_HUMAN for e in out["executions"])
        finally:
            hil.HIL_DIR = orig
    print("[PASS] test_write_and_apply_confirm")


def test_apply_edit():
    s = _summary()
    pending = {"items": [
        {"index": 1, "decision": "edit", "value": "42.5"},
        {"index": 2, "decision": "reject"},
    ]}
    out = hil.apply_decisions(s, pending)
    e1 = out["executions"][0]
    assert e1["metrics_json"] == {"人工验证值": 42.5}
    assert e1["verification_status"] == STATUS_HUMAN
    assert out["executions"][1]["verification_status"] == STATUS_UNVERIFIED
    assert "42.5" in out.get("_verified_results", "")
    print("[PASS] test_apply_edit")


def test_confirm_all_no_infinite_pause():
    """全 confirm 后 resume 不得再次暂停（修复无限暂停循环）。"""
    s = _summary()
    pending = {"items": [
        {"index": 1, "decision": "confirm"},
        {"index": 2, "decision": "confirm"},
    ]}
    out = hil.apply_decisions(s, pending)
    # 已确认标记：_verified_results 仍为空（confirm 不产生真值行）也不得再暂停
    assert out.get("_hil_confirmed") is True
    assert not out.get("_verified_results")
    orig = hil.hil_enabled
    hil.hil_enabled = lambda: True
    try:
        assert hil.should_pause(out) is False
    finally:
        hil.hil_enabled = orig
    print("[PASS] test_confirm_all_no_infinite_pause")


def test_pending_snapshot():
    """pending 文件记录 problem_path 与 sub_problems 快照（供 hil_resume 关联校验）。"""
    with tempfile.TemporaryDirectory() as td:
        orig = hil.HIL_DIR
        hil.HIL_DIR = Path(td)
        try:
            s = _summary()
            s["problem_path"] = "C:/赛题/problem.txt"
            path = hil.write_pending(s, s["executions"], s["sub_problems"])
            p = hil.load_pending(path)
            assert p["problem_path"] == "C:/赛题/problem.txt"
            assert p["sub_problems"] == ["子问题A", "子问题B"]
        finally:
            hil.HIL_DIR = orig
    print("[PASS] test_pending_snapshot")


def test_edit_value_parsable_by_data_auditor():
    """HIL edit 注入的人工行必须能被 DataAuditor 解析为参考真值。"""
    from utils.verification import parse_verified_refs
    s = _summary()
    pending = {"items": [{"index": 1, "decision": "edit", "value": "42.5"}]}
    out = hil.apply_decisions(s, pending)
    refs = parse_verified_refs(out.get("_verified_results", ""))
    assert refs and "42.5" in [str(v) for v in refs.values()]
    print("[PASS] test_edit_value_parsable_by_data_auditor")


def test_apply_errors():
    # 未填 decision → 报错
    try:
        hil.apply_decisions(_summary(), {"items": [{"index": 1, "decision": ""}]})
        raise AssertionError("应抛 ValueError")
    except ValueError:
        pass
    # edit 未填 value → 报错
    try:
        hil.apply_decisions(_summary(), {"items": [{"index": 1, "decision": "edit"}]})
        raise AssertionError("应抛 ValueError")
    except ValueError:
        pass
    # abort → RuntimeError
    try:
        hil.apply_decisions(_summary(), {"items": [{"index": 1, "decision": "abort"}]})
        raise AssertionError("应抛 RuntimeError")
    except RuntimeError:
        pass
    print("[PASS] test_apply_errors")


if __name__ == "__main__":
    test_should_pause()
    test_write_and_apply_confirm()
    test_apply_edit()
    test_confirm_all_no_infinite_pause()
    test_pending_snapshot()
    test_edit_value_parsable_by_data_auditor()
    test_apply_errors()
    print("\n所有测试通过！")
