"""测试指标提取功能"""
import sys
sys.path.insert(0, r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")

from agents.solver import _extract_metrics

test_stdout = """
特征值: [5.83, 3.12, 2.98]
方差贡献率: 0.45, 0.25, 0.18
累计方差贡献率 = 0.88
MAE: 9.8
RMSE: 13.2
站点1 得分: 0.85
站点2 得分: 0.71
| 指标 | 权重 | 重要性 |
| 温度 | 0.35 | 高 |
| 降雨 | 0.28 | 中 |
总成本: 125000
满足率: 0.94
"""

m = _extract_metrics(test_stdout)
print("numbers:", m["numbers"])
print("key_lines:", len(m["key_lines"]), "条")
print("tables:", len(m["tables"]), "行")
for t in m["tables"]:
    print(f"  {t}")
for kl in m["key_lines"]:
    print(f"  {kl}")
