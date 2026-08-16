"""测试 _is_likely_python 和 _extract_code"""
import sys
sys.path.insert(0, r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
from agents.solver import _is_likely_python, _extract_code

# Test 1: Pure code
code = "import numpy as np\nx = np.array([1,2,3])\nprint(x.mean())"
print("Test 1 (pure code):", _is_likely_python(code))

# Test 2: Explanation text
text = "修复后的代码如下：这段代码使用了随机森林算法来预测需求。"
print("Test 2 (explanation):", _is_likely_python(text))

# Test 3: Mixed
mixed = "以下是修复后的代码：\nimport pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df.head())"
print("Test 3 (mixed):", _is_likely_python(mixed))

# Test 4: extract from markdown
md = "修复完成：\n```python\nimport os\nprint(os.getcwd())\n```\n以上代码..."
print("Test 4 (markdown):", _extract_code(md)[:60])

# Test 5: extract from explanation with code embedded
exp = "修复后的代码：\nimport numpy as np\nx = 1\nprint(x)"
print("Test 5 (explanation):", _extract_code(exp)[:60])
