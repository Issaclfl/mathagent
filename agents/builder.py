from __future__ import annotations

import ast
import importlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.base import BaseAgent
from utils.config import get

SYSTEM_PROMPT = """你是一位精通数学建模与Python编程的专家。
你的核心能力是：
1. 根据实际问题抽象出数学公式（变量、目标函数、约束条件）
2. 将数学模型转化为可直接运行的Python代码（使用numpy, scipy, pulp或sklearn）
3. 代码必须包含详细注释，结构清晰，并能在标准环境下运行。
"""

USER_PROMPT_TEMPLATE = """请根据以下赛题和子问题，建立数学模型并生成对应的Python求解代码。

【赛题背景】
{problem_text}

【当前子问题】
{sub_problem}

【推荐使用的算法】
{algorithm}

【真实数据文件（如有，必须使用）】
{data_files}

【数据使用规则——必须遵守】
- 情况1（有数据文件）：必须用 pandas 读取（相对路径），严禁编造数据
- 情况2（无数据文件但题目有数字）：从题目文本提取关键数字（如站点数、容量、价格等），用 Python dict 直接嵌入代码：
  e.g. stations = dict(S1=dict(fast=8,slow=4,capacity=480), ...)
  这是允许的，因为数字来自题目本身
- 情况3（无数据文件且需模拟）：可以用 numpy 生成符合题目描述的模拟数据，但必须在代码注释中说明"模拟数据，基于题目描述生成"
- 严禁任何网络访问（requests、urllib 等禁止）
- 整个程序须在 30 秒内完成，禁止死循环

【前序子问题结果（数据契约——必须遵守）】
- 运行环境中可能存在前序子问题的结果文件 result_1.json、result_2.json 等
  （由系统按求解顺序生成，JSON 字段：sub_problem、metrics_json、numbers、key_lines）
- 若你的模型需要前序子问题的计算结果（如数量优化得到的装卸量/理想库存、预处理结果），
  **必须从对应 result_N.json 读取**（相对路径），并在代码中打印所读取的关键值
- **严禁自行重算或硬编码前序子问题的结果**——否则会造成子问题间数据不一致，
  论文将因"数值不自洽"被质量门控拦截

【建模要求】
1. 明确定义决策变量（符号含义、取值范围）
2. 清晰写出目标函数（最大化/最小化）
3. 列出所有约束条件
4. 生成完整的Python代码，代码必须包含：
   - 必要的库导入（import）
   - 数据输入（真实数据文件或用户输入，严禁模拟数据）
   - 模型构建与求解
   - **可视化图表**：用 matplotlib 生成至少 2-3 张关键结果图表，保存为 PNG 文件
     - 如：预测曲线图、敏感性分析图、ROC曲线、热力图等
     - 图表用 plt.savefig('figure_N.png', dpi=150, bbox_inches='tight') 保存
     - 同时在 metrics.json 中记录生成的图表路径
   - 结果输出（print关键结果）

【数值合理性要求——必须严格遵守】
- 代码运行结果必须物理/逻辑合理：误差/MAE/RMSE 不能为负，误差百分比不应超过100%，
  概率、覆盖率、满足率等应在[0,100]区间
- 单位必须正确（如厚度用 μm 或 cm 需换算清楚，折射率无量纲）
- 拟合/优化后必须输出误差指标（MSE、R²或相对误差），便于检验结果质量
- 如果结果可能不合理，在代码中加入 sanity check（断言或 if 判断），异常时打印警告

【执行隔离铁律——必须严格遵守】
- 你【严禁】在回答中给出任何运行结果、RMSE/MAE 数值、图表结论或"预期输出"
- 你【严禁】伪造或臆测任何计算结果，哪怕看似"合理"
- 代码必须包含 `if __name__ == "__main__":` 入口
- 代码必须将所有核心指标（如 RMSE、MAE、R²、最优值等）以 JSON 形式
  写入同目录下的 `metrics.json` 文件（键值对形式，如 {{"RMSE": 0.138, "MAE": 0.091}}）
- 所有指标**只能来自真实代码运行**，由求解者执行后回读，你无权填写

【输出格式】
请严格按以下结构返回（不要额外解释）：
---
## 数学模型
（用LaTeX或清晰文字描述变量、目标、约束）

## Python代码
```python
# 你的完整代码
```
"""


