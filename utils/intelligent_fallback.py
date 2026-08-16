"""智能兜底：当规则引擎卡住时，让 LLM 做出判断。

核心思路：pipeline 每个可能卡死的地方加 try，
卡死时调 call_llm 做一次判断，根据回答决定跳过还是终止。
"""

from utils.llm_client import call_llm


def should_skip_data_check(problem_text: str, error: str) -> bool:
    """判断数据校验失败是否可以跳过。"""
    prompt = f"""赛题内容：
{problem_text[:1500]}

数据校验报错：
{error}

请判断：这道题是否真的需要外部数据文件？
- 如果题目自带了模拟数据生成规则、或者数据只是描述性文字 → 回答 SKIP
- 如果题目明确依赖附件数据但找不到文件 → 回答 FAIL

只回答 SKIP 或 FAIL，不要解释。"""

    answer = call_llm(prompt, system_prompt="你是数学建模专家。", temperature=0.1)
    return "SKIP" in answer.upper()


def diagnose_code_error(code: str, error: str, sub_problem: str) -> str:
    """分析代码报错，给出修复方向。"""
    prompt = f"""子问题：{sub_problem}

代码（前500字符）：
{code[:500]}

报错信息：
{error[:1000]}

请用一句话说明错误原因和修复方向。"""

    return call_llm(prompt, system_prompt="你是 Python 调试专家。", temperature=0.2)


def suggest_default_strategy(context: str) -> str:
    """策略门控无人回答时，给出保守默认建议。"""
    prompt = f"""当前情况：
{context}

人工未做决策，请给出一个保守的默认策略建议（一句话）。"""

    return call_llm(prompt, system_prompt="你是建模策略顾问。", temperature=0.3)
