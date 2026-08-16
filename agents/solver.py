from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from agents.base import BaseAgent
from agents.builder import validate_code, check_dependencies
from utils.config import get

SYSTEM_PROMPT = """你是一位 Python 调试专家，擅长根据报错信息修复代码。
你会收到一段代码和运行时的报错信息，请分析错误原因并返回修正后的完整代码。
只返回修正后的代码，不要额外解释。
"""


def _is_likely_python(text: str) -> bool:
    """启发式判断文本是否像 Python 代码。"""
    indicators = [
        "import ", "def ", "class ", "for ", "while ", "if ",
        "print(", "return ", "= ", "elif ", "else:",
        "try:", "except:", "with ", "lambda ",
    ]
    score = sum(1 for ind in indicators if ind in text)
    # 至少包含 2 个 Python 特征，且不含大段中文解释
    chinese_ratio = len(re.findall(r"[\u4e00-\u9fff]", text)) / max(len(text), 1)
    return score >= 2 and chinese_ratio < 0.3


def _sanitize_code(code: str) -> str:
    """清洗代码中的控制字符（LLM 输出偶发混入 NUL 字节，ast 解析会报
    'source code string cannot contain null bytes'）。"""
    return code.replace("\x00", "")


# 代码执行临时目录：项目内 data/tmp_exec/（不用系统 %TEMP%，
# 受限环境下 %TEMP% 可能只读导致 solution.py 写不进去）
EXEC_TMP_ROOT = Path(__file__).parent.parent / "data" / "tmp_exec"


def _make_exec_tmp_dir() -> Path:
    """创建本次执行的独立临时子目录（项目内，执行后由调用方清理）。

    注意：不用 tempfile.mkdtemp()——沙箱/受限环境下 mkdtemp 创建的
    子目录可能带特殊属性导致写入被拒（实测 Permission denied），
    而手工 mkdir 的目录可正常写入。
    """
    EXEC_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    sub = EXEC_TMP_ROOT / f"exec_{uuid.uuid4().hex[:12]}"
    sub.mkdir(parents=True, exist_ok=True)
    return sub


