from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.audit import QualityGateAgent, LogicAuditor, DataAuditor, FormatAuditor
from utils.verification import STATUS_METRICS, STATUS_UNVERIFIED

GOOD_PAPER = """# 测试论文

## 摘要
本文建立回归模型，采用最小二乘求解，RMSE=15.2，R²=0.93，给出 95% 置信区间。

## 一、问题重述
根据赛题要求，建立租用量预测模型。

## 二、模型假设
假设数据满足线性关系，误差独立同分布。

## 三、模型建立
建立多元线性回归模型，定义变量与目标函数。

## 四、求解过程与算法
采用最小二乘算法拟合，回归系数见式(4.1)。

## 五、结果分析
测试集 RMSE=15.2，R²=0.93，F 检验 p<0.05，不确定度 ±0.3。

## 六、结论
模型有效，推广至其他城市，灵敏度分析表明参数稳健。
"""

BAD_PAPER = "本文研究药物浓度衰减，采用回归分析。结束。"


def _summary_with_verified():
    return {"_verified_results": "RMSE=15.2", "sub_problems": ["A"], "executions": []}


def test_determinism():
    """同一论文多次审核，分数完全一致（确定性）。"""
    gate = QualityGateAgent()
    r1 = gate.run(GOOD_PAPER, _summary_with_verified())
    r2 = gate.run(GOOD_PAPER, _summary_with_verified())
    assert r1["scores"] == r2["scores"]
    assert r1["overall"] == r2["overall"]
    print("[PASS] test_determinism")


def test_logic_checklist():
    """完整论文通过逻辑清单，空泛论文扣分。"""
    good = LogicAuditor().run(GOOD_PAPER, {})
    bad = LogicAuditor().run(BAD_PAPER, {})
    assert good["score"] >= 9.0, f"完整论文逻辑分应≈10，实际 {good['score']}"
    assert bad["score"] < 8.0, f"空泛论文逻辑分应<8，实际 {bad['score']}"
    print("[PASS] test_logic_checklist")


def test_data_audit_reference_match():
    """论文含参考真值→通过；含偏差值→标注异常。"""
    da = DataAuditor()
    ok = da.run(GOOD_PAPER, _summary_with_verified())
    assert ok["score"] is not None and ok["score"] >= 9.0
    # 论文数值偏离真值（RMSE 15.2 但论文写 18.0，偏差 18%）→ 疑似矛盾
    wrong_paper = GOOD_PAPER.replace("15.2", "18.0")
    bad = da.run(wrong_paper, _summary_with_verified())
    assert any("RMSE" in i["problem"] for i in bad["issues"])
    # 无参考值 → 跳过
    skipped = da.run(GOOD_PAPER, {"sub_problems": [], "executions": []})
    assert skipped.get("skipped") is True
    print("[PASS] test_data_audit_reference_match")


def test_format_rule_engine():
    """规范论文通过格式检查，缺参考文献的论文被标注。"""
    fa = FormatAuditor()
    good = fa.run(GOOD_PAPER, {})
    no_ref = fa.run(GOOD_PAPER.replace("参考文献", "结语").replace("[1] 张宇. 红外干涉测量. 中国激光, 2008.", ""), {})
    assert good["score"] is not None
    assert any("参考文献" in i["problem"] for i in no_ref["issues"])
    print("[PASS] test_format_rule_engine")


def test_gate_interface():
    """总审输出兼容流水线所需字段。"""
    gate = QualityGateAgent()
    r = gate.run(GOOD_PAPER, _summary_with_verified())
    for k in ("passed", "scores", "overall", "feedback", "feedback_by_section", "details"):
        assert k in r, f"缺少字段 {k}"
    assert set(r["scores"]) == {"logic", "data", "format"}
    print("[PASS] test_gate_interface")


def test_extract_refs_hil_line():
    """HIL edit 人工行（生产格式）必须被解析为参考真值。"""
    da = DataAuditor()
    summary = {"_verified_results": "子问题1: 42.5", "executions": []}
    refs = da._extract_refs(summary)
    assert refs.get("子问题1") == 42.5
    print("[PASS] test_extract_refs_hil_line")


def test_extract_refs_csv_table():
    """验证 CSV 表格文本（load_verified_results 输出）必须被解析为参考真值。"""
    da = DataAuditor()
    table = (
        "厚度计算结果:\n"
        "      附件  材料  折射率 入射角  厚度_um\n"
        "附件1.xlsx SiC 3.40 10° 10.471\n"
        "附件4.xlsx  Si 3.44 15°  7.645"
    )
    summary = {"_verified_results": table, "executions": []}
    refs = da._extract_refs(summary)
    assert refs.get("厚度计算结果.附件1.xlsx.厚度_um") == 10.471
    assert refs.get("厚度计算结果.附件4.xlsx.折射率") == 3.44
    print("[PASS] test_extract_refs_csv_table")


def test_extract_refs_only_human_verified():
    """无人工/独立验证结果时 refs 为空（代码输出不再作为审核参考）。

    设计意图：verified_metrics 只是状态标记，不是审核参考——多子问题各自
    给出不同最优解（合法多解）时，拿代码输出当参考会导致审核标准不可达。
    """
    da = DataAuditor()
    summary = {
        "_verified_results": "",
        "executions": [
            {"status": "ok", "metrics_json": {"厚度": 4.72},
             "verification_status": STATUS_UNVERIFIED},
            {"status": "ok", "metrics_json": {"RMSE": 0.1},
             "verification_status": STATUS_METRICS},
        ],
    }
    assert da._extract_refs(summary) == {}
    # 有人工真值时才解析
    summary["_verified_results"] = "厚度=7.581"
    assert da._extract_refs(summary) == {"厚度": 7.581}
    print("[PASS] test_extract_refs_only_human_verified")


