"""评审智能体 - 检查建模/求解结果的合理性，形成反馈闭环。

职责：
1. 规则检查：找出算法未确定、建模失败、求解失败的子问题
2. 一致性检查：算法 ↔ 模型 ↔ 求解结果三者是否匹配
3. LLM 评审：对失败项给出根因分析和改进建议
"""
from __future__ import annotations

from agents.base import BaseAgent

SYSTEM_PROMPT = "你是一位严谨的数学建模评审专家，擅长发现模型、算法与求解结果中的问题，并给出可执行的改进建议。"

REVIEW_PROMPT = """请对以下数学建模任务的求解结果进行评审。

【赛题】
{problem_text}

【子问题与推荐算法】
{sub_algorithms}

【求解情况】
{exec_status}

【发现的问题】
{issues}

【要求】
1. 对每个执行失败的子问题，分析可能的根因（数据缺失、模型不合适、代码错误等）
2. 给出具体的改进建议（可具体到改用哪类算法或调整建模思路）
3. 若存在问题，评估其对整体结论的影响程度（严重/中等/轻微）
4. 【逻辑剪刀·数据血缘追溯——必须执行】
   - 若子问题 B 基于子问题 A（A 是 B 的前置输入），且 A 的误差指标降低
     （宣称"有效"）、B 的最终误差指标却升高 → 判定 A 方法整体无效
   - 禁止"分而治之"：严禁把"降尺度误差降"与"最终预测误差升"放在两段
     各自美化——这是因果断裂
   - 若判定某方法无效，写作者必须将"方法优点"自动改为"方法局限性"，
     并从"高频信息不可恢复"等角度生成不少于200字的失效机理批判
5. 语言精炼、条理清晰，只返回评审意见正文"""


