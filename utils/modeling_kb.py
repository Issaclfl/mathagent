"""建模知识库：题型分类 + 算法白名单 + 易错模式。

背景（b2025 实测暴露）：LLM 给物理推导题推荐"决策树/SVM/神经网络"，
给厚度反演题推荐"回归分析"作为主算法——算法-题型错配是推荐质量的主要问题。
本模块用确定性规则先做题型分类，生成【算法白名单】注入 Modeler 提示词，
并在后处理强制约束（LLM 推荐出白名单的算法会被替换回白名单内最相近的算法）。

设计哲学：规则先行、LLM 兜底——分类和约束是确定的，推荐理由仍是 LLM 生成。
"""
from __future__ import annotations

import difflib
import re

# ── 题型分类规则：关键词 → 题型 ──────────────────────────────

_PROBLEM_TYPES = [
    ("物理推导", [
        "物理", "光学", "干涉", "衍射", "折射", "波长", "波数", "反射率", "厚度",
        "力学", "应力", "应变", "振动", "声", "电磁", "电场", "磁场", "电路",
        "热传导", "传热", "流体", "流场", "材料", "晶体", "光谱", "外延",
        "半导体", "传感器", "频", "傅里叶", "FFT", "相位", "光程",
    ]),
    ("数据预测", [
        "预测", "预报", "时间序列", "销量", "需求", "未来", "趋势", "客流",
        "负荷", "产量", "价格走势", "指数", "增长率", "碳排放预测", "人口",
    ]),
    ("综合评价", [
        "评价", "评估", "排序", "优选", "选址", "综合", "指标", "评分", "权重",
        "竞争力", "绩效", "质量评价", "风险评估", "方案比选",
    ]),
    ("优化决策", [
        "优化", "最大", "最小", "成本", "利润", "调度", "分配", "规划", "收益",
        "资源", "库存", "路径", "排班", "投资", "生产计划", "运力",
    ]),
    ("分类判别", [
        "分类", "判别", "识别", "检测", "诊断", "判定", "是否", "异常",
        "故障", "模式识别", "甄别", "筛查",
    ]),
    ("聚类分析", [
        "聚类", "分组", "划分", "细分", "群落", "分群", "归并",
    ]),
]

# ── 题型 → 算法白名单 ─────────────────────────────────────────

_WHITELISTS: dict[str, list[str]] = {
    # 物理推导：数值求解/拟合/反演类；严禁分类/评价类
    "物理推导": [
        "粒子群优化", "模拟退火", "遗传算法", "回归分析",
        "线性规划", "整数规划",
    ],
    # 数据预测
    "数据预测": [
        "ARIMA时间序列", "灰色预测GM(1,1)", "指数平滑",
        "回归分析", "神经网络",
    ],
    # 综合评价
    "综合评价": [
        "层次分析法(AHP)", "熵权法", "TOPSIS",
        "主成分分析(PCA)", "聚类分析",
    ],
    # 优化决策
    "优化决策": [
        "线性规划", "整数规划", "遗传算法", "粒子群优化", "模拟退火",
    ],
    # 分类判别
    "分类判别": [
        "支持向量机(SVM)", "决策树", "随机森林", "神经网络", "回归分析",
    ],
    # 聚类分析
    "聚类分析": [
        "聚类分析", "主成分分析(PCA)",
    ],
    # 未知题型：全池
    "未知": [
        "线性规划", "整数规划", "遗传算法", "粒子群优化", "模拟退火",
        "ARIMA时间序列", "灰色预测GM(1,1)", "指数平滑", "回归分析",
        "层次分析法(AHP)", "熵权法", "TOPSIS", "聚类分析",
        "主成分分析(PCA)", "神经网络", "支持向量机(SVM)",
        "决策树", "随机森林",
    ],
}

# ── 易错模式（注入提示词，降低模型幻觉）──────────────────────

