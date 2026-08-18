from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from agents.base import BaseAgent
from utils.config import get
from utils.experience import _classify, algorithm_prior, lessons_for
from utils.modeling_kb import (
    classify_problem, algo_whitelist, kb_text, enforce_whitelist,
    analyze_problem_structure, structure_redline,
)

SYSTEM_PROMPT = "你是一位数学建模专家，精通各类建模算法，擅长为不同问题匹配合适的解法。"

USER_PROMPT_TEMPLATE = """\
赛题：{problem_text}

子问题列表：
{sub_problems_text}

请为每个子问题推荐最适合的建模算法。

可用算法池：{algorithm_pool}

{knowledge_base}

【重要】index 字段是子问题在列表中的序号（从1开始），必须与子问题列表一一对应；sub_problem 字段必须与上方子问题原文完全一致，不要改写。

请按以下JSON格式返回，不要有任何额外内容：
{{
  "main_algorithm": "整体最核心的算法",
  "sub_algorithms": [
    {{"index": 1, "sub_problem": "子问题1原文", "algorithm": "推荐算法"}},
    {{"index": 2, "sub_problem": "子问题2原文", "algorithm": "推荐算法"}}
  ],
  "reason": "一句话推荐理由"
}}"""


def _match_algorithm(algo: str, pool: set[str], alias_map: dict[str, str]) -> str:
    """将算法名标准化到预设池中。"""
    algo = algo.strip()
    if not algo:
        return "未确定"
    if algo in pool:
        return algo
    if algo in alias_map:
        return alias_map[algo]
    matches = difflib.get_close_matches(algo, pool, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    candidates = [v for v in pool if algo in v or v in algo]
    if candidates:
        return max(candidates, key=len)
    return "未确定"


def _match_subproblem(returned_text: str, original_list: list[str]) -> str | None:
    """将 LLM 返回的子问题文本与原始列表匹配。"""
    returned_text = returned_text.strip()
    if not returned_text:
        return None

    # 1. 精确匹配
    for orig in original_list:
        if returned_text == orig:
            return orig

    # 2. 子串匹配
    for orig in original_list:
        if returned_text in orig or orig in returned_text:
            return orig

    # 3. 模糊匹配（提高阈值到 0.7）
    best_match = None
    best_score = 0.0
    for orig in original_list:
        score = difflib.SequenceMatcher(None, returned_text, orig).ratio()
        if score > best_score:
            best_score = score
            best_match = orig

    if best_match and best_score >= 0.7:
        return best_match

    return None


def _parse_llm_json(text: str) -> dict | None:
    """从 LLM 输出中提取第一个 JSON 对象，增强健壮性。"""
    # 清理 Markdown 代码块
    text = re.sub(r"```(?:json)?\s*\n?([\s\S]*?)```", r"\1", text).strip()

    # 尝试直接解析整个文本
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取第一个完整 JSON 对象
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        # 尝试修复常见问题（如尾部逗号）
        fixed = re.sub(r",\s*([}\]])", r"\1", match.group())
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


class ModelerAgent(BaseAgent):
    """算法推荐智能体：为每个子问题匹配合适的建模算法。"""

    def __init__(self) -> None:
        super().__init__(role="数学建模算法推荐专家")

    def run(self, problem_text: str, sub_problems: list[str]) -> dict:
        """为每个子问题推荐建模算法。"""
        if not sub_problems:
            return {
                "status": "error",
                "main_algorithm": "未确定",
                "sub_algorithms": [],
                "reason": "无子问题输入",
            }

        # 从配置加载算法池和别名
        pool_list = get("modeler.algorithm_pool", [])
        pool = set(pool_list) if pool_list else {
            "线性规划", "整数规划", "遗传算法", "粒子群优化", "模拟退火",
            "ARIMA时间序列", "灰色预测GM(1,1)", "指数平滑", "回归分析",
            "层次分析法(AHP)", "熵权法", "TOPSIS", "聚类分析",
            "主成分分析(PCA)", "神经网络", "支持向量机(SVM)",
            "决策树", "随机森林",
        }
        alias_map = get("modeler.alias_map", {}) or {
            "SVM": "支持向量机(SVM)",
            "支持向量机": "支持向量机(SVM)",
            "PCA": "主成分分析(PCA)",
            "主成分分析": "主成分分析(PCA)",
            "AHP": "层次分析法(AHP)",
            "层次分析": "层次分析法(AHP)",
            "GM(1,1)": "灰色预测GM(1,1)",
            "灰色预测": "灰色预测GM(1,1)",
        }
        temperature = get("modeler.temperature", 0.2)

        sub_problems_text = "\n".join(
            f"{i+1}. {sp}" for i, sp in enumerate(sub_problems)
        )

        # 建模知识库：确定性题型分类 → 算法白名单 → 注入提示词
        ptype = classify_problem(problem_text, *sub_problems)
        whitelist = algo_whitelist(ptype)
        self.update_state("problem_type", ptype)
        self.logger.info(f"题型判定：{ptype}，白名单 {len(whitelist)} 个算法")

        # 问题结构诊断（确定性规则，零 LLM）：维度/组合/可解析化/边界风险
        # → 每个子问题生成【建模策略红线】，防止 LLM 默认走网格搜索等次优方向
        # （2025A 实测：8 维三弹优化用网格 → 5.30s vs 差分进化 6.9s）
        diagnostics: dict[str, dict] = {}
        redline_lines: list[str] = []
        for sp in sub_problems:
            struct = analyze_problem_structure(sp)
            diagnostics[sp] = struct
            red = structure_redline(struct)
            if red:
                redline_lines.append(f"子问题「{sp[:40]}」：\n{red}")
        self.update_state("diagnostics", diagnostics)
        if redline_lines:
            self.logger.info(f"结构诊断：{sum(1 for d in diagnostics.values() if d['dim_estimate'] > 0)} 个子问题检出维度")

        # 经验库先验：决策教训（种子 + 历史）注入，让"第一次"就有方向
        lesson_lines: list[str] = []
        for sp in sub_problems:
            for l in lessons_for(sp):
                if l not in lesson_lines:
                    lesson_lines.append(l)

        prompt = USER_PROMPT_TEMPLATE.format(
            problem_text=problem_text,
            sub_problems_text=sub_problems_text,
            algorithm_pool="、".join(sorted(pool)),
            knowledge_base=kb_text(ptype, whitelist),
        )
        if redline_lines:
            prompt += (
                "\n\n【建模策略红线——必须据此选择算法，禁止与红线冲突】\n"
                + "\n".join(redline_lines)
            )
        if lesson_lines:
            prompt += (
                "\n\n【历史经验教训——同类问题的已知坑，算法选择时必须避开】\n"
                + "\n".join(lesson_lines)
            )

        # 经验库先验：同类历史任务中成功率高的算法优先
        prior_lines: list[str] = []
        seen_types: set[str] = set()
        for sp in sub_problems:
            prior = algorithm_prior(sp, sorted(pool))
            if prior:
                # 注意用局部变量 sp_type——此前直接复用 ptype 会覆盖上方
                # classify_problem 的题型判定，导致后续白名单日志错乱
                sp_type = _classify(sp)
                if sp_type in seen_types:
                    continue
                seen_types.add(sp_type)
                top = prior[0]
                prior_lines.append(
                    f"- 同类任务「{sp_type}」历史成功率最高: {top['algorithm']} "
                    f"({top['success_rate']*100:.0f}%, 样本{top['samples']}次)"
                )
        if prior_lines:
            prompt += (
                "\n\n【历史经验参考（来自经验库，仅供参考，非强制）】\n"
                + "\n".join(prior_lines)
                + "\n请在算法选择合理的前提下，优先考虑历史成功率高的算法。"
            )
            self.logger.info("已注入 %d 条经验库先验", len(prior_lines))
        result = self.think(prompt, system_prompt=SYSTEM_PROMPT, temperature=temperature)

        if not result:
            return {
                "status": "error",
                "main_algorithm": "未确定",
                "sub_algorithms": [],
                "reason": "LLM未返回结果",
            }

        data = _parse_llm_json(result)
        if data is None:
            self.logger.error(f"JSON解析失败，原始输出：\n{result[:500]}")
            return {
                "status": "error",
                "main_algorithm": "未确定",
                "sub_algorithms": [],
                "reason": "JSON解析失败",
            }

        raw_algos = data.get("sub_algorithms", [])
        if isinstance(raw_algos, dict):
            self.logger.warning("LLM返回了旧格式（dict），已忽略")
            raw_algos = []

        algo_map: dict[str, str] = {}
        for item in raw_algos:
            # 仅信任 index 精确对齐（从1开始）；index 缺失或无效时不猜测
            raw_index = item.get("index")
            orig = None
            if isinstance(raw_index, int) and 1 <= raw_index <= len(sub_problems):
                orig = sub_problems[raw_index - 1]
            else:
                self.logger.warning(
                    f"LLM 返回条目缺少有效 index（{raw_index!r}），"
                    f"该子问题标记为未确定，避免错配: {item.get('sub_problem', '')[:40]}"
                )
            if orig:
                raw_algo = item.get("algorithm", "")
                matched = _match_algorithm(raw_algo, pool, alias_map)
                if matched != "未确定" and matched not in whitelist:
                    # 白名单强制：LLM 推荐了题型不匹配的算法（如物理题给决策树）
                    forced = enforce_whitelist(raw_algo, whitelist, pool, alias_map)
                    self.logger.warning(
                        f"算法 {matched} 不在「{ptype}」白名单，强制替换为 {forced}"
                    )
                    matched = forced
                algo_map[orig] = matched

        # 未匹配到的子问题置为"未确定"
        aligned = [
            {"sub_problem": sp, "algorithm": algo_map.get(sp, "未确定")}
            for sp in sub_problems
        ]

        matched = sum(1 for a in aligned if a["algorithm"] != "未确定")
        self.logger.info(f"算法匹配率：{matched}/{len(aligned)}")

        main_algo = data.get("main_algorithm", "")
        main_algo = _match_algorithm(main_algo, pool, alias_map) if main_algo else "未确定"
        if main_algo != "未确定" and main_algo not in whitelist:
            forced = enforce_whitelist(main_algo, whitelist, pool, alias_map)
            self.logger.warning(f"主算法 {main_algo} 不在「{ptype}」白名单，强制替换为 {forced}")
            main_algo = forced

        self.update_state("main_algorithm", main_algo)
        self.update_state("sub_algorithms", aligned)

        return {
            "status": "ok",
            "main_algorithm": main_algo,
            "sub_algorithms": aligned,
            "reason": data.get("reason") or "无",
            "diagnostics": diagnostics,
        }


# ── 单例 + 兼容函数接口 ──────────────────────────────────────

_instance: ModelerAgent | None = None


def modeler(problem_text: str, sub_problems: list[str]) -> dict:
    """兼容旧的函数调用方式，使用单例避免重复实例化。"""
    global _instance
    if _instance is None:
        _instance = ModelerAgent()
    return _instance.run(problem_text, sub_problems)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from utils.file_parser import parse_file

    test_file = Path(__file__).parent.parent / "data" / "test.txt"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(
        "某城市计划在校园内投放共享单车，需要解决以下问题："
        "如何确定投放数量、如何规划停放区域、如何设计调度方案以满足师生出行需求。",
        encoding="utf-8",
    )

    problem_text = parse_file(str(test_file))
    from agents.coordinator import CoordinatorAgent
    sub_problems = CoordinatorAgent().run(problem_text)

    print("子问题列表：")
    for i, sp in enumerate(sub_problems, 1):
        print(f"  {i}. {sp}")
    print()

    agent = ModelerAgent()
    result = agent.run(problem_text, sub_problems)
    print(f"状态：{result['status']}")
    print(f"推荐主算法：{result['main_algorithm']}")
    print(f"推荐理由：{result['reason']}")
    print("各子问题算法：")
    for item in result["sub_algorithms"]:
        print(f"  {item['sub_problem'][:30]} -> {item['algorithm']}")