class ReviewerAgent(BaseAgent):
    """评审智能体：对 pipeline 结果进行一致性检查与质量评审。"""

    def __init__(self) -> None:
        super().__init__(role="数学建模评审专家")

    def run(self, summary: dict) -> dict:
        """输入 pipeline summary，返回评审报告。

        Returns:
            {
                "status": "ok" | "issues_found",
                "issues": [{"sub_problem", "error", "last_stderr"}],
                "warnings": [str],
                "review": "LLM 生成的评审意见"
            }
        """
        sub_problems = summary.get("sub_problems", [])
        algorithms = summary.get("algorithms", {})
        models = summary.get("models", [])
        executions = summary.get("executions", [])

        issues: list[dict] = []
        warnings: list[str] = []

        for i, sp in enumerate(sub_problems):
            algo = algorithms.get(sp, "未确定")

            # 算法未确定
            if algo == "未确定":
                warnings.append(f"子问题「{sp[:30]}」算法未确定")

            # 建模失败
            model = models[i] if i < len(models) else {}
            if model.get("status") == "error":
                warnings.append(
                    f"子问题「{sp[:30]}」建模失败: {model.get('error')}"
                )

            # 求解失败
            exec_data = executions[i] if i < len(executions) else {}
            status = exec_data.get("status")
            if status == "error":
                issues.append({
                    "sub_problem": sp,
                    "algorithm": algo,
                    "error": exec_data.get("error", "未知错误"),
                    "last_stderr": (exec_data.get("last_stderr") or "")[:500],
                })
            elif status == "skipped":
                warnings.append(f"子问题「{sp[:30]}」未执行")
            else:
                # 数值合理性检查：成功但指标异常（如 MAE/RMSE 为负）
                bad = self._check_numeric_sanity(exec_data.get("metrics", {}))
                if bad:
                    warnings.append(f"子问题「{sp[:30]}」结果疑似异常: {bad}")

        # 生成执行状态文本
        exec_lines = []
        for i, sp in enumerate(sub_problems):
            exec_data = executions[i] if i < len(executions) else {}
            status = exec_data.get("status", "skipped")
            if status == "ok":
                exec_lines.append(f"{i+1}. {sp} → 求解成功")
            elif status == "error":
                exec_lines.append(
                    f"{i+1}. {sp} → 求解失败: {exec_data.get('error', '')}"
                )
            else:
                exec_lines.append(f"{i+1}. {sp} → 未执行")
        exec_status = "\n".join(exec_lines) if exec_lines else "（无执行记录）"

        # ── 逻辑剪刀：数据血缘追溯（硬编码规则，不依赖 LLM 自觉）──
        # 若"降尺度/中间方法"误差降低、但"最终预测/下游"误差升高 → 中间方法整体无效
        scissors = self._check_logic_scissors(executions)
        for s in scissors:
            issues.append({
                "sub_problem": s["sub_problem"],
                "algorithm": s.get("algorithm", ""),
                "error": s["reason"],
                "last_stderr": "",
                "scissors": True,
            })
            warnings.append(s["reason"])

        issues_text = "\n".join(
            f"- 「{iss['sub_problem'][:30]}」({iss['algorithm']}): "
            f"{iss['error']}\n  错误详情: {iss['last_stderr'][:200]}"
            for iss in issues
        ) or "（无阻塞性问题）"

        # 有失败项时调用 LLM 评审
        if issues:
            prompt = REVIEW_PROMPT.format(
                problem_text=(summary.get("problem_text") or "")[:1500],
                sub_algorithms="\n".join(
                    f"- {sp}: {algorithms.get(sp, '未确定')}" for sp in sub_problems
                ),
                exec_status=exec_status,
                issues=issues_text,
            )
            review = self.think(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.3)
            review = review.strip() or "（评审生成失败，请人工检查）"
        else:
            review = "所有子问题均成功求解，未发现阻塞性问题。"

        report = {
            "status": "issues_found" if issues else "ok",
            "issues": issues,
            "warnings": warnings,
            "review": review,
        }
        self.update_state("review_report", report)
        return report

    @staticmethod
    def _check_numeric_sanity(metrics: dict) -> str | None:
        """检查结构化指标中明显不合理的数值（负值等）。"""
        numbers = metrics.get("numbers", {})
        if not numbers:
            return None
        # 这些指标不应为负
        non_negative = {"MAE", "RMSE", "score", "accuracy", "precision", "recall",
                        "f1", "覆盖率", "满足率", "方差贡献率", "累计", "成本"}
        problems = []
        for key, values in numbers.items():
            if key not in non_negative:
                continue
            for v in values:
                if v < 0:
                    problems.append(f"{key}={v}（负值不合理）")
                    break
        return "; ".join(problems[:3]) if problems else None

    @staticmethod
    def _check_logic_scissors(executions: list[dict]) -> list[dict]:
        """逻辑剪刀：数据血缘追溯（硬编码因果链检查）。

        规则：若子问题中出现"中间方法误差改善 + 下游最终预测误差恶化"的
        因果断裂，则该中间方法应判定为整体无效——禁止"分而治之地美化局部指标"。

        指标角色识别（按关键词，基线优先级最高）：
          - 基线指标：粗网格/基准/baseline/未降尺度/原始/coarse
          - 中间指标：辐照/降尺度/插值/中间/特征/irradiance/kt
          - 最终指标：功率预测/最终/预测/rmse/mae/误差/power
        触发条件：
          1) 存在基线 B0 与最终 B1，且 B1 > B0（最终相对基线恶化）；
             同时存在中间 M，且 M < B0（中间改善）→ 因果断裂。
          2) 无基线时：最终误差 > 中间误差×2 且最终误差 > 0.03 → 可疑断裂。
        """
        BASELINE = ("粗网格", "基准", "baseline", "未降尺度", "原始", "coarse")
        INTERMED = ("辐照", "降尺度", "插值", "中间", "特征", "irradiance", "kt")
        FINAL = ("功率预测", "最终", "预测", "rmse", "mae", "误差", "err", "power")

        def role(key: str):
            k = str(key).lower()
            if any(t in k for t in BASELINE):
                return "baseline"
            if any(t in k for t in INTERMED):
                return "intermediate"
            if any(t in k for t in FINAL):
                return "final"
            return None

        metric_map: dict[str, dict] = {}
        for e in executions:
            sp = e.get("sub_problem", "")
            if not sp:
                continue
            combined = {}
            mj = e.get("metrics_json") or {}
            m = e.get("metrics", {}).get("numbers", {})
            if isinstance(mj, dict):
                combined.update(mj)
            if isinstance(m, dict):
                for k, v in m.items():
                    combined[k] = v[0] if isinstance(v, list) and v else v
            metric_map[sp] = combined

        violations = []
        for sp, metrics in metric_map.items():
            errs = {k: v for k, v in metrics.items()
                    if isinstance(v, (int, float)) and v > 0
                    and any(t in str(k).lower() for t in ("err", "rmse", "mae", "误差"))}
            if not errs:
                continue
            r: dict = {role(k): k for k in errs if role(k)}
            base_k, inter_k, fin_k = r.get("baseline"), r.get("intermediate"), r.get("final")
            trigger = None
            if base_k and fin_k:
                b0, b1 = errs[base_k], errs[fin_k]
                if b1 > b0 * 1.2 and b1 > 0.03 and inter_k and errs[inter_k] < b0 * 0.8:
                    trigger = ("中间改善+最终恶化", inter_k, errs[inter_k],
                               fin_k, b1, base_k, b0)
            elif fin_k and inter_k:
                if errs[fin_k] > errs[inter_k] * 2 and errs[fin_k] > 0.03:
                    trigger = ("最终远差于中间", inter_k, errs[inter_k], fin_k, errs[fin_k], None, None)
            if trigger:
                kind, m_k, m_v, f_k, f_v, b_k, b_v = trigger
                desc = f"指标 {m_k}={m_v} 改善，而最终指标 {f_k}={f_v}"
                if b_k:
                    desc += f"（相对基线 {b_k}={b_v} 恶化）"
                violations.append({
                    "sub_problem": sp,
                    "algorithm": "",
                    "reason": (
                        f"【逻辑剪刀】子问题「{sp[:30]}」检测到因果断裂：{desc}。"
                        f"符合'中间方法误差降、下游最终误差升'模式，该中间方法应判定为"
                        f"整体无效。写作者必须将'方法优点'改为'方法局限性'，"
                        f"说明失效机理，严禁分而治之地美化局部指标。"
                    ),
                })
        return violations


# ── 兼容函数接口 ──────────────────────────────────────────────


def reviewer(summary: dict) -> dict:
    """兼容旧的函数调用方式。"""
    return ReviewerAgent().run(summary)
