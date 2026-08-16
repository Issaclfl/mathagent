"""Agent Loop：LLM 带工具调用的推理循环。

在流水线的关键失败点调用，让 LLM 分析错误、选择修复策略、
重新生成代码。核心思想：给 LLM 一组工具，让它自己决定怎么修。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "在临时目录中执行 Python 代码。返回 stdout 和 stderr。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 代码"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将内容写入指定文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_error",
            "description": "分析错误日志，返回错误原因和修复建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "error": {"type": "string", "description": "错误信息"},
                    "code": {"type": "string", "description": "出错的代码"},
                },
                "required": ["error"],
            },
        },
    },
]


# ══════════════════════════════════════════════════════════════
# 工具执行器
# ══════════════════════════════════════════════════════════════

def execute_tool(tool_name: str, tool_args: dict) -> str:
    """执行工具调用，返回结果字符串。"""
    if tool_name == "execute_python":
        return _exec_python(tool_args.get("code", ""))
    elif tool_name == "read_file":
        return _read_file(tool_args.get("path", ""))
    elif tool_name == "write_file":
        return _write_file(tool_args.get("path", ""), tool_args.get("content", ""))
    elif tool_name == "analyze_error":
        return _analyze_error(tool_args.get("error", ""), tool_args.get("code", ""))
    else:
        return f"未知工具: {tool_name}"


def _exec_python(code: str) -> str:
    """在临时目录中执行 Python 代码。"""
    tmp_dir = tempfile.mkdtemp(prefix="agent_loop_")
    try:
        code_path = Path(tmp_dir) / "script.py"
        code_path.write_text(code, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, "-u", str(code_path)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, env=env, cwd=str(tmp_dir),
        )
        output = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
        stderr = result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
        if result.returncode == 0:
            return f"执行成功\nstdout:\n{output}"
        else:
            return f"执行失败 (returncode={result.returncode})\nstdout:\n{output}\nstderr:\n{stderr}"
    except subprocess.TimeoutExpired:
        return "执行超时（60秒）"
    except Exception as e:
        return f"执行异常: {e}"
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _read_file(path: str) -> str:
    """读取文件内容。"""
    try:
        p = Path(path)
        if not p.exists():
            return f"文件不存在: {path}"
        content = p.read_text(encoding="utf-8")
        if len(content) > 5000:
            content = content[:5000] + f"\n... (共 {len(content)} 字符，已截断)"
        return content
    except Exception as e:
        return f"读取失败: {e}"


def _write_file(path: str, content: str) -> str:
    """写入文件。"""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {path}（{len(content)} 字符）"
    except Exception as e:
        return f"写入失败: {e}"


def _analyze_error(error: str, code: str = "") -> str:
    """分析错误，返回结构化分析（规则引擎，不调 LLM）。"""
    issues = []
    if "ModuleNotFoundError" in error or "No module named" in error:
        mod = re.search(r"No module named ['\"]?(\w+)['\"]?", error)
        if mod:
            issues.append(f"缺少依赖库: {mod.group(1)}，需要 pip install {mod.group(1)}")
    elif "KeyError" in error:
        key = re.search(r"KeyError:\s*['\"]?([^'\"]+)", error)
        if key:
            issues.append(f"缺少键: {key.group(1)}，检查数据文件结构")
    elif "FileNotFoundError" in error:
        fn = re.search(r"No such file:\s*['\"]?([^'\"]+)", error)
        if fn:
            issues.append(f"文件不存在: {fn.group(1)}，检查路径")
    elif "ValueError" in error or "TypeError" in error:
        issues.append("数据类型不匹配，检查输入数据格式")
    elif "IndexError" in error:
        issues.append("数组越界，检查数据维度")
    elif "TimeoutExpired" in error or "timeout" in error.lower():
        issues.append("代码执行超时，优化算法复杂度或增加超时时间")
    else:
        issues.append(f"未识别的错误类型，原始信息: {error[:200]}")

    if code:
        issues.append(f"相关代码长度: {len(code)} 字符")

    return "\n".join(issues)


# ══════════════════════════════════════════════════════════════
# Agent Loop 核心
# ══════════════════════════════════════════════════════════════

def agent_loop(
    task: str,
    tools: list[dict] | None = None,
    max_rounds: int = 5,
    temperature: float = 0.2,
) -> dict:
    """LLM 带工具调用的推理循环。

    Args:
        task: 完整的任务描述（包含上下文、错误信息等）
        tools: 可用工具定义列表
        max_rounds: 最大推理轮次
        temperature: LLM 温度

    Returns:
        {"status": "ok"|"max_rounds", "result": str, "rounds": int, "tool_calls": list}
    """
    from utils.llm_client import call_llm

    if tools is None:
        tools = TOOL_DEFINITIONS

    messages = [{"role": "user", "content": task}]
    all_tool_calls = []

    for round_num in range(1, max_rounds + 1):
        logger.info(f"Agent Loop 第 {round_num}/{max_rounds} 轮")

        # 调用 LLM
        response = call_llm(
            prompt=task if round_num == 1 else messages[-1]["content"],
            system_prompt="你是数学建模专家。分析问题并使用工具修复。只输出最终答案，不要解释。",
            temperature=temperature,
        )

        if not response:
            return {"status": "error", "result": "LLM 返回空结果", "rounds": round_num, "tool_calls": all_tool_calls}

        # 检查是否有工具调用（通过简单文本解析）
        tool_match = re.search(r'```json\s*(\{[^}]+\"tool\"[^}]+\})\s*```', response)
        if tool_match:
            try:
                tool_call = json.loads(tool_match.group(1))
                tool_name = tool_call.get("tool", "")
                tool_args = tool_call.get("args", {})
                logger.info(f"工具调用: {tool_name}({list(tool_args.keys())})")

                # 执行工具
                result = execute_tool(tool_name, tool_args)
                all_tool_calls.append({"tool": tool_name, "args": tool_args, "result": result[:500]})

                # 把结果加入消息历史
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"工具执行结果:\n{result}"})
                continue  # 继续下一轮
            except json.JSONDecodeError:
                pass

        # 没有工具调用 → 返回最终结果
        return {"status": "ok", "result": response, "rounds": round_num, "tool_calls": all_tool_calls}

    return {"status": "max_rounds", "result": response, "rounds": max_rounds, "tool_calls": all_tool_calls}


# ══════════════════════════════════════════════════════════════
# 高层接口：在流水线失败时调用
# ══════════════════════════════════════════════════════════════

def analyze_and_fix_code(error: str, code: str, sub_problem: str) -> dict:
    """分析代码错误并生成修复后的代码。

    Returns:
        {"status": "fixed"|"failed", "fixed_code": str, "analysis": str}
    """
    task = f"""你是一个 Python 代码调试专家。

子问题：{sub_problem}

出错的代码：
```python
{code[:2000]}
```

错误信息：
```
{error[:1000]}
```

请分析错误原因，然后生成修复后的完整代码。
直接输出修复后的 Python 代码，不要解释。用 ```python 和 ``` 包裹。"""

    result = agent_loop(task, tools=[], max_rounds=2, temperature=0.2)

    # 从结果中提取代码
    code_match = re.search(r'```python\s*(.*?)```', result["result"], re.DOTALL)
    if code_match:
        fixed_code = code_match.group(1).strip()
        return {"status": "fixed", "fixed_code": fixed_code, "analysis": result["result"], "rounds": result["rounds"]}

    return {"status": "failed", "fixed_code": "", "analysis": result["result"], "rounds": result["rounds"]}


def diagnose_paper_issue(paper_text: str, audit_report: str) -> str:
    """分析论文质量问题并给出修复建议。"""
    task = f"""你是数学建模论文审阅专家。

论文片段：
{paper_text[:2000]}

审核报告：
{audit_report[:1000]}

请分析论文存在的问题，给出具体的修改建议。"""

    result = agent_loop(task, tools=[], max_rounds=1, temperature=0.3)
    return result["result"]
