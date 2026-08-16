"""HIL/门控 续跑：读取人工决策，注入最高真值，从断点继续流水线。

支持两类人工确认文件：
  - pending_*.json   HIL 数值确认（decision: confirm/edit/reject/abort）
  - ask_*.json       策略门控（answer: 人工的建模策略决定）

用法：
  python hil_resume.py data/hil/pending_<ts>.json
  python hil_resume.py data/hil/ask_modeling_strategy_<ts>.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import run_pipeline, CHECKPOINT_FILE, _save_checkpoint
from utils.hil import load_pending, apply_decisions
from utils.ask_gate import load_ask_file, apply_answer


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python hil_resume.py data/hil/pending_<ts>.json 或 ask_<gate>_<ts>.json")
        sys.exit(1)
    pending_path = Path(sys.argv[1])
    if not pending_path.exists():
        print(f"[FAIL] 待确认文件不存在: {pending_path}")
        sys.exit(1)

    if not CHECKPOINT_FILE.exists():
        print(f"[FAIL] 未找到断点: {CHECKPOINT_FILE}（请先正常跑完对应阶段）")
        sys.exit(1)

    summary = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
    problem_path = summary.get("problem_path", "")
    if not problem_path:
        print("[FAIL] 断点缺少 problem_path")
        sys.exit(1)

    data = json.loads(pending_path.read_text(encoding="utf-8"))

    if "gate" in data:
        # ── 策略门控：人工回答 → 注入 gate_answers → 续跑 ──
        print(f"应用策略门控「{data['gate']}」人工决定...")
        try:
            summary = apply_answer(summary, data)
        except ValueError as e:
            print(f"[FAIL] {e}")
            sys.exit(1)
        _save_checkpoint(summary, 0.0)
        print(f"已注入人工策略决定，继续流水线: {problem_path}")
        run_pipeline(problem_path, resume_from=str(CHECKPOINT_FILE))
        return

    # ── HIL 数值确认（原有流程）──
    # ── 关联校验：pending 文件必须与断点属于同一次运行 ──────
    # 断点是固定路径，任何新运行都会覆盖；旧 pending 文件若被误用，
    # 人工值会按序号注入到错误赛题的执行记录上，必须拒绝。
    pending = data
    pending_problem = pending.get("problem_path", "")
    pending_subs = pending.get("sub_problems") or []
    checkpoint_subs = summary.get("sub_problems", [])
    mismatch = []
    if pending_problem and Path(pending_problem).resolve() != Path(problem_path).resolve():
        mismatch.append(f"赛题不一致: pending={pending_problem} vs 断点={problem_path}")
    elif pending_subs and pending_subs != checkpoint_subs:
        mismatch.append(
            "子问题不一致: pending=%d个 vs 断点=%d个" % (len(pending_subs), len(checkpoint_subs))
        )
    if mismatch:
        print("[FAIL] pending 文件与当前断点不匹配，拒绝注入（可能是旧文件或断点已被新运行覆盖）：")
        for m in mismatch:
            print(f"  - {m}")
        print("  请重新运行流水线生成新的待确认文件。")
        sys.exit(1)

    # 应用人工决策（confirm/edit/reject/abort）
    print("应用人工决策...")
    try:
        summary = apply_decisions(summary, pending)
    except (ValueError, RuntimeError) as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    _save_checkpoint(summary, 0.0)
    print(f"已注入人工验证值，继续流水线: {problem_path}")

    # 从断点续跑（跳过已完成的求解，进入评审/论文/门控）
    run_pipeline(problem_path, resume_from=str(CHECKPOINT_FILE))


if __name__ == "__main__":
    main()
