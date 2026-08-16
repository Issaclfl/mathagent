"""数学建模智能体 - 端到端测试（结果输出到文件）"""
import logging
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from utils.file_parser import parse_file
from agents.coordinator import CoordinatorAgent
from agents.modeler import ModelerAgent


def main():
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    # 1. 读取赛题
    problem = parse_file("data/problems/bike_shared.txt")
    log("=" * 60)
    log("赛题：")
    log(problem[:300] + "...")
    log("=" * 60)

    # 2. 协调者拆题
    coord = CoordinatorAgent()
    sub_problems = coord.run(problem)
    log(f"\n拆解得到 {len(sub_problems)} 个子问题：")
    for i, sp in enumerate(sub_problems, 1):
        log(f"  {i}. {sp}")

    if not sub_problems:
        log("拆题失败，终止测试")
        return

    # 3. 建模者推荐算法
    modeler = ModelerAgent()
    result = modeler.run(problem, sub_problems)

    log(f"\n推荐结果：")
    log(f"  状态：{result['status']}")
    log(f"  主算法：{result['main_algorithm']}")
    log(f"  理由：{result['reason']}")
    log(f"  各子问题算法：")
    for item in result["sub_algorithms"]:
        log(f"    {item['sub_problem'][:40]} -> {item['algorithm']}")

    # 4. 验证 state
    log(f"\nstate 验证：")
    log(f"  coordinator.sub_problems: {coord.get_state('sub_problems') is not None}")
    log(f"  modeler.main_algorithm: {modeler.get_state('main_algorithm')}")
    log(f"  modeler.sub_algorithms: {modeler.get_state('sub_algorithms') is not None}")

    # 写入临时目录便于查看（不污染 data/ —— 测试产物会干扰数据清单与验证扫描）
    out = Path(tempfile.gettempdir()) / "mathagent_test_run.txt"
    out.write_text("\n".join(log_lines), encoding="utf-8")
    log(f"\n结果已保存到 {out}")


if __name__ == "__main__":
    main()
