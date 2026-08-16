"""策略门控（ask_gate）测试。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import ask_gate
from utils.ask_gate import (
    gate_enabled, gates_enabled, write_ask_file, load_ask_file,
    apply_answer, gate_answer_text, _gen_question,
)


def test_gate_enabled():
    """三个门控默认开启（config.hil.gates），可单独关闭。"""
    assert set(gates_enabled()) == {"modeling_strategy", "sensitivity_solver", "path_lock"}
    assert gate_enabled("modeling_strategy") is True
    assert gate_enabled("不存在") is False
    print("[PASS] test_gate_enabled")


def test_fallback_questions():
    """LLM 失败时各门控有兜底问题（优化题模板含 IRP/分步 vs 联合）。"""
    q1 = _gen_question("modeling_strategy", "优化决策", "ctx", llm=None)
    assert "联合" in q1 and ("方案A" in q1 or "方案" in q1)
    q2 = _gen_question("sensitivity_solver", "优化决策", "ctx", llm=None)
    assert "精确" in q2 and "启发式" in q2
    q3 = _gen_question("path_lock", "优化决策", "ctx", llm=None)
    assert "锁定" in q3
    # LLM 返回空 → 回退模板
    q = _gen_question("modeling_strategy", "物理推导", "ctx", llm=lambda p: "")
    assert len(q) > 20
    print("[PASS] test_fallback_questions")


def test_ask_file_roundtrip():
    """提问文件生成 → 人工填写 answer → 注入 summary，可被 gate_answer_text 读取。"""
    with tempfile.TemporaryDirectory() as td:
        orig = ask_gate.GATE_DIR
        ask_gate.GATE_DIR = Path(td)
        try:
            summary = {"problem_path": "C:/x/problem.txt"}
            path = write_ask_file(
                "modeling_strategy", "是否授权方案B？", "ctx",
                summary, options=["授权方案B", "采用方案A"],
            )
            ask = load_ask_file(path)
            assert ask["gate"] == "modeling_strategy"
            assert ask["question"] == "是否授权方案B？"
            # 未填 answer → 报错
            try:
                apply_answer(summary, ask)
                raise AssertionError("应抛 ValueError")
            except ValueError:
                pass
            # 填写后注入
            ask["answer"] = "授权方案B，删除分步TSP子问题"
            apply_answer(summary, ask)
            assert summary["gate_answers"]["modeling_strategy"] == "授权方案B，删除分步TSP子问题"
            assert summary.get("_gate_confirmed") is True
            txt = gate_answer_text(summary, "modeling_strategy")
            assert "人工策略决定" in txt and "授权方案B" in txt
            assert gate_answer_text(summary, "path_lock") == ""
        finally:
            ask_gate.GATE_DIR = orig
    print("[PASS] test_ask_file_roundtrip")


if __name__ == "__main__":
    test_gate_enabled()
    test_fallback_questions()
    test_ask_file_roundtrip()
    print("\n所有测试通过！")
