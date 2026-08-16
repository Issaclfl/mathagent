"""HIL 人机协作闸门：无 ground truth 的子问题，求解后暂停等人工确认。

设计（见 DESIGN_数值可靠性改造.md）：
  - 触发：config.hil.enabled=true 且 该问题无人工/独立验证结果（_verified_results 为空）
  - 流程：写 pending json → 打 checkpoint → 退出；人审后运行 hil_resume.py 续跑
  - 人工值 = 最高真值（verified_human），覆盖代码输出
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from utils.config import get

HIL_DIR = Path(__file__).resolve().parent.parent / "data" / "hil"

DECISIONS = {"confirm", "edit", "reject", "abort"}


def hil_enabled() -> bool:
    return bool(get("hil.enabled", False))


def should_pause(summary: dict) -> bool:
    """是否应暂停：启用 HIL 且 已有执行记录 且 无人工/独立验证结果（无真值）。

    人工已通过 hil_resume.py 处理过（_hil_confirmed）或已注入真值时不再暂停，
    否则 confirm/reject 全选后 _verified_results 仍为空，会造成无限暂停循环。
    """
    if not hil_enabled():
        return False
    if summary.get("_hil_confirmed"):
        return False
    if not summary.get("executions"):
        return False
    if summary.get("_verified_results"):
        return False
    return True


def write_pending(summary: dict, executions: list[dict],
                  sub_problems: list[str]) -> Path:
    """写出待人工确认文件，返回路径。"""
    HIL_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    items = []
    for i, sp in enumerate(sub_problems):
        ex = executions[i] if i < len(executions) else {}
        if ex.get("status") != "ok":
            items.append({
                "index": i + 1,
                "sub_problem": sp,
                "status": ex.get("status", "skipped"),
                "decision": "",  # 待填
                "value": "",     # edit 时填正确数值
                "metrics_json": ex.get("metrics_json", {}),
                "output_preview": (ex.get("output") or "")[:300],
            })
            continue
        items.append({
            "index": i + 1,
            "sub_problem": sp,
            "status": "ok",
            "decision": "",     # 待填：confirm / edit / reject
            "value": "",        # edit 时填正确数值
            "metrics_json": ex.get("metrics_json", {}),
            "output_preview": (ex.get("output") or "")[:300],
        })
    payload = {
        "_hint": "对每个子问题填写 decision（confirm=认可当前值 / edit=填正确值到 value / "
                 "reject=拒绝），然后运行 hil_resume.py <本文件路径>",
        # 快照：供 hil_resume 校验本文件与断点是否同一次运行，防止旧 pending 文件错配
        "problem_path": summary.get("problem_path", ""),
        "sub_problems": list(sub_problems),
        "items": items,
    }
    path = HIL_DIR / f"pending_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_pending(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_decisions(summary: dict, pending: dict) -> dict:
    """把人工决策应用到 summary.executions，返回决策摘要。

    confirm → verified_human；edit → 覆盖 metrics_json + verified_human；
    reject → unverified；abort → 抛异常终止。
    """
    from utils.verification import STATUS_HUMAN, STATUS_UNVERIFIED

    items = pending.get("items", [])
    execs = summary.setdefault("executions", [])
    by_index = {it["index"]: it for it in items}
    human_lines = []
    processed = False
    for i, ex in enumerate(execs):
        it = by_index.get(i + 1)
        if not it:
            continue
        decision = (it.get("decision") or "").strip().lower()
        if decision == "confirm":
            ex["verification_status"] = STATUS_HUMAN
        elif decision == "edit":
            value = it.get("value")
            if value in (None, ""):
                raise ValueError(f"子问题{i+1} 决策为 edit 但未填写 value")
            try:
                num = float(value)
            except (TypeError, ValueError):
                num = value
            ex["metrics_json"] = {"人工验证值": num}
            ex["verification_status"] = STATUS_HUMAN
            # 可解析格式（DataAuditor.parse_verified_refs 能直接读出）：
            # 半角冒号 + 直接数值，不带"人工值"前缀与全角括号
            human_lines.append(f"子问题{i+1}: {num}")
        elif decision == "reject":
            ex["verification_status"] = STATUS_UNVERIFIED
        elif decision == "abort":
            raise RuntimeError("用户选择 abort，终止任务")
        elif decision == "":
            raise ValueError(f"子问题{i+1} 未填写 decision")
        else:
            raise ValueError(f"子问题{i+1} 非法 decision: {decision!r}")
        processed = True
    # 人工值并入 _verified_results，供数据审核优先使用
    if human_lines:
        summary["_verified_results"] = (
            (summary.get("_verified_results") or "").strip()
            + "\n" + "\n".join(human_lines)
        ).strip()
    # 已确认标记：confirm/reject 全选时 _verified_results 可能仍为空，
    # 该标记防止 HIL 闸门在 resume 后再次暂停（无限循环）
    if processed:
        summary["_hil_confirmed"] = True
    return summary
