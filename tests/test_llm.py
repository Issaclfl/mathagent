import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from utils.llm_client import call_llm

# 测试LLM调用
print("=== 测试LLM调用 ===")
result = call_llm("用一句话介绍线性规划", temperature=0.2)
print("LLM返回:", result[:100] if result else "无结果")
