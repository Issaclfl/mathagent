"""论文生成智能体 - 将 pipeline 结果整合为标准数学建模论文（Markdown）。"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agents.base import BaseAgent
from utils.config import get
from utils.verification import status_of_execution, is_verified, PLACEHOLDER

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"

# ── 论文各节的 LLM System Prompt ───────────────────────────────

from agents.paper_guide import FULL_GUIDE, ABSTRACT_GUIDE, MODEL_SECTION_GUIDE, SENSITIVITY_GUIDE, EVALUATION_GUIDE

SYSTEM_PROMPT = "你是一位资深的数学建模竞赛论文写作专家，精通学术写作和获奖论文结构。\n\n" + FULL_GUIDE + """

【全局铁律——输出内容边界（必须无条件遵守）】
1. **禁止元评论与思考过程**：全文严禁出现"设计思路""设计说明""创作意图""写作思路""反思""我选择了…因为…""我考虑到…"等任何对论文本身的解释性内容。论文只能呈现成品内容。
2. **禁止本地路径泄漏**：正文、表格、脚注、图注中严禁出现任何本地文件系统路径（如 `data/`、`figures/`、`C:\\`、`/home/`、`results/` 等）。图片一律以"图N 描述"文字形式引用。
3. **禁止占位符**：严禁输出"[请填入]""[待补充]""[XXX]""…待填写"等占位符文字。数据缺失时该处写"—"或直接省略。
4. 以上规则优先于任何其它风格要求（包括"人类写作风格"规则）。"""

# ── 各节 Prompt 模板 ──────────────────────────────────────────

PROMPT_TITLE = """\
请根据以下赛题内容，生成一个简洁准确的论文标题（不超过25字）。

赛题：
{problem_text}

要求：
1. 标题应概括研究对象和方法
2. 不要加编号、引号或额外说明
3. 只返回标题文本"""

PROMPT_ABSTRACT = """\
请根据以下信息撰写数学建模论文的摘要（200-300字）。

赛题：{problem_text}

子问题与算法：
{sub_algorithms}

代码执行结果摘要：
{exec_summary}

要求：
1. 摘要必须包含**具体的量化结论**（如"累计方差贡献率达85.2%"、"站点X水质最优"等）
2. **【数据填充铁律】**：所有数值**只能**来自代码执行结果摘要（{exec_summary}）中出现的真实值
   - 若某指标在执行结果中存在，直接引用该数值
   - 若某指标不存在或执行失败，该处写"—"或省略，**严禁**写"[请填入...]"等占位符
   - **严禁**凭经验或算法原理编造任何具体数字
3. 涵盖：问题背景、方法选择、关键结果、主要结论
4. 语言精炼、学术规范
5. 只返回摘要正文，不要标题和额外说明

{abstract_guide}"""

PROMPT_PROBLEM_RESTATEMENT = """\
请将以下数学建模赛题进行问题重述。

赛题原文：
{problem_text}

要求：
1. 分为"问题背景"和"问题要求"两部分
2. 用自己的语言重新表述，不要照抄原文
3. 使用 Markdown 格式，二级标题用 ### 1.1 和 ### 1.2"""

PROMPT_PROBLEM_ANALYSIS = """\
请对以下子问题逐一进行问题分析。

赛题背景：{problem_text}

子问题列表：
{sub_problems}

对应算法：
{sub_algorithms}

要求：
1. 每个子问题分析其数学本质和求解思路
2. 说明为什么选择该算法
3. 使用 Markdown 格式，每个子问题用二级标题"""

PROMPT_ASSUMPTIONS = """\
请为以下数学建模问题列出合理的模型假设。

赛题：
{problem_text}

子问题：
{sub_problems}

要求：
1. 列出 5-8 条假设
2. 每条假设需说明合理性
3. 假设之间不能自相矛盾（例如：不能同时假设"现有站点能代表整体"和"需要减少站点"）
4. 只返回假设列表，编号用 1, 2, 3..."""

PROMPT_SYMBOLS = """\
请为以下数学建模问题设计符号说明表。

赛题背景：{problem_text}

使用的算法：{algorithms}

要求：
1. 只列出正文公式中**实际会出现**的符号，不要列出未引用的符号
2. 使用 Markdown 表格格式：| 符号 | 含义 | 单位 |
3. 按模型模块分组（如"基础数据"、"评价模型"、"预测模型"等）
4. 符号数量控制在 20-30 个，精简为主"""

