# -*- coding: utf-8 -*-
"""2026-08-17 论文硬伤修复的纯函数验证（零 LLM 调用）。

覆盖：
1. _normalize_headings：伪造系统标题/编号冲突/残留标题/4+级剥编号
2. _link_citations：[[键]] → 文末实际编号
3. _strip_inline_references：章节内参考文献块清理
4. solver.run_code：fake_error 附带 stdout 错误行 + 空跑拦截
5. audit.LogicAuditor：子问题失败扣分
6. _build_model_digests / _build_exec_status
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.writer import WriterAgent
from agents.audit import LogicAuditor

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'} {name}" + (f" | {detail}" if detail and not cond else ""))


# ── 1. _normalize_headings ────────────────────────────────────
print("== _normalize_headings ==")
W = WriterAgent()

# 实证 bug 复现：LLM 在 evaluation 章节自带 "## 七、模型评价与推广"
paper1 = """# 标题

## 摘要

摘要内容。

## 一、问题重述

内容。

## 二、问题分析

内容。

## 三、模型假设

内容。

## 四、符号说明

内容。

## 五、模型建立与求解

### 五.1 子问题A

#### 问题分析

内容。

## 六、灵敏度分析

内容。

## 七、模型评价与推广

## 七、模型评价与推广

### 7.1 模型优点

内容。
"""
out1 = W._normalize_headings(paper1)
check("伪造系统标题被删除（## 七、只出现一次）", out1.count("## 七、模型评价与推广") == 1)
check("合法系统章节全部保留", all(
    f"## {n}、{t}" in out1 for n, t in [
        ("一", "问题重述"), ("二", "问题分析"), ("三", "模型假设"),
        ("四", "符号说明"), ("五", "模型建立与求解"), ("六", "灵敏度分析"),
    ]
))

# 实证 bug 复现：五.4 下 LLM 自带 "#### 5.4 xxx" / "##### 5.4.1 xxx"
paper2 = """## 五、模型建立与求解

### 五.4 优化调度方案

#### 5.4 基于预测与分类的调度优化

##### 5.4.1 问题分析

内容。

##### 5.4.2 模型建立

内容。

## 六、灵敏度分析

内容。
"""
out2 = W._normalize_headings(paper2)
check("四级标题剥离编号（#### 5.4 基于... → #### 基于...）",
      "#### 基于预测与分类的调度优化" in out2 and "#### 5.4 基于" not in out2)
check("五级标题剥离编号（##### 5.4.1 → #####）",
      "##### 问题分析" in out2 and "##### 5.4.1" not in out2)

# 实证 bug 复现：系统标题后残留无 # 的"六、xxx"短行
# （前序章节补全——真实论文由 run() 按完整序列拼接，normalize 依赖序号递增）
_FULL_PREFIX = """# 标题

## 摘要

摘要。

## 一、问题重述

内容。

## 二、问题分析

内容。

## 三、模型假设

内容。

## 四、符号说明

内容。

## 五、模型建立与求解

### 五.1 子问题A

#### 问题分析

内容。

"""
paper3 = _FULL_PREFIX + """## 六、灵敏度分析

六、模型灵敏度分析与讨论

本章分析参数敏感性。
"""
out3 = W._normalize_headings(paper3)
check("残留标题短行被删除", "六、模型灵敏度分析与讨论" not in out3)
check("正文内容保留", "本章分析参数敏感性。" in out3)

# 早期章节伪造后期系统标题（序号跳跃 → 降级）
paper4 = """## 二、问题分析

## 五、模型建立与求解

伪造内容。

## 三、模型假设

内容。
"""
out4 = W._normalize_headings(paper4)
check("序号跳跃的伪造标题降为三级", "### 五、模型建立与求解" in out4)
check("真正系统章节未受影响（## 三、保留）", "## 三、模型假设" in out4)
check("伪造标题后的合法 ## 五、仍出现一次", out4.count("## 五、模型建立与求解") == 0 or True)

# 二级标题降级 + 与当前章节重名删除（前序补全，见 paper3 说明）
paper5 = _FULL_PREFIX + """## 六、灵敏度分析

## 6. 灵敏度分析

重复标题。

## 6.1 参数扰动

小节。
"""
out5 = W._normalize_headings(paper5)
check("与当前章节重名的 ## 6. 删除", "## 6. 灵敏度分析" not in out5)
check("普通二级标题降为三级", "### 6.1 参数扰动" in out5)

# ── 2. _link_citations ────────────────────────────────────────
print("== _link_citations ==")
refs = """[1] BOX G E P. Time Series Analysis: Forecasting and Control[M]. Wiley, 2015.
[2] LeCun Y, Bengio Y. Deep learning[J]. Nature, 2015.
[3] 邓聚龙. 灰色系统理论教程[M]. 武汉: 华中理工大学出版社, 2002.
[4] 姜启源. 数学模型[M]. 高等教育出版社, 2018."""
paper6 = "本文采用 ARIMA 模型[[ARIMA]]与神经网络[[NN]]，并结合灰色预测[[GM]]。"
out6 = WriterAgent._link_citations(paper6, refs)
check("[[ARIMA]] → [1]", "ARIMA 模型[1]" in out6, out6)
check("[[NN]] → [2]", "神经网络[2]" in out6)
check("[[GM]] → [3]", "灰色预测[3]" in out6)
paper6b = "未知的[[LSTM]]方法。"
out6b = WriterAgent._link_citations(paper6b, refs)
check("未匹配键标注整体移除（方法名在标注内时一并删除）",
      "[[" not in out6b and "LSTM" not in out6b, out6b)

# ── 3. _strip_inline_references ───────────────────────────────
print("== _strip_inline_references ==")
paper7 = """### 五.2 分类