def list_data_files(data_dir: str | Path | None = None) -> str:
    """列出可用数据文件（相对项目根路径），供提示词数据契约使用。

    data_dir 给定时**只列当前赛题数据目录**的文件——防止 LLM 读取其它赛题
    的数据（实测：共享单车题代码读到了 bike_data.csv 并尝试使用）。
    无数据文件时返回空字符串。
    """
    root = (Path(__file__).resolve().parent.parent / "data").resolve()
    base = (Path(data_dir) if data_dir else root).resolve()
    if not base.exists():
        return ""
    # 只列当前数据目录顶层（约定：赛题数据与附件在数据目录根）。
    # 不递归——否则会列出其它赛题子目录的数据（跨赛题污染）。
    files = sorted(
        p.relative_to(root.parent) for p in base.glob("*")
        if p.is_file() and p.suffix.lower() in (".csv", ".xlsx", ".txt")
        and not any(kw in p.stem.lower() for kw in ("problem", "test"))
        and not any(kw in p.stem for kw in ("厚度计算结果", "验证"))
    )
    if not files:
        return ""
    return "\n".join(f"- {f.as_posix()}" for f in files)


def _safe_format(text: str) -> str:
    """转义文本中的花括号，防止 .format() 崩溃（赛题常含 LaTeX {} 等）。"""
    return (text or "").replace("{", "{{").replace("}", "}}")


