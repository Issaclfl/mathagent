# 修复 LLM 数值求解：让代码真正计算而非"空跑"

## 问题根因（2025A 重跑日志实证）

| 子问题 | 现象 | 根因 |
|--------|------|------|
| Q1 | 遮蔽时长=0，3轮修复后得1.79s | 几何判定条件写反（球-线段距离判定） |
| Q2 | best_obscuration_time=0，修复仍0 | LLM 不知道具体哪里错，盲修 |
| Q3 | total_shielding_time=0，最终"读取文件失败，使用默认数据" | 数据读取失败→用了全0默认值 |
| Q4 | Interference duration=0.00，Is missile interfered: False | 物理模型根本没实现 |

**核心问题**：LLM 生成的代码"能跑"（returncode=0）但没有做有效计算。修复 prompt 只说"结果为0"，LLM 无法定位具体错误。

---

## 修改清单（5 个文件）

### 1. `agents/builder.py` — Builder prompt 增强

**改动点**：

a) **SYSTEM_PROMPT** 增加计算验证要求：
```
你是精通数学建模与Python编程的专家，同时是计算验证专家。
你的代码必须：先验证再优化、先打印中间结果再输出最终值。
```

b) **USER_PROMPT_TEMPLATE** 增加【计算链路铁律】section（在"执行隔离铁律"之后）：
```
【计算链路铁律——必须严格遵守】
你的代码必须包含完整的计算链路，严禁"空跑"（只 print 不 compute）：

1. **已知答案验证**：如果题目给出了部分已知条件（如初始位置、速度），
   代码必须先用这些条件计算一个可手算验证的中间值，并打印出来。
   例：已知导弹位置(20000,0,2000)和速度300m/s → 打印"3秒后导弹位置: ..."

2. **中间结果打印**：关键计算步骤必须 print 中间结果：
   - 坐标变换后的值
   - 距离/角度判定结果
   - 每次迭代的最优值
   - 边界条件检查结果

3. **判定条件验证**：涉及"是否遮蔽/是否覆盖/是否相交"的判定，
   代码必须先用一个已知的"明显遮蔽"和"明显不遮蔽"的案例验证判定函数正确性。
   例：云团中心正好在导弹-目标连线上 → 应判定为遮蔽；
       云团在100km外 → 应判定为不遮蔽。

4. **metrics.json 必须非空**：核心指标必须写入 metrics.json，
   且至少有一个非零数值。如果计算结果确实为0，必须在代码中说明原因。

5. **物理/几何题示意图**：必须生成至少一张示意图（导弹轨迹、云团位置、
   遮蔽区间可视化），用图表直观验证计算结果是否合理。
```

c) **降级重建模 feedback**（`_rebuild_with_fallback` 中的 degrade 文本）增加：
```
新方案必须包含：① 已知条件验证函数 ② 中间结果打印 ③ 判定条件自测。
先确保计算链路正确，再追求最优解。
```

### 2. `agents/solver.py` — 修复 prompt 增强 + 空跑检测

**改动点**：

a) **`_check_result_sanity()` 返回值扩展**：从 `str|None` 改为返回 `dict|None`，增加结构化诊断：

```python
def _check_result_sanity(metrics, stdout) -> dict | None:
    # 现有检查逻辑不变...
    # 返回值改为:
    # {"problem": "zero_value", "detail": "...", "hint": "检查判定条件是否写反"}
    # 或 None（无问题）
```

b) **fix_code() 中 sanity fix prompt 增强**（当前约第671行）：

当前 prompt：
```python
sanity_prompt = f"""以下Python代码执行成功，但输出结果存在物理/逻辑不合理：
问题：{sanity_issue}
请修复代码..."""
```

改为：
```python
sanity_prompt = f"""以下Python代码执行成功，但输出结果存在物理/逻辑不合理：

【问题诊断】
{sanity_detail}  # 包含 problem_type + hint

【代码执行的 stdout（包含中间结果，请据此定位错误）】
{stdout[:1500]}

【修复要求——必须遵守】
1. 先分析 stdout 中的中间结果，定位具体哪一步计算出错
2. 修复判定条件/公式/坐标系（不要重写整个代码，只修改错误部分）
3. 增加已知答案验证：用题目给的初始条件算一个可手算验证的值
4. 增加判定条件自测：用"明显遮蔽"和"明显不遮蔽"案例验证判定函数
5. 确保 metrics.json 中至少有一个非零的核心指标

当前代码：
```python
{current_code}
```"""
```

c) **新增 `_has_real_computation()` 函数**：检测代码是否包含真正计算模式：

```python
def _has_real_computation(code: str) -> bool:
    """检测代码是否包含真正的数值计算（而非空跑）。
    
    空跑特征：只有 print/赋值，没有循环/优化器/数值运算。
    计算特征：for/while 循环、scipy.optimize、numpy 运算、条件判定。
    """
    indicators = [
        "for ", "while ", "scipy", "optimize", "minimize",
        "np.", "numpy", "math.", "sqrt", "sin", "cos",
        "def ", "return ",  # 函数定义+返回值 = 有计算逻辑
    ]
    # 排除只有 print 和赋值的"空跑"
    has_loop_or_optimize = any(ind in code for ind in indicators[:6])
    has_function = "def " in code and "return " in code
    return has_loop_or_optimize or has_function
```

d) **run_code() 中空跑检测增强**（当前约第545行）：

```python
_empty_success = (
    result.returncode == 0
    and not metrics_json and not figures and not _has_numbers
    and not _has_real_computation(original_code)  # 新增：代码本身无计算
)
```