def test_internal_consistency_conflict():
    """论文内部同一指标键出现多个不同值 → 矛盾（不依赖真值）。

    共享单车题实测：5.3 节总距离 46.693 与 5.4 节 51.15 并存必须被拦截。
    """
    da = DataAuditor()
    paper = (
        "## 摘要\n总行驶距离51.15 km，未满足需求为0辆。\n\n"
        "## 模型建立与求解\n"
        "| 指标 | 数值 |\n|---|---|\n| 总行驶距离 | 46.693 |\n"
        "| 未满足需求量 | 0 |\n\n"
        "### 5.3 路径优化\n总行驶距离为 46.693 公里。\n\n"
        "### 5.4 联合优化\n总行驶距离为 51.15 公里。"
    )
    r = da.run(paper, {"_verified_results": ""})
    assert any("总行驶距离" in i["problem"] for i in r["issues"])
    print("[PASS] test_internal_consistency_conflict")


def test_internal_consistency_same_list_no_conflict():
    """同一列表重复出现（摘要/结论各抄一遍）不算矛盾。"""
    da = DataAuditor()
    paper = (
        "## 摘要\n各站点最终车辆数为[20,7,22,17,17,22,8,26]。\n\n"
        "## 结论\n各站点最终车辆数为 [20,7,22,17,17,22,8,26]。\n"
        "总行驶距离 51.15 km，总行驶距离为51.15。"
    )
    r = da.run(paper, {"_verified_results": ""})
    # 相同列表重复出现不报；同键同值也不报 → 跳过
    assert r.get("skipped") is True
    print("[PASS] test_internal_consistency_same_list_no_conflict")


def test_big_deviation_triggers_contradiction():
    """偏差 >20% 的大错误也必须被标记（旧逻辑只查 2%~20% 窗口，大错误无声放行）。"""
    da = DataAuditor()
    summary = {"_verified_results": "厚度=10.471", "executions": []}
    # 论文写 4.72（偏差 55%）→ 必须报矛盾
    paper = "## 摘要\n厚度为 4.72 μm。\n\n## 模型建立与求解\n计算得厚度 4.72。"
    r = da.run(paper, summary)
    assert any("厚度" in i["problem"] for i in r["issues"])
    # 论文写 100（偏差 10 倍）→ 同数量级窗口内也须报矛盾
    paper2 = "## 摘要\n厚度为 100 μm。\n\n## 模型建立与求解\n计算得厚度 100。"
    r2 = da.run(paper2, summary)
    assert any("厚度" in i["problem"] for i in r2["issues"])
    print("[PASS] test_big_deviation_triggers_contradiction")


def test_refs_and_formula_numbers_do_not_fake_found():
    """公式编号 (4.1) 不得伪造"命中"（噪声过滤）。

    若不过滤，真值恰为 4.1 时公式编号 (4.1) 会被当成论文引用 → 假通过。
    """
    da = DataAuditor()
    summary = {"_verified_results": "系数=4.1", "executions": []}
    # 论文正文只有公式编号 (4.1)，没有任何真实求解数值
    paper = (
        "## 摘要\n本文研究参数拟合。\n\n"
        "## 模型建立与求解\n回归系数见式(4.1)。\n\n"
        "## 参考文献\n[1] 作者. 论文. 2018."
    )
    r = da.run(paper, summary)
    assert any("脱节" in i["problem"] for i in r["issues"])
    print("[PASS] test_refs_and_formula_numbers_do_not_fake_found")


def test_negative_error_not_hidden_by_truth():
    """论文已引用真值时，负值错误（-64.53 vs 7.581）仍必须被标记。

    本次 b2025 实测暴露：论文同时抄了真值（found）后，正值错误被掩护；
    但物理量符号错误（负厚度）是硬伤，即使真值在论文中也要报。
    """
    da = DataAuditor()
    summary = {"_verified_results": "厚度计算结果.附件3.xlsx.厚度_um=7.581", "executions": []}
    paper = (
        "## 摘要\n厚度为 7.581 μm。\n\n"
        "## 模型建立与求解\nFFT基频: -0.044080 cm\n最优厚度: -64.5276 μm"
    )
    r = da.run(paper, summary)
    assert any("负值" in i["problem"] for i in r["issues"])
    print("[PASS] test_negative_error_not_hidden_by_truth")


if __name__ == "__main__":
    test_determinism()
    test_logic_checklist()
    test_data_audit_reference_match()
    test_format_rule_engine()
    test_gate_interface()
    test_extract_refs_hil_line()
    test_extract_refs_csv_table()
    test_extract_refs_only_human_verified()
    test_big_deviation_triggers_contradiction()
    test_refs_and_formula_numbers_do_not_fake_found()
    test_negative_error_not_hidden_by_truth()
    test_internal_consistency_conflict()
    test_internal_consistency_same_list_no_conflict()
    print("\n所有测试通过！")
