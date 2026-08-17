"""质量门控（确定性重构版）：从"LLM 主观打分"改为"确定性校验 + 异常清单"。

根因（第1条）：让 LLM 审 LLM 存在同源幻觉——审核者与被审者共享同一幻觉空间，
只能抓"不一致"，抓不住"不正确"。故三个审核器全部改为**零 LLM 调用**的可复现规则检查：

  LogicAuditor   : 结构化检查清单（论文是否包含必要要素：FFT/判据/不确定度/拟合优度/模型对比/自洽/灵敏度）
  DataAuditor    : 数值比对（论文数字 vs 参考真值，标注偏差，不打分）
  FormatAuditor  : 规则引擎（公式编号/参考文献/图表编号/单位/标题层级/代码块闭合）

输出：通过/不通过 + 异常项清单 + 确定性合规分（0-10，passed项占比）。
分数不再由 LLM 主观给出，同一论文每次审核结果完全一致。
"""
from __future__ import annotations

import re
from typing import Any

from utils.config import get
from utils.verification import parse_verified_refs, status_of_execution, is_verified

SECTIONS = [
    "摘要", "问题重述", "问题分析", "模型假设", "符号说明",
    "模型建立与求解", "灵敏度分析", "模型评价与推广", "参考文献", "全文",
]


def _clamp10(x: float) -> float:
    return max(0.0, min(10.0, round(x, 2)))


# ══════════════════════════════════════════════════════════
# 逻辑审核：结构化检查清单（确定性，无 LLM）
# ══════════════════════════════════════════════════════════
class LogicAuditor:
    """逻辑审核：检查论文是否包含通用建模必备要素，不打分、只列缺失项。

    清单为**题型无关**的通用要素（任何建模论文都应具备）；题型专用要素（如 FFT、
    多光束判据）不入清单，避免对不同题型误罚。
    """

    # (检查项, 判定该要素存在的正则)
    CHECKS = [
        ("摘要", r"摘要|Abstract"),
        ("问题重述/背景", r"问题重述|问题背景|重述"),
        ("模型假设", r"模型假设|假设|assumption"),
        ("模型建立", r"模型建立|数学模型|建立模型|模型构建"),
        ("求解过程与算法", r"求解|算法|步骤|最小二乘|拟合|回归"),
        ("拟合优度/误差指标", r"RMSE|R\^2|R²|误差|残差|AIC|BIC|F检验|MSE|MAE"),
        ("不确定度/置信区间", r"不确定度|置信区间|95%|±|\\pm|标准差"),
        ("结果分析与结论", r"结果分析|结论|讨论"),
        ("模型评价/推广", r"模型评价|灵敏度|稳健性|敏感性|推广"),
    ]

    def run(self, paper: str, summary: dict) -> dict:
        issues = []
        for name, pattern in self.CHECKS:
            if not re.search(pattern, paper, re.IGNORECASE):
                issues.append({
                    "problem": f"论文缺少必要要素：{name}",
                    "severity": "高",
                    "section": "全文",
                })
        # 占位符检测：表格中不应有"请填入"等占位文字
        placeholders = re.findall(r"\[请填入[^\]]*\]|TODO|FIXME|TBD|占位", paper)
        if placeholders:
            issues.append({
                "problem": f"论文包含 {len(placeholders)} 处占位符文字（如「{placeholders[0][:30]}」），需补充实际数值",
                "severity": "高",
                "section": "表格",
            })
        # 负值异常检测：需求量/价格/距离等物理量不应为负
        neg_patterns = re.findall(
            r"(需求量|需求|价格|电价|距离|成本|收入|负荷)\s*[：:=]?\s*-[0-9]+\.?[0-9]*",
            paper
        )
        if neg_patterns:
            issues.append({
                "problem": f"发现 {len(neg_patterns)} 处物理量为负值（如「{neg_patterns[0][:30]}」），需在文中说明处理方式",
                "severity": "中",
                "section": "数值结果",
            })
        # 子问题失败检查：执行失败的子问题对应章节无真实数值支撑。
        # 存在性正则查不出这类"结构齐全但结果缺失"的论文（实测 Q4 失败
        # 时逻辑分 8.89 照常通过门控）——失败的求解无法靠重写论文修复，
        # 必须列为高严重度问题提示人工重跑求解
        execs = summary.get("executions") or []
        failed = [
            e for e in execs
            if isinstance(e, dict) and e.get("status") == "error"
        ]
        if failed:
            names = "；".join(
                (e.get("sub_problem", "") or "")[:20] for e in failed
            )
            issues.append({
                "problem": (
                    f"{len(failed)}/{len(execs)} 个子问题执行失败（{names}），"
                    "对应章节无真实数值支撑。此问题无法通过论文重写修复，"
                    "需人工检查失败原因（依赖缺失/数据契约/模型规模）后重跑求解"
                ),
                "severity": "高",
                "section": "全文",
            })
        score = _clamp10((len(self.CHECKS) - len(issues)) / len(self.CHECKS) * 10)
        return {
            "score": score,
            "issues": issues,
            "suggestions": [f"请修正：{i['problem']}" for i in issues],
            "auditor": "logic",
        }


