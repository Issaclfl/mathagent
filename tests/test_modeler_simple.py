import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from agents.modeler import ModelerAgent

# 直接测试modeler，不依赖coordinator
problem_text = "某高校计划在校园内投放共享单车，需要确定各停车点的最优投放数量。"
sub_problems = [
    "确定各停车点的需求量和距离约束",
    "建立投放数量优化模型",
    "求解最优投放方案"
]

print("=== 直接测试ModelerAgent ===")
modeler = ModelerAgent()
result = modeler.run(problem_text, sub_problems)
print("状态:", result["status"])
print("主算法:", result["main_algorithm"])
print("理由:", result["reason"])
for item in result["sub_algorithms"]:
    print("  ", item["sub_problem"][:20], "->", item["algorithm"])
