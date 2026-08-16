"""仅重跑质量门控审核 - 加载最新论文，不重新生成论文（节省 token）。

用法：
  python resume_audit.py                  # 用 data/results 里最新的 paper_*.md
  python resume_audit.py paper_xxx.md     # 指定论文文件
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.audit import QualityGateAgent
from utils.verified_results import load_verified_results

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"
DATA_DIR = Path(__file__).parent.parent / "data"


def load_latest_paper() -> Path:
    """获取最新的 paper_*.md 文件。"""
    papers = sorted(RESULTS_DIR.glob("paper_*.md"), key=lambda p: p.stat().st_mtime)
    if not papers:
        print("未找到论文文件")
        sys.exit(1)
    return papers[-1]


def load_latest_summary() -> dict:
    """加载最新的 pipeline summary（用于逻辑/数据审核的上下文）。"""
    pipelines = sorted(
        RESULTS_DIR.glob("pipeline_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    summary: dict = {
        "problem_text": "",
        "sub_problems": [],
        "algorithms": {},
        "models": [],
        "executions": [],
        "_verified_results": "",
    }
    if not pipelines:
        print("未找到 pipeline JSON，审核时将缺少赛题/算法上下文")
        return summary
    data = json.loads(pipelines[-1].read_text(encoding="utf-8"))
    for key in ("problem_text", "sub_problems", "algorithms", "models", "executions"):
        if data.get(key) is not None:
            summary[key] = data[key]
    # 加载已验证的真实结果（人工/独立验证，如 data/**/厚度计算结果.csv）
    summary["_verified_results"] = load_verified_results()
    return summary


def main() -> None:
    paper_path = Path(sys.argv[1]) if len(sys.argv) > 1 else load_latest_paper()
    if not paper_path.exists():
        print(f"论文不存在: {paper_path}")
        sys.exit(1)

    print(f"论文: {paper_path.name} ({paper_path.stat().st_size} 字节)")
    summary = load_latest_summary()
    print(f"上下文: 子问题{len(summary['sub_problems'])}个, "
          f"执行记录{len(summary['executions'])}条")

    paper = paper_path.read_text(encoding="utf-8")
    gate = QualityGateAgent()
    report = gate.run(paper, summary)

    print()
    print("=" * 50)
    scores = report["scores"]
    print(f"逻辑: {scores['logic']} 分")
    print(f"数据: {scores['data']} 分")
    print(f"排版: {scores['format']} 分")
    print(f"综合: {report['overall']} 分")
    print(f"门控: {'通过' if report['passed'] else '未通过'} "
          f"(每项>8且综合>9)")
    print("=" * 50)
    print()
    print(report["feedback"])


if __name__ == "__main__":
    main()
