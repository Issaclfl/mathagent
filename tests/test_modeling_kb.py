"""建模知识库（题型分类/白名单）与 Typst 转换测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.modeling_kb import (
    classify_problem, algo_whitelist, kb_text, enforce_whitelist,
)
from utils.typst_export import md_to_typst


def test_classify_physics():
    """b2025 物理推导题必须判为物理推导（关键词：干涉/厚度/波长/折射）。"""
    p = ("红外干涉法是外延层厚度测量的无损伤测量方法……"
         "可根据红外光谱的波长、外延层的折射率和红外光的入射角等参数确定外延层的厚度。")
    assert classify_problem(p) == "物理推导"
    print("[PASS] test_classify_physics")


def test_classify_other_types():
    assert classify_problem("预测未来一周的共享单车需求量") == "数据预测"
    assert classify_problem("对10个候选方案进行综合评价并排序") == "综合评价"
    assert classify_problem("最小化运输总成本，设计配送路径") == "优化决策"
    assert classify_problem("判断设备是否存在故障") == "分类判别"
    assert classify_problem("") == "未知"
    print("[PASS] test_classify_other_types")


def test_physics_whitelist_excludes_classifiers():
    """物理题白名单不得含分类/聚类/评价类算法（b2025 实测 bug）。"""
    wl = algo_whitelist("物理推导")
    for banned in ("决策树", "支持向量机(SVM)", "随机森林", "聚类分析",
                   "层次分析法(AHP)", "TOPSIS", "神经网络"):
        assert banned not in wl, f"物理题白名单不应含 {banned}"
    # 白名单应含数值求解/拟合/优化类
    for needed in ("粒子群优化", "回归分析", "模拟退火", "遗传算法"):
        assert needed in wl, f"物理题白名单应含 {needed}"
    print("[PASS] test_physics_whitelist_excludes_classifiers")


def test_enforce_whitelist():
    """LLM 推荐出白名单的算法被确定性替换回白名单。"""
    wl = algo_whitelist("物理推导")
    pool = set(algo_whitelist("未知")) | {"粒子群优化"}
    # 决策树 → 白名单内最相近的（回归分析）
    assert enforce_whitelist("决策树", wl, pool) in wl
    # 白名单内的保持
    assert enforce_whitelist("粒子群优化", wl, pool) == "粒子群优化"
    # 别名
    assert enforce_whitelist("PSO", wl, pool, {"PSO": "粒子群优化"}) == "粒子群优化"
    print("[PASS] test_enforce_whitelist")


def test_kb_text_contains_hints():
    txt = kb_text("物理推导", algo_whitelist("物理推导"))
    assert "物理推导" in txt and "白名单" in txt
    assert "决策树" in txt  # 易错警示提到禁用的算法
    print("[PASS] test_kb_text_contains_hints")


def test_typst_headings_and_tables():
    md = (
        "# 标题\n\n"
        "## 摘要\n"
        "本文研究厚度。\n\n"
        "## 一、模型建立\n\n"
        "### 1.1 模型\n\n"
        "| 附件 | 厚度 |\n|---|---:|\n| 附件1 | 10.471 |\n"
    )
    typ = md_to_typst(md)
    assert "= 标题" in typ and "== 摘要" in typ and "== 一、模型建立" in typ
    assert "=== 1.1 模型" in typ
    assert "#figure(" in typ and "table(" in typ and "[*附件*]," in typ
    assert "[10.471]," in typ
    print("[PASS] test_typst_headings_and_tables")


def test_typst_formulas_and_lists():
    md = (
        "光程差为 $\\Delta = 2nd\\cos\\theta$。\n\n"
        "$$\n\\delta = 4\\pi d\\nu\n$$\n\n"
        "- 假设1\n- 假设2\n\n"
        "1. 步骤一\n2. 步骤二\n\n"
        "**重点**与*强调*\n\n---\n"
    )
    typ = md_to_typst(md)
    # LaTeX 命令已转 Typst 符号（Delta/cos/theta/delta/pi）
    assert "Delta" in typ and "cos" in typ and "theta" in typ
    assert "delta" in typ and "pi" in typ
    assert "- 假设1" in typ and "- 假设2" in typ         # 无序列表
    assert "+ 步骤一" in typ and "+ 步骤二" in typ       # 有序列表 → +
    assert "*重点*" in typ and "_强调_" in typ           # 加粗/斜体
    assert "#line(length: 100%)" in typ                 # 分隔线
    print("[PASS] test_typst_formulas_and_lists")


def test_typst_roundtrip_on_real_paper():
    """真实论文 Markdown 转换不抛异常且保留标题结构。"""
    results = Path(__file__).parent.parent / "data" / "results"
    papers = sorted(results.glob("paper_*.md"))
    if not papers:
        print("[SKIP] test_typst_roundtrip_on_real_paper（无论文文件）")
        return
    md = papers[-1].read_text(encoding="utf-8")
    typ = md_to_typst(md)
    assert typ and "== " in typ
    # 代码块闭合保持
    assert typ.count("```") % 2 == 0 or "```" not in typ
    print(f"[PASS] test_typst_roundtrip_on_real_paper（{papers[-1].name} → {len(typ)} 字符）")


if __name__ == "__main__":
    test_classify_physics()
    test_classify_other_types()
    test_physics_whitelist_excludes_classifiers()
    test_enforce_whitelist()
    test_kb_text_contains_hints()
    test_typst_headings_and_tables()
    test_typst_formulas_and_lists()
    test_typst_roundtrip_on_real_paper()
    print("\n所有测试通过！")