_MISUSE_HINTS: dict[str, str] = {
    "物理推导": (
        "【易错警示】物理推导/参数反演题严禁使用分类、聚类、评价类算法"
        "（决策树、SVM、随机森林、聚类、AHP、TOPSIS 均不适用）；"
        "应使用数值求解/曲线拟合/全局优化类算法，且代码必须约束物理参数范围"
        "（如厚度>0、折射率1~5），并对结果做自洽性检验。"
    ),
    "数据预测": (
        "【易错警示】预测题严禁把分类算法（决策树/SVM）当预测器使用；"
        "时间序列优先 ARIMA/灰色/指数平滑，多变量回归或神经网络仅在样本充足时使用。"
    ),
    "综合评价": (
        "【易错警示】评价题若已知客观数据优先熵权法/TOPSIS，主观性强的用 AHP；"
        "评价类算法不得用于预测或物理求解。"
    ),
    "优化决策": (
        "【易错警示】确定性约束问题优先线性/整数规划；大规模非线性用遗传/粒子群/"
        "模拟退火；优化结果必须给出目标函数值与约束满足情况。"
        "【业务约束易错——必须遵守】"
        "① 总量守恒必须包含仓库/中心节点（仓库是供源与收容点，严禁只对业务站点做"
        " ΣX=ΣS 守恒而排除仓库，否则短缺会全部甩给个别站点）；"
        "② 容量是约束上限，不等于实际载货量，两者严禁混用；"
        "③ 目标函数是综合成本，量纲不同的项需说明含义（如距离km + M×未满足辆）；"
        "④ 灵敏度分析必须基于最终联合模型（耦合数量与路径）的输出，严禁用中间步骤"
        " 或固定方案的数据；"
        "⑤ 每个站点有非零装卸量时，路径必须访问该站点。"
    ),
    "分类判别": (
        "【易错警示】分类题需给出准确率/精确率/召回率等评价指标；"
        "样本量小时优先简单模型，防止过拟合。"
    ),
    "聚类分析": (
        "【易错警示】聚类题需说明聚类数确定方法（肘部法/轮廓系数）并给出簇特征分析。"
    ),
    "未知": "",
}


def classify_problem(*texts: str) -> str:
    """按关键词规则分类题型；多个文本（赛题+子问题）合并计分，取命中最多者。"""
    combined = " ".join(t for t in texts if t)
    if not combined:
        return "未知"
    best_type, best_hits = "未知", 0
    for ptype, keywords in _PROBLEM_TYPES:
        hits = sum(1 for kw in keywords if kw in combined)
        if hits > best_hits:
            best_type, best_hits = ptype, hits
    return best_type


def algo_whitelist(problem_type: str) -> list[str]:
    """返回该题型允许使用的算法白名单。"""
    return list(_WHITELISTS.get(problem_type, _WHITELISTS["未知"]))


def kb_text(problem_type: str, whitelist: list[str]) -> str:
    """生成注入提示词的知识库文本（题型 + 白名单 + 易错模式）。"""
    parts = [
        f"【题型判定】本题属于「{problem_type}」类问题。",
        "【算法白名单——只能从以下算法中选择，禁止使用名单之外的算法】"
        + "、".join(whitelist),
    ]
    hint = _MISUSE_HINTS.get(problem_type, "")
    if hint:
        parts.append(hint)
    return "\n".join(parts)


def enforce_whitelist(
    algo: str,
    whitelist: list[str],
    pool: set[str],
    alias_map: dict[str, str] | None = None,
) -> str:
    """把算法名约束到白名单内（确定性后处理）。

    1. 先按 _match_algorithm 归一化到池；
    2. 若已在白名单 → 直接返回；
    3. 否则在池内找与白名单的最近匹配：先用别名映射，再 difflib 相似度，
       最后子串；仍失败回退白名单第 1 个（确定性兜底，宁可用错不用"未确定"——
       不对，规则要求严格：回退到相似度最高的白名单算法）。
    """
    alias_map = alias_map or {}
    # 归一化候选
    def _norm(a: str) -> str:
        a = a.strip()
        if a in pool:
            return a
        if a in alias_map:
            return alias_map[a]
        m = difflib.get_close_matches(a, pool, n=1, cutoff=0.6)
        if m:
            return m[0]
        c = [v for v in pool if a in v or v in a]
        if c:
            return max(c, key=len)
        return ""

    norm = _norm(algo)
    if norm in whitelist:
        return norm
    # 不在白名单：找白名单中最相近的（归一化后比较）
    best, best_score = None, 0.0
    for w in whitelist:
        score = difflib.SequenceMatcher(None, norm or algo, w).ratio()
        if score > best_score:
            best, best_score = w, score
    return best if best else whitelist[0]


