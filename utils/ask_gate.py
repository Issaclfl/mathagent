"""策略门控（ask_gate）：在建模策略分岔口强制暂停，向人工请示后继续。

背景：全自动流水线只能检查"代码是否崩/格式是否对"，无法判断"数学模型
建得蠢不蠢"（如把分步 TSP 与联合 IRP 混用、用启发式做精确灵敏度、路径打架）。
在三个关键分岔口让 AI 向人工提问，人工一句话拍板即可锁死结构性错误，
避免"全自动跑偏 → 重跑"的无限循环（省 80% 无效生成）。

三个门控点（config.hil.gates 控制开关）：
  modeling_strategy  建模前：分步建模 vs 联合建模（锁"不建废模"）
  sensitivity_solver 灵敏度分析前：精确求解器 vs 启发式（锁"不乱用算法"）
  path_lock          求解后：最优路径锁定（锁"不自相矛盾"）

机制（复用 HIL 断点续跑）：
  暂停点生成 ask_<ts>.json（含问题/选项/上下文）→ 存 checkpoint → 退出
  人工填写 answer → python hil_resume.py ask_<ts>.json 续跑
  答案注入 summary["gate_answers"]，Builder/Writer prompt 携带约束。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from utils.config import get

GATE_DIR = Path(__file__).resolve().parent.parent / "data" / "hil"

GATES = ("modeling_strategy", "sensitivity_solver", "path_lock")

# 题型 → 门控1 兜底问题模板（LLM 生成失败时使用）
_FALLBACK_QUESTIONS = {
    "优化决策": (
        "我识别到该问题本质是带装卸的库存路径联合优化（IRP）。现有两种拆解方案：\n"
        "方案A（分步）：先单独求库存（LP/数量优化），再固定库存求路径（TSP），"
        "最后联合优化（MILP）；\n"
        "方案B（直接）：跳过中间分步结果，直接建立数量-路径联合优化 MILP，"
        "以联合精确解作为全篇唯一基准。\n"
        "方案A 存在'后验论证'学术风险，中间结果若劣于联合解则无引用价值。"
        "是否授权采用方案B，删除冗余的分步子问题？"
    ),
    "物理推导": (
        "物理推导题的核心数值（参数反演结果）没有独立验证来源。"
        "是否授权：求解后暂停，由人工核对/填写关键数值（HIL 确认）后再生成论文？"
    ),
    "数据预测": (
        "预测模型的参数与结果无独立真值。是否授权：求解后暂停，"
        "由人工确认预测数值与模型选择后再生成论文？"
    ),
    "综合评价": (
        "评价类模型的权重/得分无独立真值。是否授权：求解后暂停，"
        "由人工确认评价结果后再生成论文？"
    ),
}

_FALLBACK_QUESTIONS_SENSITIVITY = (
    "灵敏度分析需跑多组参数。可用求解器：\n"
    "求解器X（精确求解，如 MILP/线性规划）：小规模下秒级出结果，确定且单调；\n"
    "求解器Y（启发式，如模拟退火/遗传）：结果随机波动，无法给出严谨的权衡曲线。\n"
    "从'优秀论文'角度应强制使用精确求解器。是否确认：灵敏度分析强制调用精确求解器，"
    "禁止使用任何启发式算法？"
)

_FALLBACK_QUESTIONS_PATH = (
    "已求得最优路径（见上下文输出）。为防报告中出现多条路径混淆、"
    "数值不自洽：请确认最终'最优路线'锁定为上下文中的这一条，"
    "其他等价/等距路径一律忽略，论文中只出现这一条完整路径及对应结果？"
)


def gate_enabled(gate: str) -> bool:
    """该门控是否开启（config.hil.gates.<name>，默认开启）。"""
    if gate not in GATES:
        return False
    gates = get("hil.gates", {}) or {}
    return bool(gates.get(gate, True))


def gates_enabled() -> list[str]:
    return [g for g in GATES if gate_enabled(g)]


def _gen_question(gate: str, problem_type: str, context: str,
                  llm: callable | None = None) -> str:
    """生成门控问题文本：优先 LLM（带上下文），失败回退模板。"""
    if llm is not None:
        try:
            prompt = (
                "你是数学建模策略顾问。基于以下上下文，向用户提出一个"
                "【建模策略选择】问题（含 2-3 个方案及各自利弊），用户回答后将决定后续建模方向。\n"
                f"门控类型: {gate}\n题型: {problem_type}\n上下文:\n{context[:800]}\n\n"
                "要求：问题用第一人称，给出方案对比与推荐，结尾明确询问是否授权。"
                "只返回问题文本，不要额外内容。"
            )
            q = llm(prompt)
            if q and len(q.strip()) > 20:
                return q.strip()
        except Exception:
            pass
    if gate == "sensitivity_solver":
        return _FALLBACK_QUESTIONS_SENSITIVITY
    if gate == "path_lock":
        return _FALLBACK_QUESTIONS_PATH
    return _FALLBACK_QUESTIONS.get(problem_type, _FALLBACK_QUESTIONS["优化决策"])


def write_ask_file(gate: str, question: str, context: str,
                   summary: dict, options: list[str] | None = None) -> Path:
    """写出待人工回答的提问文件，返回路径。"""
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    payload = {
        "_hint": f"【{gate} 门控】请阅读 question 并填写 answer（直接写你的决定，"
                 "如：授权方案B，删除分步TSP。可参考 options）。"
                 "保存后运行: python hil_resume.py <本文件路径>",
        "gate": gate,
        "question": question,
        "options": options or [],
        "context": context[:600],
        "answer": "",
    }
    path = GATE_DIR / f"ask_{gate}_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_ask_file(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_answer(summary: dict, ask: dict) -> dict:
    """把人工回答注入 summary["gate_answers"][gate]，供后续阶段约束。"""
    gate = ask.get("gate", "")
    answer = (ask.get("answer") or "").strip()
    if not answer:
        raise ValueError(f"门控 {gate} 未填写 answer")
    answers = summary.setdefault("gate_answers", {})
    answers[gate] = answer
    summary["_gate_confirmed"] = True
    return summary


def gate_answer_text(summary: dict, gate: str) -> str:
    """返回该门控的人工决定文本（供 Builder/Writer prompt 注入），无则空串。"""
    answers = summary.get("gate_answers") or {}
    a = answers.get(gate)
    return f"\n【人工策略决定（必须遵守）】{a}" if a else ""


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("门控开关:", gates_enabled())
