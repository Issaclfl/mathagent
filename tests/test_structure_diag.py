# -*- coding: utf-8 -*-
"""结构诊断 + 经验教训机制验证（零 LLM 调用）"""
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
sys.path.insert(0, str(ROOT))

from utils.modeling_kb import analyze_problem_structure, structure_redline
from utils.experience import lessons_for, SEED_LESSONS

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f" | {detail}" if detail and not cond else ""))


print("== analyze_problem_structure ==")
# 2025A Q3：8 维三弹时序优化（网格搜索次优的实证场景）
s = analyze_problem_structure("针对M1，优化无人机FY1投放3枚烟幕干扰弹的时序策略，使总遮蔽时长最长")
check("Q3 检出组合结构", s["has_combination"], str(s))
check("Q3 检出可解析化", s["has_analytic"], str(s))
check("Q3 维度估计≥6", s["dim_estimate"] >= 6, f"dim={s['dim_estimate']}")

# 2025A Q5：多机多弹多目标
s5 = analyze_problem_structure("针对M1~M3三枚导弹，优化5架无人机的多弹投放策略，最大化总遮蔽覆盖")
check("Q5 检出组合结构", s5["has_combination"])
check("Q5 维度估计≥6", s5["dim_estimate"] >= 6, f"dim={s5['dim_estimate']}")

# 简单预测题：不应误报高维
s_p = analyze_problem_structure("基于历史数据预测各站点逐小时借还车需求量")
check("预测题不误报组合/高维", not s_p["has_combination"] and s_p["dim_estimate"] < 6, str(s_p))

# 边界风险
s_b = analyze_problem_structure("优化投放参数（起爆间隔至少1s、速度不超过140m/s）")
check("检出边界风险", s_b["has_boundary_risk"])

print("== structure_redline ==")
red = structure_redline(s)
check("红线包含禁止网格搜索", "网格搜索" in red and "差分进化" in red)
red5 = structure_redline(s5)
check("红线包含解耦建议", "解耦" in red5)
check("红线包含解析化建议", "解析" in red)

print("== lessons_for（种子教训）==")
ls = lessons_for("优化3枚烟幕干扰弹的投放时序策略，最大化遮蔽时长")
check("命中种子教训（多弹维度）", any("差分进化" in l for l in ls), str(ls))
ls2 = lessons_for("预测未来24小时各站点需求量")
check("预测题不误命中优化教训", len(ls2) == 0, str(ls2))

print("== SEED_LESSONS 完整性 ==")
check("种子教训 3 条", len(SEED_LESSONS) == 3)

print(f"\n结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败:", FAIL)
    sys.exit(1)
print("ALL TESTS PASSED")
