"""检查现有 pipeline 数据"""
import json, sys
sys.path.insert(0, r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
from pathlib import Path

results_dir = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\results")
for f in sorted(results_dir.glob("pipeline_*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    execs = data.get("executions", [])
    print(f"{f.name}: execs={len(execs)}", end="")
    if execs:
        for e in execs[:1]:
            print(f" status={e.get('status')} has_metrics={'metrics' in e}", end="")
    print()