# ══════════════════════════════════════════════════════════
# 问题结构诊断（确定性规则）：维度估计 + 组合结构 + 可解析化
# + 边界风险 → 生成【建模策略红线】注入 Modeler/Builder
#
# 背景（2025A 实测暴露）：8 维三弹优化用了网格搜索 → 5.30s 次优
# （差分进化 6.9s）；遮蔽评估用离散采样 → 阶梯函数不可导，梯度方法
# 全失效。方向性错误一旦发生，后续修复链都在错误方向上打转。
# 结构诊断让智能体在写代码前先"想清楚问题长什么样"。
# ══════════════════════════════════════════════════════════

# 决策变量个数线索：N 枚/架/个/辆 + 每单位几个参数（如"每枚弹的投放时刻与起爆间隔"）
_DIM_HINTS = [
    # 数量词："3枚烟幕干扰弹" / "5架无人机" / "三枚导弹"（含中文数字）
    (r"([一二三四五六七八九十\d]+)\s*[枚架颗发辆个座](?:(?!，|。|；).){0,8}?(?:弹|机|车|无人机|导弹)", 2),
    (r"(?:同时优化|决策变量为|变量为).{0,30}?([θxθv]|theta|速度|时刻|间隔|角度)", 4),
]

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10, "两": 2}

# 组合/协同结构关键词 → 提示解耦
_COMBINE_HINTS = ["并集", "组合", "协同", "协调", "接力", "分配", "覆盖", "时序", "多弹", "多枚",
                  "多机", "多目标", "衔接", "调度", "轮流", "分层"]

# 可解析化评估关键词（物理求根类）
_ANALYTIC_HINTS = ["遮蔽", "遮挡", "相交", "视线", "云团", "区间", "时长", "覆盖时间",
                   "穿透", "投影", "最短距离", "球", "半径", "线段"]

# 约束边界风险关键词（最优贴边界提示截断）
_BOUNDARY_HINTS = ["至少", "不低于", "不超过", "上限", "下限", "范围", "最大", "最小",
                   "间隔", "限制", "约束"]