PROMPT_MODEL_SECTION = """\
请为以下子问题撰写"模型建立与求解"章节。

子问题：{sub_problem}
使用的算法：{algorithm}

数学模型描述（节选）：
{math_model}

代码执行结果（节选）：
{execution_output}

要求：
1. 包含三个小节：问题分析、模型建立、模型求解与结果
2. 数学公式使用 LaTeX 格式（$..$ 行内，$$...$$ 独立行）
3. 本章节内的子标题请使用 ####（四个井号），避免与主章节层级冲突

【数据标注规则——必须严格遵守】
- 如果代码执行结果包含具体数值（特征值、得分、预测值等），直接引用并制作结果表格，注明"如表X所示"
- **【数据填充铁律】**：若某指标在代码执行结果中不存在或为空，表格单元格写"—"，**严禁**写"[请填入...]"等占位符
- **严禁**凭经验、算法原理或数据范围编造任何精确数字（如"85.2%"、"0.85"、"RMSE=0.1383109..."）
- 【人工核准优先】若执行结果中带有【人工/独立验证参考真值】区块：该区块是人工核准的正确值，
  论文数值**以真值为准**（人工核准≠编造）；执行结果中与之矛盾的旧值（如负数厚度）必须删除或替换
- 若求解失败，如实写"该模型在当前环境下求解失败，原因为XXX"，**不得**给出任何模拟数值或"方法演示"结果
- 如果整个表格无数据可填，省略该表格，不要输出空表

【引用标注要求】
- 在论述具体方法时（如 PCA、TOPSIS、ARIMA 等），在其首次出现处标注参考文献编号
- 格式：算法名称[编号]，如"主成分分析[3]""TOPSIS[1]"
- 参考文献列表由系统在文末统一生成，您只需在正文中编号标注

【图表引用要求——必须严格遵守】
- 若"代码执行结果"中包含 `![求解结果图](figures/...)` 形式的图片引用，
  **必须原样保留在论文中**，并在其前后补充图标题（如"图1 各时刻动态风险热力图"）与一段图注
- 图片引用格式保持 `![图N 描述](相对路径)` 不变，禁止改动路径或删除图片
- 每张图需在正文中至少提及一次（"如图N所示"）
- **【路径规范】** 图片路径必须是从 `data/results/` 开始的相对路径，**禁止**包含时间戳目录和深层子目录：
  - 禁止：`figures/20260816_013958_489/sub2/decision_tree_visualization.png`
  - 正确：`figures/决策树分组.png`（系统在文末统一处理图片路径）
- 若无法确认图片文件存在，仅用"图N 描述"文字引用，**不插入**任何文件路径

{model_section_guide}"""

PROMPT_SENSITIVITY = """\
请撰写灵敏度分析章节。

子问题与算法：
{sub_algorithms}

代码执行结果摘要：
{exec_summary}

要求：
1. 分析**物理参数或模型假设**的变动对结果的影响（如：监测成本浮动±10%、数据缺失比例、评价权重变化等），而非算法超参数
2. 选择 2-3 个关键参数进行分析
3. 每个参数给出：变化范围、对结果的影响、稳定性结论
4. 使用具体数据或表格支撑分析
5. 在关键论述处标注参考文献引用（格式：方法名[编号]）

{sensitivity_guide}"""

PROMPT_EVALUATION = """\
请撰写模型评价与推广章节。

赛题：{problem_text}
使用的算法：{algorithms}

要求：
1. 分为"模型优点"、"模型缺点"、"模型推广"三部分
2. 每部分列出 3-5 点
3. 使用 Markdown 格式

{evaluation_guide}"""

PROMPT_REFERENCES = """\
请为以下数学建模论文生成参考文献列表。

使用的算法：{algorithms}
赛题背景：{problem_text}

要求：
1. 列出 8-12 条参考文献
2. 包括教材、期刊论文、经典著作
3. 严格采用 GB/T 7714-2015 格式
4. 中英文文献混合
5. 只返回参考文献列表"""


