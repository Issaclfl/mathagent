"""经验库：记录每次 pipeline 的建模经验，供算法推荐作先验。

数据持久化到 data/experience.json，跨进程保留。
使用文件锁（filelock）防止并发读写导致数据损坏。
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


def record(sub_problem: str, algorithm: str, success: bool) -> None:
    """记录一次建模尝试的经验（读-改-写全程加锁，防并发覆盖）。"""
    with FileLock(str(EXPERIENCE_LOCK)):
        records = load_experience()
        records.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "problem_type": _classify(sub_problem),
            "sub_problem": sub_problem,
            "algorithm": algorithm,
            "success": bool(success),
        })
        _write_experience(records)


def record_from_summary(summary: dict) -> None:
    """从 pipeline summary 批量记录经验（只记录实际执行过的子问题）。"""
    sub_problems = summary.get("sub_problems", [])
    algorithms = summary.get("algorithms", {})
    executions = summary.get("executions", [])

    for i, sp in enumerate(sub_problems):
        exec_data = executions[i] if i < len(executions) else {}
        status = exec_data.get("status")
        if status not in ("ok", "error"):
            continue  # 跳过未执行/被跳过的子问题
        algo = algorithms.get(sp, "未确定")
        if algo == "未确定":
            continue
        record(sp, algo, success=(status == "ok"))


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
