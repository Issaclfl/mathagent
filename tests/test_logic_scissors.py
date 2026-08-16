from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.reviewer import ReviewerAgent

scissors = ReviewerAgent._check_logic_scissors


def test_detect_contradiction():
    """因果断裂应被捕获：辐照误差降 + 最终功率预测误差升（相对基线恶化）。"""
    execs = [{
        "sub_problem": "对NWP做空间降尺度并评估对功率预测的影响",
        "status": "ok",
        "metrics_json": {
            "降尺度辐照误差": 0.03,
            "功率预测E_rmse": 0.12,
            "粗网格预测E_rmse": 0.08,
        },
        "metrics": {"numbers": {}},
    }]
    v = scissors(execs)
    assert len(v) == 1, f"应检测到 1 条逻辑剪刀，实际 {len(v)}"
    assert "逻辑剪刀" in v[0]["reason"]
    print("[PASS] test_detect_contradiction")


def test_no_trigger_when_consistent():
    """两指标同向（都改善/都恶化）不应触发。"""
    assert scissors([{"sub_problem": "A", "status": "ok",
                      "metrics_json": {"误差A": 0.03, "误差B": 0.02}}]) == []
    assert scissors([{"sub_problem": "A", "status": "ok",
                      "metrics_json": {"粗网格误差": 0.03, "功率预测误差": 0.02}}]) == []
    print("[PASS] test_no_trigger_when_consistent")


def test_no_metrics_no_trigger():
    """无指标 / 非误差类指标不应触发。"""
    assert scissors([{"sub_problem": "A", "status": "ok", "metrics_json": {}}]) == []
    assert scissors([{"sub_problem": "A", "status": "ok",
                      "metrics_json": {"得分": 0.9}}]) == []
    print("[PASS] test_no_metrics_no_trigger")


def test_fallback_without_baseline():
    """无基线指标时，最终误差远差于中间误差也应触发。"""
    v = scissors([{"sub_problem": "B", "status": "ok",
                   "metrics_json": {"降尺度辐照误差": 0.03, "功率预测E_rmse": 0.12}}])
    assert len(v) == 1, "无基线时最终>>中间应触发"
    print("[PASS] test_fallback_without_baseline")


if __name__ == "__main__":
    test_detect_contradiction()
    test_no_trigger_when_consistent()
    test_no_metrics_no_trigger()
    test_fallback_without_baseline()
    print("\n所有测试通过！")
