import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from agents.builder import BuilderAgent
from agents.solver import SolverAgent

print("=== 完整流程：Builder -> Solver ===")
print()

# 1. 生成代码
builder = BuilderAgent()
build_result = builder.run(
    problem_text="某高校计划在校园内投放共享单车，需要确定各停车点的最优投放数量。",
    sub_problem="建立投放数量优化模型，使得总体服务水平最高",
    algorithm="线性规划"
)

print("【BuilderAgent】")
print("状态:", build_result["status"])
print("代码行数:", len(build_result["code"].splitlines()))
print()

# 2. 执行代码
if build_result["status"] == "ok":
    print("【SolverAgent 执行代码】")
    solver = SolverAgent()
    solve_result = solver.run(build_result["code"])
    print("状态:", solve_result["status"])
    print("尝试次数:", solve_result.get("attempts", "N/A"))
    if solve_result["status"] == "ok":
        print("输出:")
        print(solve_result.get("output", "")[:500])
    else:
        print("错误:", solve_result.get("error", "")[:200])