def cleanup_exec_tmp(keep: int = 0) -> None:
    """清理临时执行目录，防止堆积（keep=0 全部清空，默认全清）。

    Solver 执行完的 finally 已删除当前目录；这里兜底清理崩溃残留。
    """
    try:
        if not EXEC_TMP_ROOT.exists():
            return
        dirs = sorted(
            (d for d in EXEC_TMP_ROOT.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for d in dirs[keep:]:
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


# 数据路径归一化正则（两类）：
# 1. 绝对路径：盘符/根路径开头，锚定 data/ 目录 → data/文件名
# 2. 任务目录段：data/task_xxx/文件名 → data/文件名（LLM 偶发把任务 ID 目录拼进路径）
_PATH_NORM_RE = re.compile(
    r"""(['"])                     # 捕获引号（单或双）
        (?:[A-Za-z]:[\\/]|/)       # 盘符+斜杠 或 Unix 根斜杠（绝对路径标志）
        .*                         # 中间任意路径（贪婪，锚定最后一个 data/）
        [\\/]data[\\/]             # 关键锚点：data/ 目录
        ([^'"\\]+)                 # 捕获文件名（不含路径分隔符和引号）
        \1                         # 匹配开引号
    """,
    re.VERBOSE,
)
# data/task_xxx/文件名 → data/文件名（task_ 开头段是系统任务目录，沙箱里不存在）
_TASK_SEG_RE = re.compile(
    r"""(['"])(data[\\/])          # 引号 + data/
        (?:task_[^'"\\/]+[\\/])    # task_xxx/ 段（可多个）
        ([^'"\\]+)\1               # 文件名 + 匹配开引号
    """,
    re.VERBOSE,
)


# 变量拼接（os.path.join / Path 构造）中的任务目录段：
#   os.path.join('data', 'task_xxx', '附件.xlsx') → os.path.join('data', '附件.xlsx')
#   os.path.join('data', 'task_1', 'task_2', 'a.csv') → os.path.join('data', 'a.csv')
_JOIN_TASK_SEG_RE = re.compile(
    r"""(os\.path\.join\(|Path\()        # join/Path 开头
        (["']data["']\s*,\s*)            # 'data', 参数
        (?:["']task_[^"']+["']\s*,\s*)+  # 'task_xxx', 参数（一层或多层）
        (["'][^"']+["'])                 # 文件名参数
    """,
    re.VERBOSE,
)
# Path 运算符拼接：Path('data') / 'task_xxx' / 'a.csv' → Path('data') / 'a.csv'
#   Path('data') / 'task_1' / 'task_2' / 'a.csv' → Path('data') / 'a.csv'
_PATH_OP_TASK_SEG_RE = re.compile(
    r"""(Path\(["']data["']\)\s*/\s*)    # Path('data') / 前缀
        (?:["']task_[^"']+["']\s*/\s*)+  # 'task_xxx' / 段（一层或多层）
        (["'][^"']+["'])                 # 文件名段
    """,
    re.VERBOSE,
)


def _normalize_data_paths(code: str) -> str:
    """把代码中的异常数据路径归一化为相对路径 data/文件名。

    LLM 生成代码时偶发硬编码两类错误路径：
    - 绝对路径："C:\\tmp\\sandbox\\data\\附件.xlsx" 或 /home/user/data/train.csv
    - 任务目录段：'data/task_xxx/附件.xlsx'（任务 ID 目录，沙箱里不存在）
    以及 os.path.join('data', 'task_xxx', f) 变量拼接形式。
    归一化后代码可在任意沙箱环境运行。
    注：正则只处理"引号内字面量路径"，动态变量拼接（f-string 变量、open(var)）
    无法静态识别，属已知限制（LLM 极少这样写数据路径）。
    """
    code = _PATH_NORM_RE.sub(r"\1data/\2\1", code)
    code = _TASK_SEG_RE.sub(r"\1\2\3\1", code)
    code = _JOIN_TASK_SEG_RE.sub(r"\1\2\3", code)
    code = _PATH_OP_TASK_SEG_RE.sub(r"\1\2", code)
    return code


def _extract_code(text: str) -> str:
    """从 LLM 输出中提取 Python 代码，带回退保护。"""
    # 1. 尝试 Markdown 代码块
    code_match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if code_match:
        return _sanitize_code(code_match.group(1)).strip()
    code_match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if code_match:
        return _sanitize_code(code_match.group(1)).strip()

    # 2. 尝试找到代码起始行（以 Python 关键字开头的行）
    lines = text.splitlines()
    code_start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ", "def ", "class ")):
            code_start = i
            break

    if code_start >= 0:
        code_block = "\n".join(lines[code_start:])
        if _is_likely_python(code_block):
            return _sanitize_code(code_block).strip()

    # 3. 整段文本是否像代码
    stripped = text.strip()
    if _is_likely_python(stripped):
        return _sanitize_code(stripped)

    # 4. 兜底：返回原文
    return _sanitize_code(stripped)


def _code_hash(code: str) -> str:
    """计算代码哈希，用于检测重复修复。"""
    return hashlib.md5(code.encode()).hexdigest()


def _truncate_stderr(text: str, max_len: int = 500) -> str:
    """智能截断错误信息：保留开头和结尾关键内容。"""
    if len(text) <= max_len:
        return text
    head = max_len * 2 // 3
    tail = max_len - head
    return text[:head] + "\n... [中间省略] ...\n" + text[-tail:]


def _extract_metrics(stdout: str) -> dict:
    """从代码 stdout 中提取结构化关键指标。

    提取规则：
    1. 表格行（含 | 分隔符）→ tables
    2. 含关键词的行（特征值、得分、预测、误差等）→ key_lines
    3. 数值对（标签: 数值）→ numbers
    """
    metrics: dict = {"tables": [], "key_lines": [], "numbers": {}}

    if not stdout:
        return metrics

    lines = stdout.strip().splitlines()

    # 关键词模式
    keyword_pattern = re.compile(
        r"(特征值|方差贡献|累计|得分|预测|误差|MAE|RMSE|成本|score|accuracy|"
        r"precision|recall|f1|objective|最优|最佳|总成本|满足率|覆盖率|"
        r"特征重要|importance|系数|coefficient|p-value|显著|置信区间|"
        r"站点|区域|迭代|generation|fitness|适应度)",
        re.IGNORECASE,
    )

    # 数值对模式：标签: 数值 或 标签=数值
    number_pattern = re.compile(
        r"([\w\u4e00-\u9fff()/]+)\s*[:=]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)"
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 提取表格行
        if "|" in stripped and stripped.count("|") >= 3:
            metrics["tables"].append(stripped)
            continue

        # 提取含关键词的行
        if keyword_pattern.search(stripped):
            metrics["key_lines"].append(stripped[:300])
            # 同时提取该行中的数值对（同名标签存为列表）
            for label, value in number_pattern.findall(stripped):
                try:
                    num = float(value)
                    if label not in metrics["numbers"]:
                        metrics["numbers"][label] = []
                    metrics["numbers"][label].append(num)
                except ValueError:
                    pass

    # 限制大小，数值列表只保留最多5个值
    metrics["tables"] = metrics["tables"][:20]
    metrics["key_lines"] = metrics["key_lines"][:30]
    for k in metrics["numbers"]:
        metrics["numbers"][k] = metrics["numbers"][k][:5]

    return metrics


def _check_result_sanity(metrics: dict, stdout: str) -> str | None:
    """检查执行结果是否物理/逻辑上合理。

    检测"代码能跑但结果错误"的情况（如误差>100%、负值不合理、量级异常），
    这类问题无法通过报错捕获，但会直接导致论文数值不可信。

    Returns:
        发现问题时返回描述字符串，否则返回 None。
    """
    problems: list[str] = []

    # 1. 误差/分数类指标不应为负
    numbers = metrics.get("numbers", {})
    for key, values in numbers.items():
        for v in values:
            if key in ("MAE", "RMSE", "accuracy", "precision", "recall", "f1",
                       "覆盖率", "满足率", "得分", "score"):
                if v < 0:
                    problems.append(f"{key}={v} 为负值，不合理")

    # 2. 相对误差/百分比过大（>50%）视为拟合失败
    for key, values in numbers.items():
        if any(k in key for k in ("误差", "error", "err")):
            for v in values:
                if v > 50:
                    problems.append(f"{key}={v} 误差过大（>50%），疑似拟合失败")

    # 3. 概率/比率类指标应落在 [0,1] 或 [0,100]
    for key, values in numbers.items():
        if any(k in key for k in ("概率", "率", "ratio", "probability", "满足率",
                                  "覆盖率", "准确率")):
            for v in values:
                if v < 0 or v > 100:
                    problems.append(f"{key}={v} 超出合理范围[0,100]")

    if problems:
        return "；".join(problems[:5])
    return None


class SolverAgent(BaseAgent):
    """代码执行与调试智能体：运行代码、捕获报错、自动修正。"""

    def __init__(self) -> None:
        super().__init__(role="代码执行与调试专家")

    def run_code(
        self,
        code: str,
        timeout: int | None = None,
        extra_files: dict[str, str] | None = None,
        figure_dir: str | Path | None = None,
        task_dir: str | Path | None = None,
    ) -> dict:
        """在临时文件中执行 Python 代码。

        timeout 未显式传入时读取 config 的 solver.timeout（默认 30）。
        extra_files: 注入到执行目录的文件 {文件名: 内容}——用于子问题数据契约链
        （前序子问题结果 result_N.json 传给后续子问题读取，保证跨子问题数据一致）。
        figure_dir: 图片持久化目录——执行产生的图（热力图/Pareto 前沿等）复制到
        该目录后返回**持久路径**（临时目录执行完即删，不持久化则图片丢失）。
        task_dir: 任务级数据目录（Web 多任务并发时通过参数传入，
        替代全局环境变量 MATHAGENT_TASK_DIR，避免不同任务数据互相污染）。
        """
        if timeout is None:
            timeout = int(get("solver.timeout", 30) or 30)
        if not code.strip():
            return {
                "success": False, "stdout": "", "stderr": "代码为空",
                "returncode": -1, "safety_fail": False,
            }

        # 执行前安全检查
        if not code or len(code.strip()) < 10:
            return {
                "success": False, "stdout": "",
                "stderr": "代码为空或过短，跳过执行",
                "returncode": -1, "safety_fail": False,
            }
        # 安全检查用原始代码（归一化只改字符串字面量，不影响安全审查，
        # 但先 validate 保证审查对象与 LLM 输出一致，防路径注入类绕过）
        is_safe, safety_error = validate_code(code)
        if not is_safe:
            self.logger.warning(f"代码安全检查未通过: {safety_error}")
            return {
                "success": False, "stdout": "",
                "stderr": f"安全检查失败: {safety_error}",
                "returncode": -1, "safety_fail": True,
            }

        # 数据路径归一化：LLM 偶发硬编码绝对路径（data/task_xxx/附件.xlsx 或
        # C:\tmp\sandbox\data\xxx.csv），沙箱只有相对路径 data/文件名。
        # 在 validate 之后执行（validate 用原始代码，归一化不影响安全审查）。
        code = _normalize_data_paths(code)

        # 依赖检查
        missing = check_dependencies(code)
        if missing:
            self.logger.warning(f"缺少依赖库: {missing}")

        # 铁律：剥掉 Builder 注入的断言锁，代码才能执行（仅沙箱有权限）
        from agents.builder import remove_iron_lock
        code = remove_iron_lock(code)
        if not code.strip():
            return {
                "success": False, "stdout": "", "stderr": "代码为空（铁律锁剥离后）",
                "returncode": -1, "safety_fail": False,
            }

        # 独立临时子目录执行：避免 %TEMP% 根目录的历史遗留文件（截图等）
        # 污染图片收集/结果读取；执行完整体清理。
        # 目录放在项目内 data/tmp_exec/（而非系统 %TEMP%）：
        #   1. 沙箱/受限环境下系统 TEMP 可能只读，导致 solution.py 写不进去
        #   2. 产物位置可控，配合启动清理，不污染系统临时区
        tmp_dir = _make_exec_tmp_dir()
        tmp_path = tmp_dir / "solution.py"
        try:
            tmp_path.write_text(code, encoding="utf-8")
        except Exception as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {
                "success": False, "stdout": "", "stderr": f"脚本写入失败: {e}",
                "returncode": -1, "safety_fail": False,
            }

        # 注入前序子问题结果文件（数据契约链）：后续子问题代码按相对路径读取
        if extra_files:
            try:
                for fname, content in extra_files.items():
                    (tmp_dir / fname).write_text(content, encoding="utf-8")
            except Exception as e:
                self.logger.warning(f"前序结果文件注入失败: {e}")

        # 数据上下文：只复制当前任务目录的数据，不复制全局 data/
        # 避免不同任务的数据文件混在一起。
        # 优先用参数传入的 task_dir（Web 并发时线程安全），
        # 回退到环境变量（CLI 模式向后兼容）。
        try:
            # 如果有 extra_files（数据契约链），已经注入了
            # 额外：检查当前任务目录下是否有数据文件
            if task_dir is None:
                task_dir = Path(os.environ.get("MATHAGENT_TASK_DIR", ""))
            task_dir_path = Path(task_dir)
            if task_dir_path.exists():
                data_files_copied: list[Path] = []
                for df in task_dir_path.rglob("*"):
                    if df.is_file() and df.suffix.lower() in (".csv", ".xlsx", ".txt"):
                        rel = df.relative_to(task_dir_path)
                        dest = tmp_dir / "data" / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(df, dest)
                        data_files_copied.append(dest)

                # 常用文件名别名：LLM 生成代码时经常猜文件名（data.xlsx/数据.csv 等），
                # 实际文件名可能是附件.xlsx。为每个数据文件创建常见别名副本，
                # 无论代码猜什么名字都能读到。别名：data+原后缀、数据+原后缀、
                # 原始文件名（附件.xlsx 保持）。
                alias_names = ["data", "数据"]
                for dest in data_files_copied:
                    if dest.suffix.lower() not in (".csv", ".xlsx", ".txt"):
                        continue
                    for alias in alias_names:
                        alias_path = dest.with_name(alias + dest.suffix)
                        if not alias_path.exists():
                            shutil.copy2(dest, alias_path)
        except Exception as e:
            self.logger.warning(f"数据上下文复制失败: {e}")

        # 执行前清理可能残留的 metrics.json（避免读到旧结果）
        tmp_metrics = tmp_dir / "metrics.json"
        tmp_metrics.unlink(missing_ok=True)

        try:
            # 在代码文件开头注入 UTF-8 编码设置（避免依赖环境变量）
            original_code = code
            # 注入 matplotlib 配置：
            # 1. Agg 非交互后端（服务器无 GUI，且多进程画图安全）
            # 2. 中文字体（解决方块字问题）
            matplotlib_font = """import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
"""
            code = "# -*- coding: utf-8 -*-\nimport sys, io\nsys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n" + matplotlib_font + code
            print(f"  [DEBUG] 写入代码到: {tmp_path}", flush=True)
            tmp_path.write_text(code, encoding="utf-8")
            print(f"  [DEBUG] 执行 subprocess", flush=True)
            # 输出重定向到文件（而非 capture_output 管道）：
            #   1. 受限/沙箱环境下管道捕获子进程输出会 EPERM，文件重定向可绕过
            #   2. 避免 Windows 管道编码问题（Errno 22）
            #   3. 执行输出落盘到临时目录，随 finally 整体清理，不留垃圾
            out_file = tmp_dir / "_stdout.txt"
            err_file = tmp_dir / "_stderr.txt"
            with open(out_file, "wb") as _o, open(err_file, "wb") as _e:
                result = subprocess.run(
                    [sys.executable, "-u", str(tmp_path)],
                    stdout=_o,
                    stderr=_e,
                    stdin=subprocess.DEVNULL,
                    timeout=timeout,
                    cwd=str(tmp_dir),
                )
            # 从文件回读输出
            stdout = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
            stderr = err_file.read_text(encoding="utf-8", errors="replace") if err_file.exists() else ""
            result.stdout = stdout
            result.stderr = stderr
            print(f"  [DEBUG] 完成: returncode={result.returncode}", flush=True)
            # 执行后回读代码写入的 metrics.json（真实运行结果）
            metrics_json: dict = {}
            if tmp_metrics.exists():
                try:
                    parsed = json.loads(tmp_metrics.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self.logger.warning("metrics.json 解析失败")
                    parsed = None
                # 类型校验：代码可能写入数组/字符串，非 dict 一律视为无指标
                if isinstance(parsed, dict):
                    metrics_json = parsed
                else:
                    self.logger.warning("metrics.json 非 JSON 对象，忽略")

            # 收集执行产生的图片（供论文插图：热力图/Pareto图等）。
            # 临时目录执行完即删 → 必须复制到 figure_dir 持久化
            figures: list[str] = []
            try:
                for ext in (".png", ".jpg", ".jpeg", ".pdf"):
                    for p in tmp_dir.glob(f"*{ext}"):
                        if figure_dir:
                            fig_path = Path(figure_dir) / p.name
                            fig_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(p, fig_path)
                            figures.append(str(fig_path))
                        else:
                            figures.append(str(p))
            except Exception:
                pass
            # ── 成功判定增强：不仅看 returncode，还要检查 stdout 内容 ──
            # returncode=0 但 stdout 包含错误模式 = 代码"假装成功"（如 print 后 sys.exit(0)）
            _error_patterns = [
                "文件不存在", "文件未找到", "找不到文件", "No such file",
                "FileNotFoundError", "文件夹不存在", "目录不存在",
                "无法读取", "读取失败", "数据为空", "没有数据",
            ]
            _stdout_is_error = any(pat in (result.stdout or "") for pat in _error_patterns)
            # returncode=0 且 metrics_json 为空 → 可能是"空跑"成功（无实际计算）
            _empty_success = result.returncode == 0 and not metrics_json and not figures
            _effective_success = result.returncode == 0 and not _stdout_is_error

            if not _effective_success and result.returncode == 0:
                # 代码"假装成功"：returncode=0 但实际无有效产出
                # 将错误信息注入 stderr 让后续 Agent Loop 能修复
                _fake_error = f"代码执行看似成功但实际无有效产出: stdout含错误模式或metrics.json为空"
                result.stderr = (result.stderr + "\n" + _fake_error).strip() if result.stderr else _fake_error
                self.logger.warning(f"代码假装成功: stdout含错误模式={_stdout_is_error}, metrics_json为空={not metrics_json}")

            return {
                "success": _effective_success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "safety_fail": False,
                "metrics_json": metrics_json,
                "missing_deps": missing,
                "figures": figures,
                # 标记是否是"假装成功"
                "fake_success": result.returncode == 0 and not _effective_success,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "stdout": "", "stderr": "执行超时", "returncode": -1, "safety_fail": False}
        except Exception as e:
            self.logger.error(f"执行失败: {type(e).__name__}: {e} | exe={sys.executable} | cwd={tmp_dir}")
            return {"success": False, "stdout": "", "stderr": f"{type(e).__name__}: {e}", "returncode": -1, "safety_fail": False}
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def fix_code(
        self,
        code: str,
        max_retries: int = 3,
        extra_files: dict[str, str] | None = None,
        figure_dir: str | Path | None = None,
        task_dir: str | Path | None = None,
    ) -> dict:
        """执行代码，失败时自动修复，最多重试 max_retries 次。"""
        # 入口清洗控制字符（LLM 生成/修复代码偶发混入 NUL）
        code = _sanitize_code(code)
        # 仅当配置文件显式设置时覆盖，否则使用调用者传入的值
        config_retries = get("solver.max_retries", None)
        if config_retries is not None:
            max_retries = config_retries

        # 初始代码安全检查（前置）
        is_safe, safety_error = validate_code(code)
        if not is_safe:
            self.logger.warning(f"初始代码未通过安全检查: {safety_error}")
            return {
                "status": "error",
                "code": code,
                "error": f"安全检查失败: {safety_error}",
                "last_stderr": "",
                "safety_fail": True,
            }

        current_code = code
        last_stderr = ""
        seen_hashes = set()

        for attempt in range(1, max_retries + 1):
            # 检测重复修复
            code_hash = _code_hash(current_code)
            if code_hash in seen_hashes:
                self.logger.warning(f"第{attempt}次修复与之前相同，提前终止")
                break
            seen_hashes.add(code_hash)

            exec_result = self.run_code(
                current_code, extra_files=extra_files, figure_dir=figure_dir, task_dir=task_dir
            )

            # 安全检查失败，直接终止（不尝试修复）
            if exec_result.get("safety_fail"):
                self.logger.warning("代码未通过安全检查，拒绝执行和修复")
                return {
                    "status": "error",
                    "code": current_code,
                    "error": exec_result["stderr"],
                    "last_stderr": exec_result["stderr"],
                    "safety_fail": True,
                }

            if exec_result["success"]:
                metrics = _extract_metrics(exec_result["stdout"])
                # 合理性校验同时覆盖 metrics.json（论文引用的真值来源）
                mj = exec_result.get("metrics_json", {})
                if isinstance(mj, dict):
                    merged_metrics = dict(metrics)
                    numbers = dict(metrics.get("numbers", {}))
                    for k, v in mj.items():
                        if isinstance(v, (int, float)):
                            numbers.setdefault(k, []).append(v)
                    merged_metrics["numbers"] = numbers
                else:
                    merged_metrics = metrics
                sanity_issue = _check_result_sanity(merged_metrics, exec_result["stdout"])
                if sanity_issue and attempt < max_retries:
                    self.logger.warning(
                        f"第{attempt}次执行成功但结果不合理: {sanity_issue}"
                    )
                    sanity_prompt = f"""以下Python代码执行成功，但输出结果存在物理/逻辑不合理：
问题：{sanity_issue}

请修复代码（可能是模型公式错误、单位错误、参数不合理或数据处理错误），
确保输出数值合理。请返回修正后的完整代码。

当前代码：
```python
{current_code}
```"""
                    fixed = self.think(sanity_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.2)
                    if not fixed:
                        self.logger.error("LLM 未返回修复代码")
                        break
                    current_code = _extract_code(fixed)
                    continue

                # 验证状态判定：结果不合理或零指标（无任何可引用数值）都不得标 verified
                has_metrics = bool(
                    exec_result.get("metrics_json")
                    or metrics.get("numbers")
                    or metrics.get("key_lines")
                    or metrics.get("tables")
                )
                v_status = "verified_metrics" if (not sanity_issue and has_metrics) else "unverified"

                self.logger.info(f"代码执行成功（第{attempt}次尝试）")
                return {
                    "status": "ok",
                    "code": current_code,
                    "output": exec_result["stdout"],
                    "metrics": metrics,
                    "metrics_json": exec_result.get("metrics_json", {}),
                    "attempts": attempt,
                    "missing_deps": exec_result.get("missing_deps"),
                    "figures": exec_result.get("figures", []),
                    "sanity_issue": sanity_issue,
                    "verification_status": v_status,
                    "verify_note": (
                        None if v_status == "verified_metrics"
                        else (sanity_issue or "执行成功但无任何可引用指标")
                    ),
                }

            last_stderr = exec_result.get("stderr", "未知错误")
            self.logger.warning(f"第{attempt}次执行失败: {_truncate_stderr(last_stderr, 300)}")

            # 完全无错误信息时（无法提供任何修复线索），直接终止
            if not last_stderr.strip():
                self.logger.warning("错误信息为空，终止修复尝试")
                break

            # 超时单独处理：给 LLM 一次机会，提示可能原因
            if "超时" in last_stderr:
                self.logger.warning("执行超时，将提示 LLM 检查死循环或数据规模")
                if attempt >= max_retries:
                    break
                timeout_secs = int(get("solver.timeout", 30) or 30)
                timeout_prompt = f"""以下Python代码执行超时，常见原因包括死循环、数据规模过大或算法复杂度太高。
请修复代码，使其能在{timeout_secs}秒内完成执行（例如限制迭代次数、缩小数据规模、优化循环逻辑）。
请返回修正后的完整代码。

原代码：
```python
{current_code}
```"""
                fixed = self.think(timeout_prompt, system_prompt=SYSTEM_PROMPT, temperature=0.2)
                if not fixed:
                    self.logger.error("LLM 未返回修复代码")
                    break
                current_code = _extract_code(fixed)
                continue

            if attempt < max_retries:
                prompt = f"""以下Python代码执行报错，请分析错误原因并返回修正后的完整代码。

错误信息：
{last_stderr}

原代码：
```python
{current_code}
```"""

                fixed = self.think(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.2)
                if not fixed:
                    self.logger.error("LLM 未返回修复代码")
                    break
                current_code = _extract_code(fixed)

        return {
            "status": "error",
            "code": current_code,
            "error": f"经过{max_retries}次修复仍无法执行",
            "last_stderr": last_stderr,
            "safety_fail": False,
        }

    def run(self, code: str, extra_files: dict[str, str] | None = None,
            figure_dir: str | Path | None = None, task_dir: str | Path | None = None) -> dict:
        """主入口：执行代码并尝试修复。"""
        return self.fix_code(
            code, extra_files=extra_files, figure_dir=figure_dir, task_dir=task_dir
        )


# ── 单例 + 兼容函数接口 ──────────────────────────────────────

_instance: SolverAgent | None = None


def solver(code: str) -> dict:
    """兼容旧的函数调用方式，使用单例避免重复实例化。"""
    global _instance
    if _instance is None:
        _instance = SolverAgent()
    return _instance.run(code)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    agent = SolverAgent()

    # 测试1：正确代码
    code1 = "print('Hello, MathModeling!')"
    result1 = agent.run(code1)
    print(f"测试1 - 状态：{result1['status']}")
    print(f"  输出：{result1.get('output', '').strip()}")
    print()

    # 测试2：有bug的代码（自动修复）
    code2 = "x = 1 / 0"
    result2 = agent.run(code2)
    print(f"测试2 - 状态：{result2['status']}")
    print(f"  尝试次数：{result2.get('attempts', 'N/A')}")
    if result2["status"] == "error":
        print(f"  错误：{result2.get('error', '')[:100]}")
    print()

    # 测试3：危险代码（安全检查拦截）
    code3 = "import os; os.system('rm -rf /')"
    result3 = agent.run(code3)
    print(f"测试3 - 状态：{result3['status']}")
    print(f"  安全检查失败：{result3.get('safety_fail', False)}")
    print(f"  错误：{result3.get('error', '')[:100]}")