class WriterAgent(BaseAgent):
    """论文生成智能体 - 将 pipeline 结果整合为标准数学建模论文。"""

    def __init__(self) -> None:
        super().__init__(role="数学建模论文写作专家")

    def run(self, summary: dict, feedback: str = "", feedback_by_section: dict | None = None) -> dict:
        """输入 pipeline summary，生成完整论文 Markdown。

        Args:
            summary: pipeline 汇总字典，包含 sub_problems, algorithms, models, executions
            feedback: 可选，质量审核完整反馈（上一轮未通过时），注入各章节 prompt。
            feedback_by_section: 可选，按章节分组的反馈 {章节: 问题清单}，
                      存在时按章节精准注入，否则退化为整体注入 feedback。

        Returns:
            {"status": "ok"|"error", "paper_path": str, "content": str, "error": str|None}
        """
        self.on_start()
        temperature = get("writer.temperature", 0.3)
        max_retries = get("writer.max_retries", 2)
        max_workers = get("writer.max_workers", 4)

        # feedback: 完整反馈文本；feedback_by_section: {章节: 该章节需改的问题}
        # 若提供按章节反馈，则按章节精准注入；否则退化为整体注入
        feedback_by_section = feedback_by_section or {}

        def _fb_block(*chapter_names: str) -> str:
            """为该章节组合反馈块。

            有按章节反馈时：每个章节取"该章节专属问题"，缺失则退化到"全文性问题"；
            否则退化为整体注入 feedback（仅一份）。
            """
            blocks = []
            if feedback_by_section:
                for name in chapter_names:
                    part = feedback_by_section.get(name) or feedback_by_section.get("全文") or ""
                    if part:
                        blocks.append(part)
            elif feedback and feedback.strip():
                blocks.append(feedback.strip())
            if not blocks:
                return ""
            return (
                "\n\n【上一轮质量审核反馈——必须逐条修正，并在修改后的文本中体现】\n"
                + "\n".join(blocks)
            )

        sub_problems = summary.get("sub_problems", [])
        algorithms = summary.get("algorithms", {})
        models = summary.get("models", [])
        executions = summary.get("executions", [])
        problem_text = self._read_problem(summary.get("problem_path", ""))

        if not sub_problems or not algorithms:
            return {"status": "error", "paper_path": "", "content": "", "error": "无子问题或算法数据"}

        # 组装算法信息文本
        algo_lines = "\n".join(f"- {sp}: {algorithms.get(sp, '未确定')}" for sp in sub_problems)
        # 保序去重 + 过滤 None（set 顺序跨运行不稳定，None 会导致 join 崩溃）
        algo_set = "、".join(dict.fromkeys(v for v in algorithms.values() if v))

        # 组装执行结果摘要
        try:
            exec_summary = self._build_exec_summary(executions, sub_problems)
        except Exception as e:
            self.logger.error(f"组装执行结果摘要失败，降级处理: {e}")
            exec_summary = "（执行结果摘要组装失败）"
        # 参考真值仅在【重写轮】（存在审核反馈）时注入：
        # 首轮注入会让 LLM 直接把真值抄进正文，掩盖求解结果错误——数据审核
        # 必须首轮对照真实求解结果，发现矛盾后重写轮再给真值修正。
        if feedback and feedback.strip():
            exec_summary = self._append_verified_refs(exec_summary, summary)

        sections: dict[str, str] = {}
        warnings: list[str] = []

        # ── 并行生成独立章节 ──────────────────────────────────
        self.logger.info("并行生成独立章节（摘要/重述/分析/假设/符号/评价）...")
        independent_tasks = {
            "abstract": PROMPT_ABSTRACT.format(
                problem_text=problem_text[:1500],
                sub_algorithms=algo_lines,
                exec_summary=exec_summary,
                abstract_guide=ABSTRACT_GUIDE,
            ) + _fb_block("摘要"),
            "restatement": PROMPT_PROBLEM_RESTATEMENT.format(
                problem_text=problem_text[:2000],
            ) + _fb_block("问题重述"),
            "analysis": PROMPT_PROBLEM_ANALYSIS.format(
                problem_text=problem_text[:1200],
                sub_problems="\n".join(f"{i+1}. {sp}" for i, sp in enumerate(sub_problems)),
                sub_algorithms=algo_lines,
            ) + _fb_block("问题分析"),
            "assumptions": PROMPT_ASSUMPTIONS.format(
                problem_text=problem_text[:1200],
                sub_problems="\n".join(f"- {sp}" for sp in sub_problems),
            ) + _fb_block("模型假设"),
            "symbols": PROMPT_SYMBOLS.format(
                problem_text=problem_text[:800],
                algorithms=algo_set,
            ) + _fb_block("符号说明"),
            "evaluation": PROMPT_EVALUATION.format(
                problem_text=problem_text[:800],
                algorithms=algo_set,
                evaluation_guide=EVALUATION_GUIDE,
            ) + _fb_block("模型评价与推广"),
        }

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._gen_section, prompt, temperature, max_retries): name
                for name, prompt in independent_tasks.items()
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    sections[name] = future.result()
                except Exception as e:
                    self.logger.error(f"生成 {name} 失败: {e}")
                    sections[name] = "（生成失败，请手动补充）"
                    warnings.append(f"章节「{name}」生成失败: {e}")

        # ── 并行生成模型建立与求解（每个子问题独立） ────────────
        self.logger.info("并行生成模型建立与求解章节...")
        model_tasks: dict[int, str] = {}
        for i, sp in enumerate(sub_problems):
            model_data = models[i] if i < len(models) else {}
            if not isinstance(model_data, dict):
                model_data = {}
            execution = executions[i] if i < len(executions) else {}
            if not isinstance(execution, dict):
                execution = {}

            math_model = model_data.get("math_model", "（暂无）")
            exec_output = self._build_model_exec_summary(execution)
            # 重写轮：模型章节必须同时看到参考真值——否则 LLM 在"防编造铁律"
            # 约束下不敢用真值替换执行结果中的错误值（实测 -64.53 三轮回改不掉）
            if feedback and feedback.strip():
                exec_output = self._append_verified_refs(exec_output, summary)

            model_tasks[i] = PROMPT_MODEL_SECTION.format(
                sub_problem=sp,
                algorithm=algorithms.get(sp, "未确定"),
                math_model=self._smart_truncate(math_model, 3000),
                execution_output=self._smart_truncate(exec_output, 2000),
                model_section_guide=MODEL_SECTION_GUIDE,
            ) + _fb_block("模型建立与求解")
            # 人工策略决定（路径锁定等）注入：论文只呈现人工拍板的路线
            _lock = (summary.get("gate_answers") or {}).get("path_lock")
            if _lock:
                model_tasks[i] += f"\n\n【人工策略决定（必须遵守）】{_lock}"

        model_results: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._gen_section, prompt, temperature, max_retries): idx
                for idx, prompt in model_tasks.items()
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    model_results[idx] = future.result()
                except Exception as e:
                    self.logger.error(f"生成子问题 {idx+1} 失败: {e}")
                    model_results[idx] = "（生成失败，请手动补充）"
                    warnings.append(f"模型章节「子问题{idx+1}」生成失败: {e}")

        model_sections = []
        model_chapter = self._chapter_index("模型建立与求解")
        for i, sp in enumerate(sub_problems):
            text = model_results.get(i, "（生成失败）")
            model_sections.append(f"### {model_chapter}.{i+1} {sp}\n\n{text}")

        # ── 串行生成灵敏度分析（依赖前面的模型信息） ──────────
        self.logger.info("生成灵敏度分析...")
        sensitivity = self._gen_section(
            PROMPT_SENSITIVITY.format(
                sub_algorithms=algo_lines,
                exec_summary=exec_summary,
                sensitivity_guide=SENSITIVITY_GUIDE,
            ) + _fb_block("灵敏度分析"),
            temperature, max_retries,
        )

        # ── 生成标题（LLM 辅助） ──────────────────────────────
        self.logger.info("生成论文标题...")
        title = self._gen_section(
            PROMPT_TITLE.format(problem_text=problem_text[:1000]) + _fb_block("摘要", "全文"),
            temperature, max_retries,
        )
        title = self._clean_title(title)

        # ── 生成参考文献（LLM 辅助，静态映射作为兜底） ────────
        self.logger.info("生成参考文献...")
        references = self._gen_section(
            PROMPT_REFERENCES.format(
                algorithms=algo_set,
                problem_text=problem_text[:500],
            ) + _fb_block("参考文献"),
            temperature, max_retries,
        )
        # 如果 LLM 生成失败，使用静态映射（精确匹配失败标记，避免误判正文内容）
        if references.strip().startswith("（生成失败，请手动补充）"):
            references = self._gen_references_static(algorithms)

        # ── 拼接完整论文 ──────────────────────────────────────
        ch = {name: self._chapter_index(name) for name in [
            "问题重述", "问题分析", "模型假设", "符号说明",
            "模型建立与求解", "灵敏度分析", "模型评价与推广",
        ]}
        paper_parts = [f"# {title}"]

        paper_parts.append(f"## 摘要\n\n{sections.get('abstract', '')}")
        paper_parts.append(f"## {ch['问题重述']}、问题重述\n\n{sections.get('restatement', '')}")
        paper_parts.append(f"## {ch['问题分析']}、问题分析\n\n{sections.get('analysis', '')}")
        paper_parts.append(f"## {ch['模型假设']}、模型假设\n\n{sections.get('assumptions', '')}")
        paper_parts.append(f"## {ch['符号说明']}、符号说明\n\n{sections.get('symbols', '')}")
        paper_parts.append(f"## {ch['模型建立与求解']}、模型建立与求解\n\n" + "\n\n".join(model_sections))
        paper_parts.append(f"## {ch['灵敏度分析']}、灵敏度分析\n\n{sensitivity}")
        paper_parts.append(f"## {ch['模型评价与推广']}、模型评价与推广\n\n{sections.get('evaluation', '')}")
        paper_parts.append(f"## 参考文献\n\n{references}")

        paper = "\n\n---\n\n".join(paper_parts)

        # 后处理：插入可用图表
        paper = self._insert_figures(paper, summary)

        # 后处理：检查引用标记
        paper = self._check_citations(paper, references)

        # 后处理：确定性清理（零 LLM 调用，规则引擎兜底）——
        # 删除本地路径、占位符、元评论等泄漏（防止 LLM 不遵守 prompt 时污染论文）
        paper = self._sanitize_paper(paper)

        # 后处理：标题规范化（零 LLM 调用）——
        # 修复 LLM 自带标题导致的章节重复/层级混乱（历史 bug）：
        #   - LLM 在章节内自带的二级标题降为三级（嵌套在系统章节之下）
        #   - 与当前章节同名的重复标题删除（如"6. 灵敏度分析"出现在"六、灵敏度分析"下）
        #   - LLM 重复输出的子问题标题删除（如"### 5.3 xxx"重复系统"### 五.3 xxx"）
        paper = self._normalize_headings(paper)

        # 保存
        paper_path = self._save_paper(paper)

        status = "ok" if not warnings else "partial"
        result = {
            "status": status,
            "paper_path": str(paper_path),
            "content": paper,
            "error": None,
            "warnings": warnings if warnings else None,
        }
        self.update_state("last_paper", result)
        self.on_finish()
        return result

    # ── 辅助方法 ──────────────────────────────────────────────

    def _gen_section(self, prompt: str, temperature: float = 0.3, retries: int = 2) -> str:
        """调用 LLM 生成论文某一节，带重试。"""
        for attempt in range(retries + 1):
            result = self.think(prompt, system_prompt=SYSTEM_PROMPT, temperature=temperature)
            if result:
                return result.strip()
            if attempt < retries:
                delay = 2 ** attempt
                self.logger.warning(f"LLM 返回空，{delay}s 后重试 ({attempt+1}/{retries})")
                time.sleep(delay)
        self.logger.error(f"生成失败，已重试 {retries} 次")
        return "（生成失败，请手动补充）"

    def _smart_truncate(self, text: str, max_len: int) -> str:
        """智能截断：保留开头和结尾关键内容。"""
        if len(text) <= max_len:
            return text
        if max_len <= 50:
            return text[:max_len]
        head = int(max_len * 0.7)
        tail = max_len - head - 50
        return text[:head] + "\n\n... [中间内容已省略] ...\n\n" + text[-tail:]

    def _clean_title(self, title: str) -> str:
        """清理 LLM 返回的标题。"""
        title = title.strip()
        # 去掉可能的引号、编号
        for ch in ('"', "'", "「", "」", "《", "》"):
            title = title.replace(ch, "")
        # 去掉 "标题：" 等前缀
        for prefix in ("标题：", "标题:", "论文标题：", "论文标题:"):
            if title.startswith(prefix):
                title = title[len(prefix):]
        return title.strip()[:30] or "数学建模论文"

    def _read_problem(self, path: str) -> str:
        """读取赛题文件（支持 txt/docx/pdf，复用 file_parser）。"""
        if not path:
            return ""
        try:
            from utils.file_parser import parse_file
            return parse_file(path)
        except Exception as e:
            self.logger.warning(f"赛题文件读取失败，降级为空文本: {e}")
            return ""

    def _build_model_exec_summary(self, execution: dict) -> str:
        """为模型章节组装精简的执行结果：优先结构化指标，避免塞入原始长输出。"""
        if execution.get("status") != "ok":
            return "（未执行或执行失败）"

        v_status = status_of_execution(execution)
        if not is_verified(v_status):
            return f"（执行成功，但数值{PLACEHOLDER}，不得引用）"

        metrics_json = execution.get("metrics_json", {})
        metrics = execution.get("metrics", {})
        if not isinstance(metrics_json, dict):
            metrics_json = {}
        if not isinstance(metrics, dict):
            metrics = {}
        parts = []
        if metrics_json:
            mj_str = ", ".join(f"{k}={v}" for k, v in list(metrics_json.items())[:15])
            parts.append(f"真实运行指标(metrics.json): {mj_str}")
        elif metrics.get("numbers"):
            num_str = ", ".join(
                f"{k}={v}" for k, v in list(metrics["numbers"].items())[:15]
            )
            parts.append(f"关键数值: {num_str}")
        if metrics.get("key_lines"):
            parts.append("关键输出:")
            parts.extend(f"  {kl}" for kl in metrics["key_lines"][:10])
        if metrics.get("tables"):
            parts.append("数据表格:")
            parts.extend(f"  {t}" for t in metrics["tables"][:5])
        # 图片引用（求解产生的热力图/Pareto 前沿等，论文必须引用）
        figures = execution.get("figures") or []
        if figures:
            parts.append("已生成图表（论文中必须用 ![图X描述](相对路径) 引用并配图标题）:")
            for f in figures[:6]:
                parts.append(f"  ![求解结果图]({f})")
        if parts:
            return "\n".join(parts)

        output = execution.get("output", "")
        return self._smart_truncate(output, 800) if output else "（执行成功，无输出）"

    @staticmethod
    def _append_verified_refs(exec_summary: str, summary: dict) -> str:
        """把人工/独立验证参考真值追加到执行摘要（重写轮专用）。

        用途：数据审核发现论文数值与真值不符后，重写时给 LLM 提供正确值，
        使论文引用值对齐审核参考。首轮不注入（见 run() 调用点）。
        """
        from utils.verification import parse_verified_refs
        verified = summary.get("_verified_results") or ""
        if not isinstance(verified, str) or not verified.strip():
            return exec_summary
        refs = parse_verified_refs(verified)
        if not refs:
            return exec_summary
        ref_lines = "、".join(f"{k}={v:.6g}" for k, v in list(refs.items())[:20])
        return (
            exec_summary
            + "\n\n【人工/独立验证参考真值（仅供核对修正——审核指出论文数值不符时，"
              "将论文中对应的求解数值改为这些真值；不要凭空罗列）】\n"
            + ref_lines
        )

    def _build_exec_summary(self, executions: list[dict], sub_problems: list[str]) -> str:
        """组装代码执行结果摘要，供 Prompt 使用。优先使用结构化指标。"""
        if not executions:
            return "（代码未执行，无执行结果）"

        # 长度对齐：以 sub_problems 为准，不足补空，多余忽略
        if len(executions) < len(sub_problems):
            self.logger.warning(
                f"executions({len(executions)}) 少于 sub_problems({len(sub_problems)})，缺失部分标记为未执行"
            )
            executions = list(executions) + [{}] * (len(sub_problems) - len(executions))
        elif len(executions) > len(sub_problems):
            self.logger.warning(
                f"executions({len(executions)}) 多于 sub_problems({len(sub_problems)})，多余部分忽略"
            )

        lines = []
        for i, (exec_data, sp) in enumerate(zip(executions, sub_problems)):
            if not isinstance(exec_data, dict):
                exec_data = {}
            status = exec_data.get("status", "skipped")
            if status == "ok":
                v_status = status_of_execution(exec_data)
                if not is_verified(v_status):
                    lines.append(f"{i+1}. {sp}: 执行成功，但数值【未验证】{PLACEHOLDER}，不得引用")
                    continue
                metrics = exec_data.get("metrics", {})
                metrics_json = exec_data.get("metrics_json", {})
                # 类型防护：metrics.json 可能被代码写成数组/字符串，非 dict 一律视为无指标
                if not isinstance(metrics_json, dict):
                    metrics_json = {}
                if not isinstance(metrics, dict):
                    metrics = {}
                # 优先：代码真实写入的 metrics.json
                if metrics_json:
                    mj_str = ", ".join(f"{k}={v}" for k, v in list(metrics_json.items())[:15])
                    lines.append(f"{i+1}. {sp}: 执行成功")
                    lines.append(f"   真实运行指标(metrics.json): {mj_str}")
                # 其次结构化指标
                elif metrics.get("numbers"):
                    num_str = ", ".join(f"{k}={v}" for k, v in list(metrics["numbers"].items())[:15])
                    lines.append(f"{i+1}. {sp}: 执行成功")
                    lines.append(f"   关键数值: {num_str}")
                if metrics.get("key_lines"):
                    lines.append(f"   关键输出:")
                    for kl in metrics["key_lines"][:8]:
                        lines.append(f"     {kl}")
                if metrics.get("tables"):
                    lines.append(f"   数据表格:")
                    for t in metrics["tables"][:5]:
                        lines.append(f"     {t}")
                figures = exec_data.get("figures") or []
                if figures:
                    lines.append(f"   已生成图表（论文必须引用）:")
                    for f in figures[:6]:
                        # 只传文件名，不传完整路径（防止 LLM 引用本地时间戳路径）
                        fig_name = Path(str(f)).name
                        lines.append(f"     ![求解结果图](figures/{fig_name})")
                # 如果没有提取到结构化指标，回退到原始输出
                # （有已验证 metrics_json 时禁止回退，避免旧错误值混入）
                if (
                    not metrics_json
                    and not metrics.get("numbers")
                    and not metrics.get("key_lines")
                    and not metrics.get("tables")
                ):
                    output = exec_data.get("output", "")[:800]
                    lines.append(f"{i+1}. {sp}: 执行成功\n   输出摘要: {output}")
            elif status == "error":
                error = exec_data.get("error", "未知错误")[:200]
                lines.append(f"{i+1}. {sp}: 执行失败\n   错误: {error}")
            else:
                lines.append(f"{i+1}. {sp}: 未执行")
        return "\n".join(lines)

    def _insert_figures(self, paper: str, summary: dict) -> str:
        """扫描 figures 目录，将可用图表插入论文的模型求解章节末尾。"""
        from pathlib import Path
        import time
        import shutil

        # 查找最新的 figures 目录
        fig_base = Path("data/results/figures")
        if not fig_base.exists():
            return paper

        fig_dirs = sorted([d for d in fig_base.iterdir() if d.is_dir()])
        if not fig_dirs:
            return paper

        latest_dir = fig_dirs[-1]
        # 并行求解后每个子问题图片在独立子目录 sub{i}/ 下，需递归扫描
        fig_files = (
            sorted(latest_dir.rglob("*.png"))
            + sorted(latest_dir.rglob("*.jpg"))
            + sorted(latest_dir.rglob("*.pdf"))
        )
        if not fig_files:
            return paper

        # 将图片复制到扁平目录 data/results/figures/paper/figN.ext
        # （去除时间戳子目录，论文引用干净的相对路径，PDF 编译时文件必须真实存在）
        flat_dir = Path("data/results/figures/paper")
        flat_dir.mkdir(parents=True, exist_ok=True)
        fig_refs: list[tuple[str, str]] = []  # (显示名, 相对引用路径)
        for i, fig in enumerate(fig_files[:5], 1):
            ext = fig.suffix
            dest = flat_dir / f"fig{i}{ext}"
            try:
                shutil.copy2(fig, dest)
            except OSError:
                continue
            fig_refs.append((f"图{i} {fig.stem}", f"figures/paper/fig{i}{ext}"))

        if not fig_refs:
            return paper

        # 构建图片引用块
        fig_block = "\n\n### 模型结果可视化\n\n"
        for label, ref in fig_refs:
            fig_block += f"![{label}]({ref})\n\n"

        # 在"模型建立与求解"章节末尾插入（在"灵敏度分析"之前）
        # 使用正则匹配：章节标题可能是 "## 灵敏度分析" 或 "## 六、灵敏度分析" 等
        import re
        sensitivity_pattern = r"^##\s*(?:[一二三四五六七八九十]+[、.]?\s*)?灵敏度分析"
        match = re.search(sensitivity_pattern, paper, re.MULTILINE)
        if match:
            insert_pos = match.start()
            paper = paper[:insert_pos] + fig_block + paper[insert_pos:]
        else:
            # 找不到标记，追加到论文末尾（参考文献之前）
            if "## 参考文献" in paper:
                paper = paper.replace("## 参考文献", fig_block + "\n## 参考文献", 1)
            else:
                paper += fig_block

        return paper

    def _check_citations(self, paper: str, references: str) -> str:
        """检查正文中是否有参考文献引用标记，仅警告不自动修复。"""
        import re
        ref_nums = re.findall(r"^\[(\d+)\]", references, re.MULTILINE)
        if not ref_nums:
            return paper

        body = paper.split("## 参考文献")[0] if "## 参考文献" in paper else paper
        citations_found = re.findall(r"\[(\d+)\]", body)

        if not citations_found:
            self.logger.warning(
                "正文中未找到参考文献引用标记。"
                "参考文献列表包含 %s，但正文未引用。"
                "建议在方法首次出现处手动添加引用（如 PCA[3]）。"
                % ", ".join(f"[{n}]" for n in ref_nums[:5])
            )
        else:
            uncited = set(ref_nums) - set(citations_found)
            if uncited:
                self.logger.info(
                    f"部分参考文献未在正文中引用: {', '.join(f'[{n}]' for n in sorted(uncited, key=int))}"
                )

        return paper

    def _gen_references_static(self, algorithms: dict[str, str]) -> str:
        """静态参考文献映射（LLM 生成失败时的兜底）。"""
        algo_list = sorted(set(algorithms.values()))
        refs = [
            "[1] 姜启源, 谢金星, 叶俊. 数学模型(第五版)[M]. 北京: 高等教育出版社, 2018.",
            "[2] 韩中庚. 数学建模方法及其应用(第二版)[M]. 北京: 高等教育出版社, 2009.",
        ]
        algo_refs = {
            "TOPSIS": "[3] Hwang C L, Yoon K. Multiple Attribute Decision Making: Methods and Applications[M]. Springer, 1981.",
            "层次分析法(AHP)": "[4] Saaty T L. The Analytic Hierarchy Process[M]. McGraw-Hill, 1980.",
            "主成分分析(PCA)": "[5] Jolliffe I T. Principal Component Analysis[M]. Springer, 2002.",
            "ARIMA时间序列": "[6] Box G E P, Jenkins G M. Time Series Analysis: Forecasting and Control[M]. Wiley, 2015.",
            "遗传算法": "[7] Goldberg D E. Genetic Algorithms in Search, Optimization, and Machine Learning[M]. Addison-Wesley, 1989.",
            "神经网络": "[8] Bishop C M. Pattern Recognition and Machine Learning[M]. Springer, 2006.",
            "随机森林": "[9] Breiman L. Random Forests[J]. Machine Learning, 2001, 45(1): 5-32.",
            "支持向量机(SVM)": "[10] Vapnik V N. The Nature of Statistical Learning Theory[M]. Springer, 1995.",
            "灰色预测GM(1,1)": "[11] 邓聚龙. 灰色系统理论教程[M]. 武汉: 华中科技大学出版社, 2002.",
            "回归分析": "[12] Seber G A F, Lee A J. Linear Regression Analysis[M]. Wiley, 2003.",
            "熵权法": "[13] Shannon C E. A Mathematical Theory of Communication[J]. Bell System Technical Journal, 1948.",
            "聚类分析": "[14] Kaufman L, Rousseeuw P J. Finding Groups in Data[M]. Wiley, 2005.",
            "线性规划": "[15] Bazaraa M S, Sherali H D, Shetty C M. Nonlinear Programming: Theory and Algorithms[M]. Wiley, 2006.",
            "整数规划": "[16] Wolsey L A. Integer Programming[M]. Wiley, 1998.",
            "粒子群优化": "[17] Kennedy J, Eberhart R. Particle swarm optimization[C]//IEEE ICNN, 1995: 1942-1948.",
            "模拟退火": "[18] Kirkpatrick S, Gelatt C D, Vecchi M P. Optimization by simulated annealing[J]. Science, 1983, 220(4598): 671-680.",
            "XGBoost": "[19] Chen T, Guestrin C. XGBoost: A scalable tree boosting system[C]//KDD, 2016: 785-794.",
        }
        matched = set()
        for algo in algo_list:
            for key, ref in algo_refs.items():
                if key in matched:
                    continue
                # 模糊匹配：算法名包含键名，或键名包含算法名
                if algo in key or key in algo:
                    refs.append(ref)
                    matched.add(key)
                    break
        return "\n".join(refs)

    def _sanitize_paper(self, paper: str) -> str:
        """确定性清理论文文本（规则引擎，零 LLM 调用）。

        处理三类泄漏（均为历史实测发现的 bug）：
        1. 本地路径：`data/...`、`figures/2026...`、`C:\\...`、`results/...` 等
        2. 占位符：「请填入」「待补充」「[XXX]」等
        3. 元评论：「设计思路」「写作思路」「反思」「我之所以…因为…」等

        图片引用例外：`![图N 描述](figures/paper/figN.png)` 是系统生成的合法引用，
        需保留；仅清理游离在正文中的路径。
        """
        import re

        lines = paper.splitlines()
        cleaned: list[str] = []

        # 任何 markdown 图片引用行（![...](...)）都是合法内容，跳过清理
        _img_line = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")
        # 系统生成的扁平图片引用（figures/paper/figN.png）
        _fig_ref = re.compile(r"^!\[[^\]]*\]\(figures/paper/fig\d+\.(?:png|jpg|pdf)\)\s*$")

        _placeholder = re.compile(
            r"(请填入|请填写|待补充|待填写|此处填入|\[占位\]|\[待填\]|\[请填入|\[待补充)"
            r"|(?:TODO|FIXME|TBD)\b"
        )
        _meta_comment = re.compile(
            r"(设计思路|设计说明|写作思路|创作意图|元评论|自我反思|"
            r"我之所以.{0,20}是因为|我考虑到|我选择了.{0,10}因为)"
        )
        # 游离本地路径特征（不含合法的 markdown 图片引用行）
        _local_path = re.compile(
            r"(?:data|figures|results)/[\w\u4e00-\u9fff\-]+"
            r"|[A-Za-z]:\\|/home/|/Users/|C:\\|\.\./|tempfile|tmp/"
        )

        for line in lines:
            # 图片引用行一律保留
            if _img_line.match(line):
                cleaned.append(line)
                continue
            # 1. 占位符整行删除
            if _placeholder.search(line):
                continue
            # 2. 元评论整行删除
            if _meta_comment.search(line):
                continue
            # 3. 游离本地路径整行删除
            if _local_path.search(line):
                continue
            cleaned.append(line)

        # 去除连续空行
        out = "\n".join(cleaned)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out + "\n"

    @staticmethod
    def _strip_heading_num(title: str) -> str:
        """去掉标题开头的编号（中文/阿拉伯数字+分隔符），返回纯标题文本。"""
        import re
        return re.sub(
            r"^[\d一二三四五六七八九十]+[\d.、．\s]*\s*", "", title
        ).strip()

    def _normalize_headings(self, paper: str) -> str:
        """标题规范化（确定性规则引擎，零 LLM 调用）。

        处理 LLM 自带标题导致的章节层级混乱与重复（历史实测 bug）：
        1. 系统章节（## 一、问题重述 / ## 摘要 / ## 参考文献 等）保留为二级；
        2. LLM 在章节内容里自带的二级标题（## 1. xxx / ## 6. 灵敏度分析）降为三级
           （嵌套在系统章节之下）；
        3. 与当前章节名相同的标题直接删除（如"## 6. 灵敏度分析"出现在
           "## 六、灵敏度分析"下是重复标题）；
        4. LLM 重复输出的子问题标题（### 5.3 xxx 重复系统 ### 五.3 xxx）删除。
        """
        import re
        lines = paper.splitlines()
        out: list[str] = []
        current_chapter = ""   # 当前系统章节名（去编号后）
        seen_sub_titles: set[str] = set()  # 系统已生成的子问题标题

        # 系统章节：中文序号 + 章节名（如"一、问题重述"），或摘要/参考文献
        _sys_chapter = re.compile(
            r"^##\s+([一二三四五六七八九十]+)[、.．]\s*(.+?)\s*$"
        )

        for line in lines:
            # 系统章节标题
            m = _sys_chapter.match(line)
            if m:
                current_chapter = m.group(2).strip()
                seen_sub_titles.clear()
                out.append(line)
                continue
            if line.strip() in ("## 摘要", "## 参考文献"):
                current_chapter = "摘要" if "摘要" in line else "参考文献"
                seen_sub_titles.clear()
                out.append(line)
                continue

            # 二级标题（非系统章节）：LLM 自带 → 降为三级
            m2 = re.match(r"^##\s+(.+?)\s*$", line)
            if m2:
                title = m2.group(1).strip()
                bare = self._strip_heading_num(title)
                if current_chapter and bare == current_chapter:
                    continue  # 与当前章节重复（如"6. 灵敏度分析"在"六、灵敏度分析"下）
                # 降为三级；若仍是系统章节名重复（如"模型建立与求解"再次出现）也删除
                if bare in (
                    "问题重述", "问题分析", "模型假设", "符号说明",
                    "模型建立与求解", "灵敏度分析", "模型评价与推广",
                ) and bare == current_chapter:
                    continue
                out.append(f"### {title}")
                continue

            # 三级标题：检测是否重复系统子问题标题（### 五.3 xxx）
            m3 = re.match(r"^###\s+(.+?)\s*$", line)
            if m3:
                title = m3.group(1).strip()
                bare = self._strip_heading_num(title)
                # 系统子问题标题格式：五.3 空间分布分析与建模
                m_sub = re.match(r"^([一二三四五六七八九十]+)[.．]\d+\s+(.+?)$", title)
                if m_sub:
                    seen_sub_titles.add(self._strip_heading_num(title))
                    out.append(line)
                    continue
                # LLM 重复输出同一子问题（5.3 xxx 重复 五.3 xxx）
                if bare in seen_sub_titles:
                    continue
                # 与当前章节名重复（如 ### 7. 模型评价与推广 在 七、... 下）
                if current_chapter and bare == current_chapter:
                    continue
                out.append(line)
                continue

            out.append(line)

        return "\n".join(out)

    def _save_paper(self, content: str) -> Path:
        """保存论文到文件（Markdown + Typst 双格式）。

        .typ 源文件可用 typst CLI 编译为 PDF（竞赛提交格式）：
          typst compile paper_xxx.typ
        转换失败不影响主流程（.md 始终是权威格式）。
        """
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        paper_path = RESULTS_DIR / f"paper_{timestamp}.md"
        paper_path.write_text(content, encoding="utf-8")
        self.logger.info(f"论文已保存: {paper_path} ({len(content)} 字符)")
        # Typst 导出（最佳努力）
        try:
            from utils.typst_export import md_to_typst
            typ_path = paper_path.with_suffix(".typ")
            typ_path.write_text(md_to_typst(content), encoding="utf-8")
            self.logger.info(f"Typst 源文件已保存: {typ_path}")
        except Exception as e:
            self.logger.warning(f"Typst 导出失败（不影响主流程）: {e}")
        return paper_path

    @staticmethod
    def _chapter_index(name: str) -> str:
        """根据章节名返回中文序号（动态映射，避免硬编码）。"""
        mapping = {
            "问题重述": "一", "问题分析": "二", "模型假设": "三",
            "符号说明": "四", "模型建立与求解": "五",
            "灵敏度分析": "六", "模型评价与推广": "七",
        }
        return mapping.get(name, "?")


# ── 兼容函数接口 ──────────────────────────────────────────────


def writer(summary: dict) -> dict:
    """兼容旧的函数调用方式，每次创建新实例避免状态共享。"""
    return WriterAgent().run(summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result_files = sorted(RESULTS_DIR.glob("pipeline_*.json"))
    if not result_files:
        print("未找到 pipeline 结果文件，请先运行 main.py")
    else:
        latest = result_files[-1]
        print(f"加载: {latest.name}")
        summary = json.loads(latest.read_text(encoding="utf-8"))

        agent = WriterAgent()
        result = agent.run(summary)
        print(f"\n状态: {result['status']}")
        print(f"论文: {result['paper_path']}")
        if result.get("error"):
            print(f"错误: {result['error']}")
