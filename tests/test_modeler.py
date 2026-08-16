import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from utils.file_parser import parse_file
from agents.coordinator import CoordinatorAgent
from agents.modeler import ModelerAgent

problem_text = parse_file("data/problems/bike_shared.txt")
coordinator = CoordinatorAgent()
sub_problems = coordinator.run(problem_text)

print("=== Step2: 推荐算法 ===")
modeler = ModelerAgent()
result = modeler.run(problem_text, sub_problems)
print("主算法:", result["main_algorithm"])
print("推荐理由:", result["reason"])
for item in result["sub_algorithms"]:
    print("  ", item["sub_problem"][:30], "->", item["algorithm"])