e) **修复 prompt 的 SYSTEM_PROMPT 增强**：

当前：
```python
SYSTEM_PROMPT = """你是一位 Python 调试专家，擅长根据报错信息修复代码。"""
```

改为：
```python
SYSTEM_PROMPT = """你是一位 Python 调试专家，擅长根据报错信息修复代码。
你特别擅长定位数值计算错误：
- 全零结果通常是判定条件写反、坐标系错误或数据读取失败
- 修复时先看 stdout 中的中间结果，定位具体哪一步出错
- 不要重写整个代码，只修改错误部分
- 修复后必须增加已知答案验证步骤"""
```

### 3. `main.py` — 降级策略增强

**改动点**：

a) **`_rebuild_with_fallback()` 的 degrade 指令增强**（约第661行）：

```python
degrade = (
    "【降级重建模——原方案已失败，必须更换算法并修复计算链路】\n"
    f"原算法「{algo}」生成的代码执行失败且自动修复无效。\n"
    "请放弃原算法，改用更简单、可靠的方法。\n\n"
    "【计算链路要求——降级时必须优先保证】\n"
    "1. 先写一个已知答案验证函数（用题目初始条件计算可手算验证的值）\n"
    "2. 判定函数必须用'明显通过'和'明显不通过'的案例自测\n"
    "3. 每步计算必须 print 中间结果\n"
    "4. metrics.json 必须写入至少一个非零核心指标\n"
    "5. 物理/几何题必须画示意图验证\n\n"
    "【上次代码执行报错】\n"
)
```

b) **新增"代码审计"步骤**：当 Agent Loop 修复也失败时，不直接降级重建模，
先让 LLM 分析代码逻辑错误（而非重写）：

```python
def _audit_code(error_text: str, code: str) -> dict:
    """让 LLM 分析代码逻辑错误（不是重写，是诊断）。"""
    audit_prompt = f"""以下Python代码执行后结果全为0，请分析代码逻辑错误：

【执行输出】
{error_text[:1000]}

【代码】
```python
{code[:3000]}
```

请只分析错误原因（不要重写代码），指出：
1. 哪个判定条件/公式可能写反
2. 坐标系/单位是否正确
3. 数据读取是否成功
4. 中间结果打印是否足够定位问题

输出格式：
错误原因: ...
具体位置: ...
修复方向: ..."""
    # 用 LLM 分析，返回分析结果
```

### 4. `utils/experience.py` — 增加计算失败种子教训

**改动点**：在 `SEED_LESSONS` 中增加 3 条教训：

```python
{
    "problem_type": "优化",
    "keywords": ["遮蔽", "遮挡", "相交", "视线", "云团", "覆盖", "判定"],
    "lesson": "涉及'是否遮蔽/覆盖/相交'的判定函数，必须先用已知案例验证："
              "① 明显遮蔽（云团中心在连线上）→ 应返回True；"
              "② 明显不遮蔽（云团在远处）→ 应返回False。"
              "全零结果90%是判定条件写反（如距离<threshold写成>threshold）。",
    "source": "2025A Q1-Q5 实测",
},
{
    "problem_type": "优化",
    "keywords": ["读取", "文件", "数据", "csv", "xlsx", "默认"],
    "lesson": "数据读取失败会静默使用全0默认值，导致结果无意义。"
              "代码必须：① 读取失败时抛异常而非静默降级；"
              "② 打印读取的行数和前3行数据验证；"
              "③ 数据为空时立即报错终止。",
    "source": "2025A Q3 实测",
},
{
    "problem_type": "优化",
    "keywords": ["数值", "计算", "求解", "优化", "结果"],
    "lesson": "metrics.json 必须包含至少一个非零核心指标。"
              "代码执行成功但 metrics.json 为空 = 空跑（只 print 不 compute）。"
              "修复方向：检查是否所有计算都在 if __name__ 块内、"
              "是否被条件分支跳过、是否写入了错误的文件名。",
    "source": "通用",
},
```

### 5. `utils/modeling_kb.py` — 几何题计算模板

**改动点**：在 `structure_redline()` 中，当 `has_analytic=True` 时增加计算模板要求：

```python
if struct.get("has_analytic"):
    lines.append(
        "- 评估函数疑似可解析化（遮蔽/相交/距离类）：优先解析求根"
        "（如球心到线段距离的二次方程）而非离散采样\n"
        "- 【计算模板要求】判定函数必须包含自测：\n"
        "  ① 写一个 check_判定函数()，用已知案例验证\n"
        "  ② 打印每步中间结果（坐标、距离、判定结果）\n"
        "  ③ 生成示意图可视化判定结果"
    )
```

---

## 实施顺序

1. **`utils/experience.py`** — 增加 3 条种子教训（立即生效，无依赖）
2. **`agents/solver.py`** — 增强修复 prompt + 空跑检测 + `_has_real_computation()`
3. **`agents/builder.py`** — 计算链路铁律 + SYSTEM_PROMPT 增强
4. **`main.py`** — 降级策略增强 + 代码审计步骤
5. **`utils/modeling_kb.py`** — 几何题计算模板

## 验证方式

重跑 2025A（`python main.py --problem-file "A题求解/题目.md" --data-dir "A题求解"`）：
- 检查 Sub1-4 的 metrics.json 是否非零
- 检查 stdout 是否有中间结果打印
- 检查修复轮次是否减少（从 3 轮降到 1-2 轮）
- 检查门控分数是否提升（逻辑分从 8.89 提升）
