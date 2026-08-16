from __future__ import annotations

import re
from pathlib import Path

from agents.base import BaseAgent
from utils.config import get
from utils.file_parser import parse_file

SYSTEM_PROMPT = "你是一位数学建模专家，擅长将复杂问题拆解为可独立求解的子问题。"

USER_PROMPT_TEMPLATE = """\
请将以下数学建模赛题拆解为3-5个独立的子问题。

要求：
1. 每个子问题应该是可独立建模和求解的
2. 子问题之间应有逻辑递进关系
3. 只返回子问题列表，每行一个，不要有序号、不要额外解释

赛题：
{problem_text}"""

RETRY_PROMPT_TEMPLATE = """\
你只返回了{current}个子问题，不足{min_count}个。请在已有子问题基础上补充，使总数达到{min_count}-{max_count}个。

已有子问题：
{existing}

请继续补充新的子问题（不要重复已有内容）："""


def _strip_numbering(line: str) -> str:
    """去掉 LLM 常见的序号前缀。"""
    line = re.sub(r"^\*{1,2}[\d]+[.、)）．]\s*\*{0,2}", "", line)
    line = re.sub(r"^[(\uff08]?\s*[\d]+\s*[)\uff09]?[.、)）．]\s*", "", line)
    line = re.sub(r"^\u7b2c[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+[\u3001\uff1a:]\s*", "", line)
    line = re.sub(r"^[-*]\s+(?=\S)", "", line)
    line = re.sub(r"^\u5b50\u95ee\u9898\s*[\d]+\s*[\uff1a:]\s*", "", line)
    # 带圈数字 ① ② ... ⑳
    line = re.sub(r"^[\u2460-\u2473]\s*[.、)）．]?\s*", "", line)
    # 中文括号编号 （一） （二） ...
    line = re.sub(r"^[(\uff08]\s*[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+\s*[)\uff09]\s*[.、)）．]?\s*", "", line)
    return line.strip()


def _dedup(problems: list[str]) -> list[str]:
    """去重，保持原始顺序。"""
    seen: set[str] = set()
    unique: list[str] = []
    for sp in problems:
        key = sp.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


class CoordinatorAgent(BaseAgent):
    """赛题拆解智能体：将复杂赛题拆解为可独立求解的子问题。"""

    def __init__(self) -> None:
        super().__init__(role="数学建模赛题拆解专家")

    def run(
        self,
        problem_text: str,
        min_problems: int | None = None,
        max_problems: int | None = None,
    ) -> list[str]:
        """将赛题拆解为 min_problems ~ max_problems 个子问题。"""
        min_problems = min_problems or get("coordinator.min_problems", 3)
        max_problems = max_problems or get("coordinator.max_problems", 5)
        temperature = get("coordinator.temperature", 0.2)

        if not problem_text or not problem_text.strip():
            self.logger.warning("输入赛题为空，跳过拆解")
            return []

        prompt = USER_PROMPT_TEMPLATE.format(problem_text=problem_text)
        result = self.think(prompt, system_prompt=SYSTEM_PROMPT, temperature=temperature)

        if not result:
            return []

        sub_problems = _dedup(
            stripped
            for line in result.strip().splitlines()
            if (stripped := _strip_numbering(line))
        )

        if not sub_problems:
            self.logger.warning("LLM 未返回有效子问题")
            return []

        # 数量不足时重试一次补充
        if len(sub_problems) < min_problems:
            self.logger.info(
                f"首次拆解仅{len(sub_problems)}个，不足{min_problems}，尝试补充"
            )
            retry = self.think(
                RETRY_PROMPT_TEMPLATE.format(
                    current=len(sub_problems),
                    min_count=min_problems,
                    max_count=max_problems,
                    existing="\n".join(f"  {i+1}. {sp}" for i, sp in enumerate(sub_problems)),
                ),
                system_prompt=SYSTEM_PROMPT,
                temperature=0.3,
            )
            if retry:
                more = _dedup(
                    s
                    for line in retry.strip().splitlines()
                    if (s := _strip_numbering(line)) and s not in sub_problems
                )
                sub_problems = _dedup(sub_problems + more)

        # 超过上限时截断
        if len(sub_problems) > max_problems:
            self.logger.warning(
                f"拆解结果{len(sub_problems)}个，超出上限{max_problems}，截断至前{max_problems}个"
            )
            sub_problems = sub_problems[:max_problems]

        if len(sub_problems) < min_problems:
            self.logger.warning(f"最终子问题仅{len(sub_problems)}个，不足{min_problems}")

        self.update_state("sub_problems", sub_problems)
        return sub_problems


# ── 单例 + 兼容函数接口 ──────────────────────────────────────

_instance: CoordinatorAgent | None = None


def coordinator(
    problem_text: str,
    min_problems: int | None = None,
    max_problems: int | None = None,
) -> list[str]:
    """兼容旧的函数调用方式，使用单例避免重复实例化。"""
    global _instance
    if _instance is None:
        _instance = CoordinatorAgent()
    return _instance.run(problem_text, min_problems, max_problems)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_file = Path(__file__).parent.parent / "data" / "test.txt"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(
        "某城市计划在校园内投放共享单车，需要解决以下问题："
        "如何确定投放数量、如何规划停放区域、如何设计调度方案以满足师生出行需求。",
        encoding="utf-8",
    )

    problem_text = parse_file(str(test_file))
    print(f"赛题内容：{problem_text}\n")

    agent = CoordinatorAgent()
    for i, sp in enumerate(agent.run(problem_text), 1):
        print(f"子问题{i}：{sp}")
