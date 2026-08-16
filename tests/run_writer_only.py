"""单独运行 WriterAgent - 使用已保存的 pipeline 结果"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from agents.writer import WriterAgent

results_dir = Path(__file__).parent.parent / "data" / "results"
latest = sorted(results_dir.glob("pipeline_20260731_16*.json"))[-1]
print(f"加载: {latest.name}")
summary = json.loads(latest.read_text(encoding="utf-8"))

sub_count = len(summary.get("sub_problems", []))
model_count = len(summary.get("models", []))
print(f"子问题: {sub_count}个, 模型: {model_count}个")

agent = WriterAgent()
result = agent.run(summary)

print(f"\n状态: {result['status']}")
print(f"论文: {result['paper_path']}")
if result.get("error"):
    print(f"错误: {result['error']}")
else:
    content = result.get("content", "")
    print(f"字数: {len(content)}字符")
