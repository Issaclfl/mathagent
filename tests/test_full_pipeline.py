import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from utils.file_parser import parse_file
from agents.coordinator import CoordinatorAgent
from agents.modeler import ModelerAgent
from agents.builder import BuilderAgent

# 1. 读取赛题
problem_text = parse_file("data/problems/bike_shared.txt")
print("=" * 60)
print("赛题内容：")
print(problem_text[:200] + "...")
print("=" * 60)
print()

# 2. 拆解子问题
print("【第一步】CoordinatorAgent 拆解赛题")
coordinator = CoordinatorAgent()
sub_problems = coordinator.run(problem_text)
for i, sp in enumerate(sub_problems, 1):
    print(f"  子问题{i}: {sp}")
print()

# 3. 推荐算法
print("【第二步】ModelerAgent 推荐算法")
modeler = ModelerAgent()
result = modeler.run(problem_text, sub_problems)
print(f"  主算法: {result['main_algorithm']}")
print(f"  推荐理由: {result['reason']}")
for item in result["sub_algorithms"]:
    print(f"  {item['sub_problem'][:30]} -> {item['algorithm']}")
print()

# 拆题/推荐失败（LLM 空响应等）时优雅退出，不崩溃
if not sub_problems or not result.get("sub_algorithms"):
    print("[!] 拆题或算法推荐返回空（可能是 LLM 临时不可用），测试提前结束")
    raise SystemExit(0)

# 4. 生成代码（只测试第一个子问题）
print("【第三步】BuilderAgent 生成代码")
builder = BuilderAgent()
first_sp = sub_problems[0]
first_algo = result["sub_algorithms"][0]["algorithm"]
print(f"  子问题: {first_sp}")
print(f"  算法: {first_algo}")
build_result = builder.run(problem_text, first_sp, first_algo)
print(f"  状态: {build_result['status']}")
print(f"  代码行数: {len(build_result['code'].splitlines())}")
print(f"  语法验证: {'通过' if build_result['status'] == 'ok' else build_result.get('error', '')}")
print()
print("=" * 60)
print("全流程测试完成！")
