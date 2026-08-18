"""经验库：记录每次 pipeline 的建模经验，供算法推荐作先验。

数据持久化到 data/experience.json，跨进程保留。
使用文件锁（filelock）防止并发读写导致数据损坏。

两类记录：
1. 算法-成功率统计（原功能）→ algorithm_prior 注入推荐先验
2. 决策教训 lesson（2026-08 新增）→ 解决"第一次就选对方向"：
   执行后把结构诊断与结果对比沉淀为教训，下次同类问题自动注入。
   内置 SEED_LESSONS 提供专家种子（2025A 实测教训），无需跑过就有先验。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from filelock import FileLock

EXPERIENCE_PATH = Path(__file__).parent.parent / "data" / "experience.json"
EXPERIENCE_LOCK = EXPERIENCE_PATH.with_suffix(".json.lock")

# 问题类型关键词，用于粗分类
TYPE_KEYWORDS: dict[str, list[str]] = {
    "预测": ["预测", "预报", "趋势", "估计", "拟合", "时序", "未来", "回归"],
    "优化": ["优化", "调度", "分配", "规划", "决策", "最小", "最大", "成本", "投放", "布局"],
    "评价": ["评价", "评估", "综合", "等级", "排序", "打分", "优劣", "指标"],
}

# ── 专家种子教训（无需先跑过就有先验，来自 2025A 实测）──────
SEED_LESSONS: list[dict] = [
    {
        "problem_type": "优化",
        "keywords": ["多弹", "多机", "协同", "投放", "调度", "时序", "多目标", "组合"],
        "lesson": "决策空间≥5维的连续优化严禁网格搜索——维数灾难下网格系统性次优"
                  "（实测 8 维三弹问题网格 5.30s vs 差分进化 6.9s）。必须用差分进化/"
                  "遗传算法等全局优化器，网格只作粗扫找起点。",
        "source": "2025A Q3/Q4",
    },
    {
        "problem_type": "优化",
        "keywords": ["遮蔽", "遮挡", "相交", "视线", "云团", "覆盖"],
        "lesson": "遮蔽/遮挡/距离类评估函数优先解析化：球心到线段距离是二次方程，"
                  "解析求根得到精确区间，避免离散采样——采样使目标函数呈阶梯不可导，"
                  "梯度优化器全失效且精度受限（实测 ±0.02s 采样精度）。",
        "source": "2025A Q1-Q5",
    },
    {
        "problem_type": "优化",
        "keywords": ["并集", "覆盖", "接力", "分配", "多目标"],
        "lesson": "多资源覆盖类问题先解耦：下层单资源最优区间预计算（快），"
                  "上层按区间调度/并集组合选择。直接联合优化高维空间难收敛，"
                  "贪心序贯决策容易锁死次优。",
        "source": "2025A Q3-Q5",
    },
]


def _classify(sub_problem: str) -> str:
    """根据关键词粗分类子问题类型。"""
    for ptype, keywords in TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in sub_problem:
                return ptype
    return "其他"


def load_experience() -> list[dict]:
    """加载全部经验记录。"""
    if not EXPERIENCE_PATH.exists():
        return []
    try:
        return json.loads(EXPERIENCE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_experience(records: list[dict]) -> None:
    """写经验库（调用方需已持有锁，避免嵌套加锁死锁）。"""
    EXPERIENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPERIENCE_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_experience(records: list[dict]) -> None:
    """覆盖保存经验记录（带文件锁）。"""
    with FileLock(str(EXPERIENCE_LOCK)):
        _write_experience(records)


def record(sub_problem: str, algorithm: str, success: bool, lesson: str | None = None) -> None:
    """记录一次建模尝试的经验（读-改-写全程加锁，防并发覆盖）。

    Args:
        sub_problem: 子问题文本
        algorithm: 使用的算法
        success: 执行是否成功
        lesson: 可选，决策教训（如"8维网格次优，应差分进化"——来自结构诊断
                与结果对比，下次同类问题自动注入）
    """
    with FileLock(str(EXPERIENCE_LOCK)):
        records = load_experience()
        records.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "problem_type": _classify(sub_problem),
            "sub_problem": sub_problem,
            "algorithm": algorithm,
            "success": bool(success),
            "lesson": lesson or "",
        })
        _write_experience(records)


def record_from_summary(summary: dict) -> None:
    """从 pipeline summary 批量记录经验（只记录实际执行过的子问题）。"""
    sub_problems = summary.get("sub_problems", [])
    algorithms = summary.get("algorithms", {})
    executions = summary.get("executions", [])
    diagnostics = summary.get("diagnostics", {}) or {}

    for i, sp in enumerate(sub_problems):
        exec_data = executions[i] if i < len(executions) else {}
        status = exec_data.get("status")
        if status not in ("ok", "error"):
            continue  # 跳过未执行/被跳过的子问题
        algo = algorithms.get(sp, "未确定")
        if algo == "未确定":
            continue
        # 决策教训：结构诊断建议的算法方向 vs 实际算法，记录差异供下次参考
        lesson = ""
        diag = diagnostics.get(sp) or {}
        if diag.get("dim_estimate", 0) >= 6 and status == "ok":
            if "网格" in algo or "枚举" in algo:
                lesson = ("≥6维优化用了网格/枚举（次优风险）；"
                          "应改用差分进化/遗传算法等全局优化器")
        record(sp, algo, success=(status == "ok"), lesson=lesson)


def lessons_for(sub_problem: str, top: int = 3) -> list[str]:
    """返回该子问题适用的决策教训（种子教训 + 历史积累）。

    匹配规则：关键词命中优先（问题类型仅弱过滤——"时序"这类词在
    预测/优化分类里归属不稳，关键词才是可靠信号）。
    """
    ptype = _classify(sub_problem)
    matched: list[str] = []
    for lesson in SEED_LESSONS:
        kws = lesson.get("keywords", [])
        if any(kw in sub_problem for kw in kws):
            matched.append(f"[经验] {lesson['lesson']}（来源：{lesson.get('source', '专家')}）")
    # 历史记录中同类型且有教训的
    for r in load_experience():
        if r.get("problem_type") == ptype and r.get("lesson"):
            matched.append(f"[经验] {r['lesson']}（来源：历史记录）")
    # 去重保序
    seen: set[str] = set()
    unique = []
    for m in matched:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique[:top]


def algorithm_prior(
    sub_problem: str,
    algorithm_pool: list[str],
    min_samples: int = 5,
) -> list[dict]:
    """返回同类型问题的算法先验（按成功率排序）。

    Args:
        sub_problem: 子问题文本
        algorithm_pool: 算法池
        min_samples: 最少样本数，样本不足的算法不纳入先验

    Returns:
        [{"algorithm": str, "success_rate": float, "samples": int}, ...]
    """
    ptype = _classify(sub_problem)
    records = [r for r in load_experience() if r.get("problem_type") == ptype]
    if not records:
        return []

    stats: dict[str, list[bool]] = {}
    for r in records:
        algo = r.get("algorithm", "")
        if algo not in algorithm_pool:
            continue
        stats.setdefault(algo, []).append(bool(r.get("success")))

    result = []
    for algo, outcomes in stats.items():
        if len(outcomes) < min_samples:
            continue
        result.append({
            "algorithm": algo,
            "success_rate": round(sum(outcomes) / len(outcomes), 2),
            "samples": len(outcomes),
        })
    result.sort(key=lambda x: (x["success_rate"], x["samples"]), reverse=True)
    return result
