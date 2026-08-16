"""用已有数据生成论文"""
import json, sys
sys.path.insert(0, r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
from pathlib import Path
from agents.writer import WriterAgent

results_dir = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\results")
latest = sorted(results_dir.glob("pipeline_20260731_18*.json"))[-1]
print(f"加载: {latest.name}")
summary = json.loads(latest.read_text(encoding="utf-8"))

execs = summary.get("executions", [])
ok_count = sum(1 for e in execs if e.get("status") == "ok")
print(f"子问题: {len(summary['sub_problems'])}个, 执行成功: {ok_count}/{len(execs)}")

agent = WriterAgent()
result = agent.run(summary)

print(f"\n状态: {result['status']}")
print(f"论文: {result['paper_path']}")
if result.get("warnings"):
    for w in result["warnings"]:
        print(f"  警告: {w}")
content = result.get("content", "")
print(f"字数: {len(content)}字符")
