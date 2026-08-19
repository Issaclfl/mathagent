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


print("== 真实拆题文本（2025A 实际拆解结果，定性量词）==")
# LLM 拆题不写数字："多枚"而非"3枚"（实测 2025A 全定性化）
real_subs = [
    "烟幕干扰弹运动与遮蔽效果模型",
    "无人机投放策略约束与运动模型",
    "单无人机投放单枚烟幕干扰弹的优化策略",
    "单无人机投放多枚烟幕干扰弹的优化策略",
    "多无人机协调投放烟幕干扰弹的优化策略",
]
sr = [analyze_problem_structure(sp) for sp in real_subs]
check("子问题3（单弹）维度 2-4 不误报高维",
      1 <= sr[2]["dim_estimate"] <= 4, f"dim={sr[2]['dim_estimate']}")
check("子问题4（多枚）检出高维", sr[3]["dim_estimate"] >= 6, f"dim={sr[3]['dim_estimate']}")
check("子问题4 检出组合结构", sr[3]["has_combination"])
check("子问题5（多机协调）检出高维", sr[4]["dim_estimate"] >= 6, f"dim={sr[4]['dim_estimate']}")
check("子问题5 检出组合结构", sr[4]["has_combination"])
check("子问题1/2（模型构建）不误报高维", sr[0]["dim_estimate"] < 6 and sr[1]["dim_estimate"] < 6,
      f"dims={sr[0]['dim_estimate']},{sr[1]['dim_estimate']}")

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
check("种子教训 6 条", len(SEED_LESSONS) == 6)

print("== 新增种子教训（计算失败类）==")
ls_judge = lessons_for("优化遮蔽判定函数，使遮蔽时长最长")
check("命中遮蔽判定教训", any("判定条件写反" in l for l in ls_judge), str(ls_judge))
ls_read = lessons_for("读取数据文件，FileNotFoundError 时使用默认值")
check("命中数据读取教训", any("静默" in l or "假数据" in l for l in ls_read), str(ls_read))
ls_empty = lessons_for("代码空跑，metrics.json 为空")
check("命中空跑教训", any("空跑" in l for l in ls_empty), str(ls_empty))

print("== _has_real_computation ==")
from agents.solver import _has_real_computation
check("循环代码有计算", _has_real_computation("for i in range(10): x += i"))
check("scipy代码有计算", _has_real_computation("from scipy.optimize import minimize\nminimize(f, x0)"))
check("函数+返回有计算", _has_real_computation("def f(x):\n    return x**2\nresult = f(3)"))
check("纯print无计算", not _has_real_computation("print('hello')\nprint('world')"))
check("纯赋值无计算", not _has_real_computation("x = 1\ny = 2\nprint(x + y)"))

print(f"\n结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败:", FAIL)
    sys.exit(1)
print("ALL TESTS PASSED")
