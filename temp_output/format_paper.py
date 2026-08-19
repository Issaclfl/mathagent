# -*- coding: utf-8 -*-
"""A 题论文格式处理：
1. 摘要重写为"每问一段"结构（真实数据，手动构造保证数值准确）
2. 正文段落首行缩进两个全角空格（中文论文格式规范）
"""
from pathlib import Path

SRC = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\results\paper_20260817_150809.md")

NEW_ABSTRACT = """## 摘要

本文针对无人机投放烟幕干扰弹干扰来袭空地导弹、保护真实目标的策略优化问题，建立了基于运动学仿真的多阶段优化模型体系：以导弹—烟幕云团视线遮蔽判定为核心评估函数，从单弹仿真、单弹优化到多弹协同、多机协同、多机多弹多目标逐步递进求解，并完成灵敏度分析与鲁棒性验证。

针对问题1（固定策略遮蔽时长计算），建立了导弹匀速直线飞行、无人机等高匀速飞行、干扰弹重力弹道与烟幕云团匀速下沉的运动学仿真模型，以真目标下底面圆心为遮蔽判定参考点，离散采样判定视线与烟幕球相交关系，求得给定投放策略（v=120 m/s、t_d=1.5 s、τ=3.6 s）下对M1的有效遮蔽时长为1.41 s（遮蔽区间[8.04, 9.45] s），为后续优化提供基准评估模型。

针对问题2（单机单弹优化），以有效遮蔽时长最大化为目标，将无人机航向角θ、飞行速度v、投放时刻t_d、起爆间隔τ作为决策变量，采用多级网格细化搜索求解。优化后有效遮蔽时长提升至4.76 s（θ=9°、v=76 m/s、t_d=0、τ=1.0 s），较问题1提升约3.4倍，验证了参数优化对遮蔽效果的关键作用。

针对问题3（单机三弹时序协同），在无人机航向与速度固定的前提下，优化3枚烟幕干扰弹的投放时刻与起爆间隔，并考虑相邻投放间隔不小于1 s的约束。优化得到三弹投放时刻0/2/4 s、起爆间隔3/4/5 s的策略，各弹遮蔽区间首尾衔接，累计有效遮蔽时长5.30 s，连续遮蔽区间为[5.74, 11.04] s。

针对问题4（三机各一弹协同），将FY1、FY2、FY3三架无人机的飞行参数与投放时序联合优化（12维决策空间），采用分层搜索与多起点局部优化求解。优化后三枚弹的遮蔽区间在时间轴上接力衔接，对M1的总有效遮蔽时长达8.80 s，较单机三弹方案进一步提升66%。

针对问题5（多机多弹多目标），面向M1、M2、M3三枚导弹与5架无人机的组合优化问题，采用分层贪心策略：先逐导弹单弹优化保证覆盖，再以并集增量补充。最终实现三枚导弹总有效遮蔽时长26.62 s（M1: 19.54 s、M2: 4.34 s、M3: 2.74 s），验证了多机协同在应对多目标威胁时的显著优势。

灵敏度分析表明，起爆间隔τ与飞行速度v在±20%范围内扰动时，总遮蔽时长波动不超过±6%，模型对关键参数具有较好的鲁棒性。所建立的模型物理意义明确、求解高效、可扩展性强，可为实际烟幕干扰弹投放决策提供量化支撑。

关键词：烟幕干扰弹、投放策略、运动学仿真、多级网格搜索、分层贪心、协同优化
"""


def indent_body(text: str) -> str:
    """正文段落首行缩进两个全角空格（跳过标题/表格/列表/图片/公式/引用/分隔线）。"""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        # 不缩进：标题、表格、列表、图片、公式块、引用、分隔线、围栏
        if (stripped.startswith(("#", "|", "-", "*", ">", "!", "$", "```", "---", "=="))
                or stripped[0].isdigit() and ". " in stripped[:4]
                or stripped.startswith(("图", "表")) and len(stripped) < 40 and stripped[1:2] in "0123456789"):
            out.append(line)
            continue
        # 已是全角空格缩进的行跳过（幂等）
        if stripped.startswith("　　"):
            out.append(line)
            continue
        out.append("　　" + line)
    return "\n".join(out)


def main():
    text = SRC.read_text(encoding="utf-8")
    # 1. 替换摘要（从 "## 摘要" 到 "关键词" 行结束）
    start = text.find("## 摘要")
    kw_line = text.find("关键词：", start)
    kw_end = text.find("\n", kw_line)
    if start < 0 or kw_line < 0:
        raise SystemExit("未找到摘要/关键词")
    # 关键词行后可能紧跟 --- 分隔；保留分隔
    tail = text[kw_end + 1:]
    if tail.startswith("\n---"):
        tail = tail[1:]
    text = text[:start] + NEW_ABSTRACT.strip() + tail

    # 2. 正文缩进
    text = indent_body(text)

    dst = SRC.with_name("paper_20260817_150809_indent.md")
    dst.write_text(text, encoding="utf-8")
    print("已生成:", dst)
    print("摘要段落数:", NEW_ABSTRACT.count("\n\n") - 1)
    # 统计缩进行数
    indented = sum(1 for l in text.splitlines() if l.startswith("　　"))
    print("缩进段落数:", indented)


if __name__ == "__main__":
    main()
