"""验证 pipeline 数据流"""
import json, sys
sys.path.insert(0, r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
from pathlib import Path

results_dir = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\results")
pipeline_files = sorted(results_dir.glob("pipeline_*.json"))
latest = pipeline_files[-1]
print(f"加载: {latest.name}")

summary = json.loads(latest.read_text(encoding="utf-8"))
print(f"sub_problems: {len(summary.get('sub_problems', []))}个")
print(f"algorithms: {len(summary.get('algorithms', {}))}个")
print(f"models: {len(summary.get('models', []))}个")
print(f"executions: {len(summary.get('executions', []))}个")

execs = summary.get("executions", [])
for i, e in enumerate(execs[:2]):
    print(f"\nexecution[{i}]:")
    print(f"  status: {e.get('status')}")
    print(f"  has metrics: {'metrics' in e}")
    if e.get("metrics"):
        nums = e["metrics"].get("numbers", {})
        print(f"  numbers: {list(nums.keys())[:5]}")
