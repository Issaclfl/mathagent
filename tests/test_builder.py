import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from agents.builder import BuilderAgent

print("=== 测试BuilderAgent ===")
builder = BuilderAgent()

result = builder.run(
    problem_text="某高校计划在校园内投放共享单车，需要确定各停车点的最优投放数量。",
    sub_problem="建立投放数量优化模型，使得总体服务水平最高",
    algorithm="线性规划"
)

print("状态:", result["status"])
print("代码行数:", len(result["code"].splitlines()))
print()
print("=== 数学模型 ===")
print(result["math_model"][:500])
print()
print("=== Python代码预览 ===")
print(result["code"][:800])