# ══════════════════════════════════════════════════════════
# 数据审核：只做数值比对，参照真值，不打分
# ══════════════════════════════════════════════════════════
# 内部自洽检查：参与比对的指标键（含"总/最优/最终/最小"等总量词，
# 或以 距离/成本/惩罚/函数值/阈值 结尾）——排除"净需求/容量/车辆"这类
# 每站点一个值的多值指标，避免把站点数据表误报为矛盾
_CONSISTENCY_KEYS = re.compile(
    r"[\u4e00-\u9fff]{0,8}?(?:总|最优|最终|最小|最大)[\u4e00-\u9fff]{0,8}"
    r"(?:距离|成本|惩罚|函数值|阈值|车辆数|装卸量|调度量|路线|路径|需求)"
    r"|[\u4e00-\u9fff]{1,8}(?:距离|成本|惩罚|函数值|阈值)"
)


def _check_internal_consistency(paper: str) -> list[str]:
    """论文内部数值自洽：同一指标键出现多个不同数值 → 矛盾。

    不依赖人工真值，拦截"总行驶距离 46.69 与 51.15 并存"这类
    多子问题结果拼装矛盾（b2025 与共享单车题实测均出现）。
    标量与列表分开比较：同一列表重复出现（摘要/结论各抄一遍）不算矛盾。
    """
    body = paper.split("## 参考文献")[0]
    scalar_pairs: dict[str, list[float]] = {}
    list_pairs: dict[str, list[tuple]] = {}

    # 列表：如 "最终车辆数 [20, 7, 22, ...]" / "卡车路线：0-1-3-4-6-8-7-5-2-0"
    list_pat = re.compile(
        r"([\u4e00-\u9fff]{2,16}?)\s*[：:为是=]?\s*[\[【（(]\s*"
        r"(-?\d+(?:\.\d+)?(?:\s*[,，、\s]\s*-?\d+(?:\.\d+)?){3,})"
    )
    for m in list_pat.finditer(body):
        key = m.group(1)
        if not _CONSISTENCY_KEYS.fullmatch(key):
            continue
        vals = tuple(float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(2)))
        list_pairs.setdefault(key, []).append(vals)

    # 标量：键 + 数值，如 "总行驶距离 51.15 km" / "总行驶距离51.15" / "总成本为 51.1536"
    # 分隔符支持 空格/中文冒号/为/是/=/| 竖线（表格 "| 总行驶距离 | 46.693 |"），
    # 也允许 0 个分隔符（摘要里 "总行驶距离51.15" 键值直接相连）
    pat = re.compile(
        r"([\u4e00-\u9fff]{2,16}?)\s*[\s：:为是=|\uFF5C]*\s*"
        r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    )
    for line in body.splitlines():
        # 摘要行常同时含列表（"最终车辆数为[20,7,...]，总行驶距离51.15 km"），
        # 只剔除方括号字符（列表由 list_pat 处理），不能跳过整行
        for m in pat.finditer(line.replace("[", " ").replace("]", " ")):
            key = m.group(1)
            if not _CONSISTENCY_KEYS.fullmatch(key):
                continue
            try:
                v = float(m.group(2))
            except ValueError:
                continue
            scalar_pairs.setdefault(key, []).append(v)

    issues: list[str] = []
    for key, vals in scalar_pairs.items():
        if len(vals) < 2:
            continue
        uniq = sorted({round(v, 4) for v in vals})
        if len(uniq) < 2:
            continue
        base = max(abs(uniq[-1]), abs(uniq[0]), 1e-9)
        if abs(uniq[-1] - uniq[0]) / base > 0.02:  # 相对偏差 > 2%
            issues.append(
                f"论文内部数值不自洽：「{key}」出现多个不同值 {uniq[:6]}"
                "（多子问题结果拼装矛盾，需统一为同一来源）"
            )
    for key, lists in list_pairs.items():
        if len(lists) < 2:
            continue
        uniq = list({lst for lst in lists})
        if len(uniq) < 2:
            continue
        issues.append(
            f"论文内部数值不自洽：「{key}」出现多个不同取值 {[list(l) for l in uniq[:3]]}"
            "（多子问题结果拼装矛盾，需统一为同一来源）"
        )
    return issues