def analyze_problem_structure(sub_problem: str) -> dict:
    """确定性诊断子问题的建模结构（零 LLM 调用）。

    Returns:
        {
          "dim_estimate": int,      # 决策空间维度估计（0=未知）
          "has_combination": bool,  # 组合/协同结构
          "has_analytic": bool,     # 评估函数疑似可解析化
          "has_boundary_risk": bool,# 约束边界风险
        }
    """
    text = sub_problem or ""
    dim = 0
    # 显式维度：N 维
    m = re.search(r"(\d+)\s*维", text)
    if m:
        dim = max(dim, int(m.group(1)))
    # 单位数：数字量词（3枚）+ 定性量词（多枚/单枚/若干——LLM 拆题
    # 常写"多枚烟幕干扰弹"而非"3枚"，实测 2025A 拆题全部定性化）
    units: list[int] = []
    for um in re.finditer(r"([一二三四五六七八九十\d]+)\s*[枚架颗发辆个座](?:(?!，|。|；).){0,8}?(?:弹|机|车|无人机|导弹)", text):
        token = um.group(1)
        units.append(max(_CN_NUM.get(token) or (int(token) if token.isdigit() else 1), 1))
    for qual, n in (
        (r"多(?:枚|弹|机|架|辆|个|目标|无人机|架次)", 3),
        (r"(?:若干|数|几)(?:枚|弹|机|架|辆|个)", 3),
        (r"单(?:枚|弹|机|架|辆|个|无人机)", 1),
        (r"各(?:枚|弹|机|架|辆|个|无人机)", 2),
    ):
        if re.search(qual, text):
            units.append(n)
    if units:
        # 每单位参数数：显式参数词优先；优化类无参数词默认 4（θ,v,t_d,τ 类）
        param_count = sum(
            1 for kw in ("时刻", "间隔", "速度", "角度", "方向", "位置", "起爆")
            if kw in text
        )
        per_unit = max(param_count, 4 if "优化" in text else 2)
        dim = max(dim, max(units) * per_unit)
    # 变量列举
    if "变量" in text or "参数" in text:
        var_kws = [k for k in ("时刻", "间隔", "速度", "角度", "方向", "投放", "起爆") if k in text]
        dim = max(dim, len(var_kws))
    # 组合结构下多单位/多目标：高维估计兜底（"多弹/多机/多目标" + 组合结构）
    has_comb = any(k in text for k in _COMBINE_HINTS)
    if has_comb:
        multi_units = sum(1 for u in units if u >= 2) + (1 if "多" in text else 0)
        if multi_units >= 2 or any(k in text for k in ("多弹", "多机", "多目标", "协同", "协调")):
            dim = max(dim, 8)
    return {
        "dim_estimate": dim,
        "has_combination": has_comb,
        "has_analytic": any(k in text for k in _ANALYTIC_HINTS),
        "has_boundary_risk": any(k in text for k in _BOUNDARY_HINTS),
    }


def structure_redline(struct: dict) -> str:
    """由结构诊断生成【建模策略红线】文本（注入 Modeler/Builder prompt）。"""
    lines = ["【建模策略红线（问题结构诊断，必须遵守）】"]
    dim = struct.get("dim_estimate", 0)
    if dim > 0:
        if dim >= 6:
            lines.append(
                f"- 决策空间估计 {dim} 维（≥6 维连续优化）：禁止网格搜索/枚举——维数灾难下"
                "网格会系统性次优（实测 8 维三弹问题网格 5.30s vs 差分进化 6.9s）；"
                "必须用差分进化 / 遗传算法等全局优化器"
            )
        elif dim >= 3:
            lines.append(
                f"- 决策空间估计 {dim} 维：网格搜索仅适合 ≤2 维；{dim} 维建议"
                "差分进化或模拟退火等全局方法，网格只能作粗扫找起点"
            )
    else:
        lines.append("- 决策空间维度未知：先明确决策变量再选算法；多变量联合优化优先全局优化器")
    if struct.get("has_analytic"):
        lines.append(
            "- 评估函数疑似可解析化（遮蔽/相交/距离类）：优先解析求根（如球心到线段"
            "距离的二次方程）而非离散采样——采样使目标函数呈阶梯、不可导，"
            "梯度优化器全失效且精度受限"
        )
        lines.append(
            "- 【计算模板要求】判定函数必须包含自测：\n"
            "  ① 写 check_判定函数()，用'明显通过'和'明显不通过'两个案例验证\n"
            "  ② 打印每步中间结果：坐标、距离、判定布尔值\n"
            "  ③ 生成示意图可视化判定结果（导弹轨迹+云团+遮蔽区间）\n"
            "  ④ 全零结果 90% 是判定条件写反（<写成>）或坐标系不一致"
        )
    if struct.get("has_combination"):
        lines.append(
            "- 存在组合/协同结构（并集/多弹/多机/分配）：先解耦——下层单资源最优"
            "区间预计算，上层按区间调度/并集组合选择；直接联合优化高维空间难收敛"
        )
    if struct.get("has_boundary_risk"):
        lines.append(
            "- 存在约束边界风险：最优解贴边界（如间隔=下限）时可能被截断，"
            "需检查并说明；灵敏度分析覆盖边界两侧"
        )
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
