"""逐个执行代码并提取指标，更新 pipeline 结果（优化版：每个子问题独立保存）"""
import json, sys, time
sys.path.insert(0, r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
from pathlib import Path
from agents.solver import SolverAgent

results_dir = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent\data\results")
latest = sorted(results_dir.glob("pipeline_20260731_18*.json"))[-1]
print(f"加载: {latest.name}")

summary = json.loads(latest.read_text(encoding="utf-8"))
sub_problems = summary["sub_problems"]
models = summary["models"]

solver = SolverAgent()
executions = []

for i, (sp, model) in enumerate(zip(sub_problems, models)):
    code = model.get("code", "")
    if not code:
        print(f"  [{i+1}] 无代码，跳过")
        executions.append({"sub_problem": sp, "status": "skipped"})
        continue

    print(f"  [{i+1}] {sp[:35]}...", end=" ", flush=True)
    start = time.time()
    # 只重试1次，加快速度
    result = solver.fix_code(code, max_retries=1)
    elapsed = time.time() - start
    result["sub_problem"] = sp
    executions.append(result)

    if result["status"] == "ok":
        nums = result.get("metrics", {}).get("numbers", {})
        print(f"OK ({elapsed:.0f}s) {len(nums)}个数值")
    else:
        print(f"FAIL ({elapsed:.0f}s)")

    # 每完成一个就保存一次，防止超时丢数据
    summary["executions"] = executions
    out_file = results_dir / latest.name
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n完成: {sum(1 for e in executions if e.get('status')=='ok')}/{len(executions)} 成功")
print(f"已保存: {latest.name}")