class DataAuditor:
    """数据审核：论文内部自洽检查（始终） + 与参考真值比对（有真值时）。"""

    def run(self, paper: str, summary: dict) -> dict:
        tol = float(get("audit.data_tolerance", 0.02))
        # 提取论文数值（含科学计数法，如 2.82e-24）。预处理剔除无关数字噪声：
        #  - 参考文献区域（年份）
        #  - 括号公式编号 (4.1)
        #  - LaTeX 上标（cm^{-1} 的 -1、e^{-2iδ} 的 -2，会被负值硬伤检测误报）
        #  - 数字-数字 区间/编号（表 7-1、[1-2]、界面（1-2）），连字符拆成空格
        body = paper.split("## 参考文献")[0]
        body = re.sub(r"\(\s*\d+(?:\.\d+)?\s*\)", " ", body)
        body = re.sub(r"\^\{-?\d+(?:\.\d+)?[^}]*\}", " ", body)
        body = re.sub(r"\d+-\d+", lambda m: m.group(0).replace("-", " "), body)
        # 负百分比（-10% / $-10\%$ 灵敏度幅度）是"下降幅度"而非物理量符号错误，去掉负号
        body = re.sub(r"-(\d+(?:\.\d+)?\\?%)", r"\1", body)
        paper_floats = [float(m) for m in re.findall(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", body)]
        # 负值硬伤检测的候选：按行提取，跳过含 % 的行——灵敏度表格的变化幅度列
        # （-4.76 等）所在行必有 $+5\%$ 之类的百分比标记，负物理量行（-64.53 μm）没有。
        # 另跳过"正负配对"行（+5.0 / -5.00 绝对值相等）：灵敏度表的变化输入/输出成对
        # 出现且不带 % 号（表头注明），不是物理量符号错误。不能用章节过滤：LLM 可能
        # 把求解表格放进"灵敏度分析"章节。
        neg_candidates: list[float] = []
        for line in body.splitlines():
            if "%" in line or "\\%" in line:
                continue
            nums = [float(m) for m in re.findall(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", line)]
            negs = [n for n in nums if n < 0]
            if not negs:
                continue
            positives = {abs(n) for n in nums if n > 0}
            for n in negs:
                if not any(abs(abs(n) - p) < 1e-9 for p in positives):
                    neg_candidates.append(n)

        # ── 论文内部自洽检查（不依赖真值，始终运行）──
        contradictions = _check_internal_consistency(paper)

        # ── 与参考真值比对（无真值时跳过比对，内部自洽矛盾仍参与评分）──
        refs = self._extract_refs(summary)
        if refs:
            found = 0
            neg_conflicts: dict[float, tuple[str, float]] = {}  # 负值 v -> (最近的键, ref)
            for key, ref in refs.items():
                ref_abs = max(abs(ref), 1e-6)
                matched = any(abs(v - ref) <= ref_abs * tol for v in paper_floats)
                if matched:
                    found += 1
                else:
                    # 未命中真值：找论文中与 ref 最近的数值；偏差超过容差且同数量级
                    # （比值 0.1~10）一律标记。旧逻辑只查 [tol, 10*tol] 窗口，偏差 >20%
                    # 的大错误反而无声放行。附建议修正值，给重写 LLM 明确指令。
                    if paper_floats:
                        v = min(paper_floats, key=lambda x: abs(x - ref))
                        ratio = v / ref_abs
                        if abs(v - ref) > ref_abs * tol and 0.1 <= ratio <= 10:
                            contradictions.append(
                                f"{key}={ref:.4g} vs 论文最近值 {v:.4g}"
                                f"（偏差{abs(v - ref) / ref_abs * 100:.1f}%，"
                                f"建议修正为 {ref:.4g}）"
                            )
                    continue
                # 硬伤检测：论文已引用真值（matched）时，仍检查是否存在**负值**错误。
                # 物理量真值为正、论文中出现同数量级的负值（如 -64.53 vs 7.581）是
                # 符号/公式硬伤，即使论文同时抄了真值也必须标记，不能被 found 掩护。
                # 候选已排除含 % 的行（变化幅度）；窗口 [0.5, 10] 排除 -1（cm^{-1} 上标、
                # 表 7-1 编号、[1-2] 文献区间等小量噪声）。
                for v in neg_candidates:
                    if (
                        v < 0 < ref
                        and abs(v - ref) > ref_abs * tol
                        and 0.5 <= abs(v) / ref_abs <= 10
                    ):
                        # 每个负值只报与【最接近真值】的一条矛盾（负值常同时与多个
                        # 同量级真值冲突，报多条会让重写 LLM 不知道该改成哪个值）
                        cur = neg_conflicts.get(v)
                        if cur is None or abs(v - ref) < abs(v - cur[1]):
                            neg_conflicts[v] = (key, ref)
                        break
            for v, (key, ref) in neg_conflicts.items():
                ref_abs = max(abs(ref), 1e-6)
                contradictions.append(
                    f"{key}={ref:.4g} vs 论文负值 {v:.4g}"
                    f"（疑似符号错误，建议修正为 {ref:.4g}）"
                )
        else:
            found = 0

        if not refs and not contradictions:
            return {
                "score": None,
                "issues": [{"problem": "【已跳过】无参考真值且论文内部数值自洽，"
                                      "数据审核不参与评分。",
                            "severity": "中", "section": "全文"}],
                "suggestions": [],
                "auditor": "data",
                "skipped": True,
            }

        issues: list[dict] = []
        if contradictions:
            issues.append({
                "problem": "存在疑似数值矛盾：" + "；".join(contradictions[:3]),
                "severity": "高", "section": "模型建立与求解",
            })
        if refs:
            ratio = found / max(len(refs), 1)
            if ratio < 0.3:
                issues.append({
                    "problem": f"论文仅反映 {found}/{len(refs)} 个求解关键值，与求解结果脱节",
                    "severity": "高", "section": "模型建立与求解",
                })
        score = _clamp10(10.0 - 3.0 * len(issues))
        return {
            "score": score,
            "issues": issues,
            "suggestions": [f"请核对：{i['problem']}" for i in issues],
            "auditor": "data",
            # 数值一致性验收明细（供 verify_report 使用）
            "refs_total": len(refs),
            "refs_found": found,
            "contradictions": contradictions,
            "ref_keys": list(refs.keys()),
        }

    @staticmethod
    def _extract_refs(summary: dict) -> dict[str, float]:
        """提取参考真值：仅人工/独立验证结果（_verified_results）。

        设计意图（DESIGN_数值可靠性改造.md）：
          数据审核优先级 = 人工值(verified_human) > verified_metrics > 缺省跳过。
        verified_metrics 只是"代码真实运行"的状态标记，**不作为审核参考**——
        把它当参考会把"论文未引用某次运行的输出"误判为矛盾，且多子问题各自
        给出不同最优解（合法多解）时审核标准不可达，重写永远无法通过。
        无人工真值时数据审核跳过（不评分，逻辑/排版照常）。
        """
        verified = summary.get("_verified_results") or ""
        if not isinstance(verified, str):
            return {}
        return parse_verified_refs(verified)


# ══════════════════════════════════════════════════════════
# 排版审核：规则引擎（确定性，无 LLM）
# ══════════════════════════════════════════════════════════
class FormatAuditor:
    """排版审核：正则规则检查格式规范，不靠 LLM。"""

    def run(self, paper: str, summary: dict) -> dict:
        issues = []
        # 1. 公式编号：存在形如 (数字.数字) 的编号，且无重复
        nums = re.findall(r"\(\s*\d+(?:\.\d+)?\s*\)", paper)
        if not nums:
            issues.append({"problem": "未检测到公式编号（如 (4.1)）", "severity": "中", "section": "全文"})
        elif len(nums) != len(set(nums)):
            issues.append({"problem": "存在重复公式编号", "severity": "中", "section": "全文"})

        # 2. 参考文献：存在 [n] 引用，且含年份（19xx/20xx）
        refs = re.findall(r"\[\d+\]", paper)
        if not refs:
            issues.append({"problem": "正文缺少参考文献引用标记 [n]", "severity": "高", "section": "参考文献"})
        if not re.search(r"19\d{2}|20\d{2}", paper):
            issues.append({"problem": "参考文献中未检测到年份", "severity": "中", "section": "参考文献"})

        # 3. 图表编号与标题
        tables = re.findall(r"表\s?\d+", paper)
        figs = re.findall(r"图\s?\d+", paper)
        if not tables:
            issues.append({"problem": "未检测到表格（表N）", "severity": "中", "section": "全文"})
        if not figs:
            issues.append({"problem": "未检测到插图（图N）", "severity": "中", "section": "全文"})

        # 4. 单位规范：μm 使用规范，检测裸 um
        if re.search(r"(?<![μu])\bum\b", paper):
            issues.append({"problem": "存在不规范单位写法 'um'（应写 μm）", "severity": "低", "section": "全文"})
        if not re.search(r"μm", paper):
            issues.append({"problem": "未检测到 μm 单位写法", "severity": "低", "section": "全文"})

        # 5. 标题层级
        if not re.search(r"^## ", paper, re.MULTILINE):
            issues.append({"problem": "缺少二级标题（##）", "severity": "高", "section": "全文"})
        if not re.search(r"^### ", paper, re.MULTILINE):
            issues.append({"problem": "缺少三级标题（###）", "severity": "中", "section": "全文"})

        # 6. 代码块闭合
        if paper.count("```") % 2 != 0:
            issues.append({"problem": "Markdown 代码块未闭合（``` 数量为奇数）", "severity": "中", "section": "全文"})

        total = 6
        # 计算通过项：上述每个问题归为一个"检查族"，存在高严重度问题的族计为未通过
        high = sum(1 for i in issues if i["severity"] == "高")
        score = _clamp10((total - high) / total * 10)
        return {
            "score": score,
            "issues": issues,
            "suggestions": [f"请修正：{i['problem']}" for i in issues],
            "auditor": "format",
        }


# ══════════════════════════════════════════════════════════
# 总审：聚合三审，输出 通过/不通过 + 异常清单
# ══════════════════════════════════════════════════════════
class QualityGateAgent:
    """质量门控总审（确定性）。保留 scores/overall 字段以兼容流水线，
    但分数为合规分（可复现），核心输出为异常项清单。"""

    def __init__(self) -> None:
        self.logic = LogicAuditor()
        self.data = DataAuditor()
        self.format = FormatAuditor()

    def run(self, paper: str, summary: dict) -> dict:
        threshold = float(get("auditor.score_threshold", 8.0))
        overall_threshold = float(get("auditor.overall_threshold", 9.0))

        logic_res = self.logic.run(paper, summary)
        data_res = self.data.run(paper, summary)
        format_res = self.format.run(paper, summary)

        data_score = None if data_res.get("skipped") else data_res["score"]
        scores = {"logic": logic_res["score"], "data": data_score, "format": format_res["score"]}
        active = {k: v for k, v in scores.items() if v is not None}

        if active:
            overall = round(sum(active.values()) / len(active), 2)
        else:
            overall = 0.0
        passed = (
            all(v > threshold for v in active.values())
            and overall > overall_threshold
        )

        # ── 硬性红线：占位符/未填充数值直接不通过（不能靠分数稀释混过）──
        # 占位符意味着论文存在未完成内容，任何数量都视为未交付，必须重写
        hard_placeholders = re.findall(
            r"\[请填入[^\]]*\]|\[具体[^\]]*\]|TODO|FIXME|TBD|图X\.|表X\.|图 ?X\d|表 ?X\d",
            paper,
        )
        if hard_placeholders:
            passed = False
            logic_res["issues"].append({
                "problem": f"论文包含 {len(hard_placeholders)} 处未填充占位符"
                           f"（如「{hard_placeholders[0][:40]}」），硬性红线：必须全部补充实际数值后才能通过",
                "severity": "高",
                "section": "全文",
            })
            logic_res["score"] = _clamp10(min(logic_res["score"], 5.0))

        details = {"logic": logic_res, "data": data_res, "format": format_res}
        feedback = self._build_feedback(active, details, threshold)
        feedback_by_section = self._feedback_by_section(details)

        return {
            "passed": passed,
            "scores": active,
            "overall": overall,
            "overall_threshold_used": overall_threshold,
            "data_skipped": bool(data_res.get("skipped")),
            "details": details,
            "feedback": feedback,
            "feedback_by_section": feedback_by_section,
        }

    @staticmethod
    def _build_feedback(scores: dict, details: dict, threshold: float) -> str:
        """汇总异常项清单为反馈文本。"""
        name_map = {"logic": "逻辑", "data": "数据", "format": "排版"}
        prefix = {"logic": "L", "data": "D", "format": "F"}
        parts = []
        for key, name in name_map.items():
            res = details[key]
            score = scores.get(key)
            issues = res.get("issues", [])
            if score is None:
                parts.append(f"【{name}审核 已跳过】")
            else:
                passed_txt = "通过" if score > threshold else "未通过"
                parts.append(f"【{name}审核 {passed_txt}（合规分 {score}）共{len(issues)}个异常】")
            for idx, iss in enumerate(issues, 1):
                parts.append(
                    f"  - [{prefix[key]}{idx}] ({iss.get('severity', '中')}"
                    f"|{iss.get('section', '全文')}) {iss.get('problem', '')}"
                )
        return "\n".join(parts)

    @staticmethod
    def _feedback_by_section(details: dict) -> dict[str, str]:
        """按章节聚合异常项（兼容 Writer 按章节注入反馈）。"""
        prefix = {"logic": "L", "data": "D", "format": "F"}
        all_issues = []
        for key, res in details.items():
            if res.get("skipped"):
                continue
            for idx, iss in enumerate(res.get("issues", []), 1):
                all_issues.append({**iss, "code": f"[{prefix[key]}{idx}]"})

        by_section: dict[str, list] = {s: [] for s in SECTIONS}
        global_issues = [i for i in all_issues if i.get("section") == "全文"]
        for iss in all_issues:
            sec = iss.get("section", "全文")
            by_section.setdefault(sec, []).append(iss)

        result: dict[str, str] = {}
        for sec in SECTIONS:
            issues = by_section.get(sec, []) + global_issues
            seen = set()
            dedup = []
            for iss in issues:
                if iss["code"] in seen:
                    continue
                seen.add(iss["code"])
                dedup.append(iss)
            if dedup:
                lines = [f"【{sec}需修改的异常】"]
                lines += [f"  - {i['code']} ({i.get('severity','中')}) {i.get('problem','')}"
                          for i in dedup]
                result[sec] = "\n".join(lines)
        return result
