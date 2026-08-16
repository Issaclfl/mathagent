"""论文修订闭环：审核 → 基于反馈修改 → 再审，直到通过或达最大轮数。

用法：
  python revise_paper.py                    # 用 data/results 里最新的论文
  python revise_paper.py paper_xxx.md       # 指定论文文件

每次修改基于【原论文全文 + 审核反馈】让 LLM 定向修改，不重写全文，节省 token。
修订版保存为 paper_revised_<时间戳>.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.audit import QualityGateAgent
from utils.llm_client import call_llm
from utils.config import get

RESULTS_DIR = Path(__file__).parent / "data" / "results"

REVISE_SYSTEM = """你是一位资深的数学建模竞赛论文修改专家。
你收到一篇已有论文全文，以及审核提出的问题清单。
你的任务：在原论文基础上【逐条修正】这些问题，保留原文中正确的内容和结构，
只修改有问题的部分。不要重写整篇论文，不要丢失原文的好的表述。
输出完整的修改后论文（Markdown 格式）。"""

REVISE_PROMPT = """请修改以下数学建模论文。

【赛题】
{problem_text}

【审核问题清单——必须逐条修正】
{feedback}

【原论文全文】
{paper}

【修改要求】
1. 逐条回应审核问题：每个问题的修改结果都应在正文中体现
2. 保留原文正确的结构、公式、表述，只改有问题的部分
3. 标题层级统一（## 章 / ### 节 / #### 小节）
4. 修改后输出【完整论文】，不要只输出改动片段，不要解释修改过程"""


def load_latest_paper() -> Path:
    papers = sorted(RESULTS_DIR.glob("paper*.md"), key=lambda p: p.stat().st_mtime)
    if not papers:
        print("未找到论文文件")
        sys.exit(1)
    return papers[-1]


def load_summary() -> dict:
    import json
    pipelines = sorted(RESULTS_DIR.glob("pipeline_*.json"), key=lambda p: p.stat().st_mtime)
    summary: dict = {
        "problem_text": "",
        "sub_problems": [],
        "algorithms": {},
        "models": [],
        "executions": [],
    }
    if pipelines:
        data = json.loads(pipelines[-1].read_text(encoding="utf-8"))
        for key in summary:
            if data.get(key) is not None:
                summary[key] = data[key]
    return summary


def revise_paper(paper: str, feedback: str, problem_text: str) -> str:
    """调用 LLM 基于反馈修改论文。"""
    prompt = REVISE_PROMPT.format(
        problem_text=(problem_text or "")[:1500],
        feedback=feedback[:8000],
        paper=paper[:30000],
    )
    max_retries = int(get("auditor.max_retries", 2) or 2)
    for attempt in range(max_retries):
        result = call_llm(prompt, system_prompt=REVISE_SYSTEM, temperature=0.3)
        if result and result.strip():
            # 清理 markdown 代码块包裹（若 LLM 包了）
            if result.strip().startswith("```") and result.strip().endswith("```"):
                lines = result.strip().splitlines()
                result = "\n".join(lines[1:-1])
            return result.strip()
        print(f"  LLM 未返回结果，重试 {attempt+1}/{max_retries}")
        time.sleep(2)
    raise RuntimeError("LLM 多次未返回修改结果")


def main() -> None:
    paper_path = Path(sys.argv[1]) if len(sys.argv) > 1 else load_latest_paper()
    if not paper_path.exists():
        print(f"论文不存在: {paper_path}")
        sys.exit(1)

    summary = load_summary()
    max_rounds = int(get("auditor.max_rounds", 100) or 100)
    max_stagnant = int(get("auditor.max_stagnant_rounds", 2) or 2)

    paper = paper_path.read_text(encoding="utf-8")
    gate = QualityGateAgent()
    current_paper = paper
    feedback = ""
    stagnant = 0
    best_overall = -1.0

    print(f"开始修订闭环（最多 {max_rounds} 轮，连续 {max_stagnant} 轮无提升自动停止）")
    print(f"原论文: {paper_path.name}")

    for round_i in range(1, max_rounds + 1):
        print(f"\n===== 第 {round_i} 轮审核 =====")
        report = gate.run(current_paper, summary)

        scores = report["scores"]
        overall = report["overall"]
        print(
            f"逻辑:{scores['logic']} 数据:{scores['data']} "
            f"排版:{scores['format']} 综合:{overall} "
            f"-> {'通过' if report['passed'] else '未通过'}"
        )

        if report["passed"]:
            print("🎉 质量门控通过")
            out = RESULTS_DIR / f"paper_passed_{time.strftime('%Y%m%d_%H%M%S')}.md"
            out.write_text(current_paper, encoding="utf-8")
            print(f"通过版论文已保存: {out}")
            break

        # 停滞保护：连续 N 轮综合分未提升则停止
        if overall > best_overall:
            best_overall = overall
            stagnant = 0
        else:
            stagnant += 1
            if stagnant >= max_stagnant:
                print(
                    f"⚠ 已连续 {max_stagnant} 轮综合分未提升"
                    f"（最好 {best_overall} 分），停止重写"
                )
                out = RESULTS_DIR / f"paper_force_{time.strftime('%Y%m%d_%H%M%S')}.md"
                out.write_text(current_paper, encoding="utf-8")
                print(f"强制接受版论文已保存: {out}")
                print("\n未通过问题（需人工处理）：")
                print(report["feedback"][:3000])
                break

        if round_i >= max_rounds:
            print(f"⚠ 已达最大轮数 {max_rounds}，接受当前版本")
            out = RESULTS_DIR / f"paper_force_{time.strftime('%Y%m%d_%H%M%S')}.md"
            out.write_text(current_paper, encoding="utf-8")
            print(f"强制接受版论文已保存: {out}")
            print("\n未通过问题（需人工处理）：")
            print(report["feedback"][:3000])
            break

        print(f"  未通过，正在基于反馈修改（第{round_i}轮）...")
        current_paper = revise_paper(
            current_paper, report["feedback"], summary.get("problem_text", "")
        )
        out = RESULTS_DIR / f"paper_revised_{time.strftime('%Y%m%d_%H%M%S')}.md"
        out.write_text(current_paper, encoding="utf-8")
        print(f"  修订版已保存: {out}")


if __name__ == "__main__":
    main()