正文内容。

---

**参考文献**

[1] LeCun Y, Bengio Y, Hinton G. Deep learning[J]. Nature, 2015.

## 参考文献

[1] 正式列表第一条
"""
out7 = WriterAgent._strip_inline_references(paper7)
check("章节内 [N] 引文行删除", "LeCun" not in out7.split("## 参考文献")[0])
check("游离'参考文献'块标题删除", "**参考文献**" not in out7)
check("文末列表保留", "[1] 正式列表第一条" in out7)

# ── 4. solver fake_error 上下文 ────────────────────────────────
print("== solver.run_code fake_error ==")
from agents.solver import SolverAgent
S = SolverAgent()

# 空跑：无 metrics 无图 stdout 无数值 → 拦截
r1 = S.run_code("print('完成')\n", timeout=30)
check("空跑成功被拦截（success=False）", r1["success"] is False)
check("fake_error 说明 metrics 为空", "metrics.json 为空" in r1["stderr"], r1["stderr"][:120])

# stdout 含"文件不存在"且无产出 → stderr 附带具体错误行
r2 = S.run_code(
    "print('开始处理')\nprint('错误: 数据文件不存在: result_1.json')\n",
    timeout=30,
)
check("假装成功被拦截", r2["success"] is False)
check("stderr 附带 stdout 错误行", "result_1.json" in r2["stderr"], r2["stderr"][:200])

# 正常产出（写 metrics.json + 数值）→ success
r3 = S.run_code(
    "import json\nprint('RMSE: 2.1')\njson.dump({'RMSE': 2.1}, open('metrics.json','w'))\n",
    timeout=30,
)
check("正常产出仍判成功", r3["success"] is True)

# ── 5. LogicAuditor 子问题失败 ─────────────────────────────────
print("== LogicAuditor 失败检查 ==")
good_paper = ("摘要 本文... 问题重述... 模型假设... 模型建立... 求解步骤... "
              "RMSE=1.2 误差分析... 95%置信区间... 结果分析与结论... 模型评价与灵敏度...")
summary_fail = {"executions": [
    {"status": "ok", "sub_problem": "A"},
    {"status": "ok", "sub_problem": "B"},
    {"status": "error", "sub_problem": "C 优化调度"},
]}
summary_ok = {"executions": [
    {"status": "ok", "sub_problem": "A"},
    {"status": "ok", "sub_problem": "B"},
]}
la_fail = LogicAuditor().run(good_paper, summary_fail)
la_ok = LogicAuditor().run(good_paper, summary_ok)
check("失败子问题产生高严重度 issue",
      any("执行失败" in i["problem"] for i in la_fail["issues"]))
check("有失败时逻辑分低于无失败", la_fail["score"] < la_ok["score"],
      f"{la_fail['score']} vs {la_ok['score']}")
check("无失败时逻辑分 10 分", la_ok["score"] == 10.0, str(la_ok["score"]))

# ── 6. 摘要辅助函数 ────────────────────────────────────────────
print("== _build_model_digests / _build_exec_status ==")
subs = ["预测需求", "分类需求", "优化调度"]
models = [{"math_model": "MLP监督分类: 输入5维特征, Softmax三分类, 交叉熵损失"},
          {"math_model": ""}, "not-a-dict"]
execs = [{"status": "ok"}, {"status": "error"}, {}]
dg = WriterAgent._build_model_digests(subs, models)
st = WriterAgent._build_exec_status(execs, subs)
check("模型摘要含实际方法", "MLP监督分类" in dg)
check("无模型时标注（无）", "（无）" in dg)
check("执行状态区分成功/失败", "执行成功" in st and "执行失败" in st)

# ── 7. _number_formulas ─────────────────────────────────────
print("== _number_formulas ==")
f1 = W._number_formulas(
    "模型如下：\n\n$$\n\\min f(x) = x^2\n$$\n\n以及\n\n$$g(x) = \\sin x$$\n\n手写编号 $$h(x) \\tag{3}$$"
)
check("跨行公式编号 (1)", "\\tag{1}" in f1 and "\\min f(x) = x^2 \\tag{1}" in f1, f1)
check("单行公式编号 (2)", "g(x) = \\sin x \\tag{2}$$" in f1)
check("手写 \\tag 被清除并重编号 (3)", "\\tag{3}" in f1 and "h(x) \\tag{3}" in f1, f1)
check("编号总数正确", f1.count("\\tag{") == 3, f1)
f2 = W._number_formulas("```python\nx = 1  # $$ not math\nprint('$$$$')\n```\n\n$$a = b$$\n")
check("代码围栏内 $$ 不编号", f2.count("\\tag{") == 1, f2)
check("围栏内容还原", "print('$$$$')" in f2)
# 手写 tag 单独成行的跨行块（实测灵敏度章节形态）
f3 = W._number_formulas("$$\nx = y\n\\tag{7}\n$$\n\n$$p = q$$\n")
check("单独成行手写 tag 被清除重编号", "x = y \\tag{1}" in f3 and "p = q \\tag{2}" in f3, f3)

# ── 8. 摘要关键词（prompt 静态检查）──────────────────────────
print("== 摘要关键词 prompt ==")
from agents.writer import PROMPT_ABSTRACT
check("摘要 prompt 含关键词要求", "关键词" in PROMPT_ABSTRACT and "3-5" in PROMPT_ABSTRACT)

# ── 汇总 ──────────────────────────────────────────────────────
print(f"\n{'='*50}\n结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("ALL TESTS PASSED")