def _parse_build_result(text: str) -> tuple[str, str]:
    """从 LLM 输出中提取数学模型和代码。"""
    math_model = ""
    code = ""

    math_match = re.search(
        r"#{1,3}\s*数学模型\s*(.*?)(?:#{1,3}\s*Python代码|```python)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if math_match:
        math_model = math_match.group(1).strip()

    code_match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if code_match:
        code = code_match.group(1).strip()
    else:
        code_match = re.search(r"~~~python\s*(.*?)~~~", text, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
        else:
            code_match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
            if code_match:
                code = code_match.group(1).strip()
            else:
                code_match = re.search(r"~~~\s*(.*?)~~~", text, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()

    if not code and not math_model:
        code = text.strip()

    return math_model, code


IRON_LOCK = 'assert False, "IRON_LOCK: 禁止直接运行，请等待Solver沙箱调用"'


def inject_iron_lock(code: str) -> str:
    """铁律：在代码第一行注入断言锁，使代码无法被直接运行。

    LLM 生成的代码永远是"死的"——任何直接运行都会触发 AssertionError，
    只有 Solver 执行前会剥掉这行。这从物理上切断了 AI 编造运行结果的通道。
    """
    code = code.strip()
    if "IRON_LOCK" in code:
        return code
    return IRON_LOCK + "\n" + code


def remove_iron_lock(code: str) -> str:
    """Solver 专属：移除铁律断言锁，代码才可执行。

    只删行首精确匹配的锁行，避免误删注释/说明中提到 IRON_LOCK 的合法内容。
    """
    lock_prefixes = (
        'assert False, "IRON_LOCK',
        "assert False, 'IRON_LOCK",
        'assert False, "禁止直接运行',
    )
    out = [l for l in code.splitlines() if not l.strip().startswith(lock_prefixes)]
    return "\n".join(out).strip()


def validate_code(code: str) -> tuple[bool, str]:
    """验证Python代码语法和安全性。"""
    if not code.strip():
        return False, "代码为空"

    # 1. 语法检查
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误(第{e.lineno}行): {e.msg}"

    # 2. 安全检查：禁止危险导入和函数调用
    # 注: os 允许导入（数据题常需 os.path 拼路径），但危险属性被下方 DANGEROUS_ATTRS 拦截
    DANGEROUS_IMPORTS = {"subprocess", "shutil", "socket", "importlib"}
    DANGEROUS_CALLS = {
        "eval", "exec", "__import__",
        "import_module", "breakpoint",
    }
    DANGEROUS_ATTRS = {
        "system", "popen", "spawn",
        # os 写操作/删除（mkdir/makedirs 放行：生成代码常用其创建输出目录；
        # replace 放行：str.replace/DataFrame.replace 是常用方法，
        # 与 os.replace 同名但 AST 无法区分，沙箱内替换自己文件风险低）
        "remove", "unlink", "rmdir", "chmod", "chown",
        "symlink", "link",
        # dunder 逃逸链：() -> __class__ -> __bases__ -> __subclasses__ -> Popen
        "__class__", "__bases__", "__subclasses__", "__mro__",
        "__globals__", "__builtins__", "__getattribute__", "__getattr__",
    }

    WRITE_MODES = {"w", "a", "x", "wb", "ab", "xb", "w+", "a+", "x+"}

    for node in ast.walk(tree):
        # 检查直接访问 __builtins__ 变量（绕过属性黑名单）
        if isinstance(node, ast.Name) and node.id == "__builtins__":
            return False, "禁止访问变量: __builtins__"

        # 检查 open()：允许写结果文件（metrics.json/csv/txt），禁止写代码/系统路径。
        # 注意：文件名是变量（非常量）时放行——Solver 在隔离临时目录执行，
        # 写相对文件无系统风险；硬编码绝对路径/非结果后缀才拦截。
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = "r"
            fname = ""
            is_const = node.args and isinstance(node.args[0], ast.Constant)
            if is_const:
                fname = str(node.args[0].value)
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            if mode in WRITE_MODES:
                if not is_const:
                    # 变量文件名：放行（沙箱内隔离执行）
                    pass
                elif (
                    fname.endswith((".json", ".csv", ".txt", ".xlsx"))
                    and "/" not in fname and "\\" not in fname and ":" not in fname
                    and not fname.startswith(".")
                ):
                    # 结果类文件：允许
                    pass
                else:
                    return False, f"禁止写非结果文件 (mode='{mode}', file='{fname}')"

        # 检查危险导入
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in DANGEROUS_IMPORTS:
                    return False, f"禁止导入危险模块: {alias.name}"

        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in DANGEROUS_IMPORTS:
                return False, f"禁止导入危险模块: {node.module}"

        # 检查危险函数调用
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in DANGEROUS_CALLS:
                return False, f"禁止调用危险函数: {func_name}()"

        # 检查危险属性访问
        if isinstance(node, ast.Attribute):
            if node.attr in DANGEROUS_ATTRS:
                return False, f"禁止访问危险属性: .{node.attr}"

    return True, ""


def check_dependencies(code: str) -> list[str]:
    """检查代码依赖的库是否已安装。"""
    missing = []
    try:
        tree = ast.parse(code)
        imports = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])

        for imp in imports:
            try:
                spec = importlib.util.find_spec(imp)
                if spec is None:
                    missing.append(imp)
            except (ImportError, AttributeError, ModuleNotFoundError, ValueError):
                missing.append(imp)
    except SyntaxError:
        pass

    return missing


class BuilderAgent(BaseAgent):
    """建模构建智能体：将算法转化为数学模型和可执行代码。"""

    def __init__(self) -> None:
        super().__init__(role="数学建模代码生成专家")

    def run(
        self,
        problem_text: str,
        sub_problem: str,
        algorithm: str,
        feedback: str | None = None,
        data_dir: str | Path | None = None,
        gate_decisions: str = "",
        structure_hints: str = "",
    ) -> dict:
        """为单个子问题建立模型并生成代码。

        Args:
            problem_text: 完整赛题
            sub_problem: 当前处理的子问题原文
            algorithm: 建模者推荐的算法名称
            feedback: 可选，上次代码执行的报错信息（由 Solver 回传），
                      用于指导重新建模/修正代码。
            data_dir: 当前赛题数据目录（数据清单只列该目录，防跨赛题读取）。
            gate_decisions: 人工策略决定文本（来自策略门控），注入提示词必须遵守。
            structure_hints: 问题结构诊断红线（维度/组合/可解析化），
                      建模与代码必须遵守（防默认走网格搜索等次优方向）。
        """
        if not sub_problem or not algorithm or algorithm == "未确定":
            return {
                "status": "error",
                "sub_problem": sub_problem,
                "algorithm": algorithm,
                "math_model": "",
                "code": "",
                "error": "子问题或算法缺失，无法建模",
            }

        temperature = get("builder.temperature", 0.2)

        prompt = USER_PROMPT_TEMPLATE.format(
            problem_text=_safe_format(problem_text),
            sub_problem=_safe_format(sub_problem),
            algorithm=_safe_format(algorithm),
            data_files=_safe_format(list_data_files(data_dir)) or "（无）",
        )
        if structure_hints:
            prompt += "\n\n" + _safe_format(structure_hints)
        if gate_decisions:
            prompt += "\n\n" + _safe_format(gate_decisions)
        if feedback:
            prompt += (
                "\n\n"
                "【上次代码执行报错——请务必据此修正数学模型与代码，"
                "不要再犯同样的错误】\n"
                f"{feedback[:2000]}"
            )
        result = self.think(prompt, system_prompt=SYSTEM_PROMPT, temperature=temperature)

        if not result:
            return {
                "status": "error",
                "sub_problem": sub_problem,
                "algorithm": algorithm,
                "math_model": "",
                "code": "",
                "error": "LLM未返回结果",
            }

        math_model, code = _parse_build_result(result)

        # 铁律：注入断言锁，使生成的代码无法被直接运行（只有 Solver 沙箱可解锁执行）
        code = inject_iron_lock(code)

        # ── 语法验证 + 自动重试（最多2次）──
        # LLM 偶发生成缩进错误/括号不匹配的代码，直接返回 warning 会导致
        # Solver 端 fix_code 也无法修复（因为语法错误在执行前就被拦截）。
        # 在 Builder 端重试，让 LLM 有机会自行修正。
        is_valid, error_msg = validate_code(code)
        max_build_retries = 2
        build_attempt = 0
        while not is_valid and build_attempt < max_build_retries:
            build_attempt += 1
            self.logger.warning(
                f"代码语法错误(第{build_attempt}次重试): {error_msg}"
            )
            retry_prompt = (
                f"你上次生成的代码有语法错误，请修正后重新输出完整代码。\n"
                f"错误信息: {error_msg}\n\n"
                f"原始子问题: {sub_problem[:500]}\n"
                f"推荐算法: {algorithm}\n"
                f"请严格按格式返回修正后的数学模型和Python代码。"
            )
            retry_result = self.think(
                retry_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.1
            )
            if retry_result:
                _, retry_code = _parse_build_result(retry_result)
                retry_code = inject_iron_lock(retry_code)
                is_valid, error_msg = validate_code(retry_code)
                if is_valid:
                    code = retry_code
                    math_model_retry, _ = _parse_build_result(retry_result)
                    if math_model_retry:
                        math_model = math_model_retry
                    self.logger.info(f"第{build_attempt}次重试成功")
                    break
        if not is_valid:
            self.logger.warning(f"代码验证失败(重试{build_attempt}次): {error_msg}")

        # 依赖检查
        missing_deps = check_dependencies(code)
        if missing_deps:
            self.logger.warning(f"缺少依赖库: {missing_deps}")

        self.update_state(
            f"model_{sub_problem[:10]}",
            {"algorithm": algorithm, "math_model": math_model, "code": code},
        )
        self.logger.info(
            f"子问题「{sub_problem[:20]}...」建模完成，代码行数：{len(code.splitlines())}"
        )

        return {
            "status": "ok" if is_valid else "warning",
            "sub_problem": sub_problem,
            "algorithm": algorithm,
            "math_model": math_model,
            "code": code,
            "error": error_msg if not is_valid else None,
            "missing_deps": missing_deps if missing_deps else None,
        }

    def run_batch(
        self,
        problem_text: str,
        sub_problems: list[str],
        algorithm_map: dict,
        max_workers: int = 4,
        data_dir: str | Path | None = None,
        gate_decisions: str = "",
        diagnostics: dict | None = None,
    ) -> list[dict]:
        """批量构建多个子问题的模型（并行，保持返回顺序与输入一致）。

        diagnostics: {子问题: 结构诊断} → 每个子问题生成建模红线注入 prompt。
        """
        def _hints(sp: str) -> str:
            if not diagnostics:
                return ""
            from utils.modeling_kb import structure_redline
            struct = diagnostics.get(sp)
            if not struct:
                return ""
            red = structure_redline(struct)
            return red or ""

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    self.run, problem_text, sp, algorithm_map.get(sp, "未确定"),
                    None, data_dir, gate_decisions, _hints(sp),
                )
                for sp in sub_problems
            ]
            results = [f.result() for f in futures]
        return results


# ── 单例 + 兼容函数接口 ──────────────────────────────────────

_instance: BuilderAgent | None = None


def builder(problem_text: str, sub_problem: str, algorithm: str) -> dict:
    """兼容旧的函数调用方式，使用单例避免重复实例化。"""
    global _instance
    if _instance is None:
        _instance = BuilderAgent()
    return _instance.run(problem_text, sub_problem, algorithm)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    agent = BuilderAgent()
    result = agent.run(
        problem_text="城市共享单车投放优化问题",
        sub_problem="确定校园内共享单车的投放数量",
        algorithm="线性规划",
    )
    print(f"状态：{result['status']}")
    print(f"数学模型：\n{result['math_model'][:200]}...")
    print(f"代码预览：\n{result['code'][:300]}...")
    if result["error"]:
        print(f"错误：{result['error']}")
