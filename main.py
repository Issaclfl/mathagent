"""数学建模智能体 - 主程序

串联完整 pipeline：
  协调者(拆题) → 建模者(推荐算法) → 构建者(生成代码) → 求解者(执行修复) → 写作者(生成论文)

用法：
  python main.py                          # 使用默认测试赛题
  python main.py data/my_problem.txt      # 指定赛题文件
  python main.py --until 拆题             # 渐进式：拆解后停止，人工确认再续跑
  python main.py --until 求解             # 渐进式：求解后停止（配合 HIL 数值确认）
  python main.py --resume data/results/pipeline_checkpoint.json  # 断点续跑
  python main.py --skip-solve             # 跳过代码执行（仅生成不运行）
  python main.py --skip-write             # 跳过论文生成
  python main.py --skip-data-check        # 跳过数据前置校验（数据不齐时显式放行）
  python main.py --skip-hil               # 全自动模式：跳过 HIL 数值确认与策略门控
  策略门控（人在环，默认开启）：建模策略 / 灵敏度求解器 / 路径锁定 三处
  会生成 data/hil/ask_*.json 暂停，人工填 answer 后
  python hil_resume.py data/hil/ask_*.json 续跑；config.hil.gates 可单独关闭
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from utils.file_parser import parse_file
from agents.coordinator import CoordinatorAgent
from agents.modeler import ModelerAgent
from agents.builder import BuilderAgent
from agents.solver import SolverAgent, _extract_metrics
from agents.reviewer import ReviewerAgent
from agents.writer import WriterAgent
from agents.audit import QualityGateAgent
from utils.experience import record_from_summary
from utils.config import get
from utils.verified_results import load_verified_results
from utils.manual_solutions import (
    load_manifest,
    find_manual,
    load_manual_code,
    load_manual_math,
)

logger = logging.getLogger("mathagent")

RESULTS_DIR = Path(__file__).parent / "data" / "results"
CHECKPOINT_FILE = RESULTS_DIR / "pipeline_checkpoint.json"

# 运行产物保留策略：results/ 下最多保留 N 份论文产物、M 份执行代码目录
_MAX_PAPER_KEEP = 20
_MAX_CODE_DIRS = 30


def cleanup_old_artifacts() -> None:
    """清理运行产物，防止 data/results 无限堆积（用户痛点：产物不及时清除）。

    策略：
      - paper_*.md / pipeline_*.json / verify_report_*.json：按修改时间保留最新 N 份
      - code/<时间戳>/：保留最新 M 个目录（每目录含 subN.py/ipynb/输出）
      - figures/<时间戳>/：保留最新 M 个目录
    仅删除本进程可写的 results 目录下的内容，不动 data 下的正式数据。
    """
    try:
        if not RESULTS_DIR.exists():
            return
        for pattern, keep in (
            ("paper_*", _MAX_PAPER_KEEP),
            ("pipeline_*.json", _MAX_PAPER_KEEP),
            ("verify_report_*.json", _MAX_PAPER_KEEP),
        ):
            files = sorted(RESULTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[keep:]:
                old.unlink(missing_ok=True)
        for sub in ("code", "figures"):
            subdir = RESULTS_DIR / sub
            if not subdir.is_dir():
                continue
            dirs = sorted(
                (d for d in subdir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            for old in dirs[_MAX_CODE_DIRS:]:
                import shutil
                shutil.rmtree(old, ignore_errors=True)
        # 清理代码执行临时目录（崩溃残留）
        try:
            from agents.solver import cleanup_exec_tmp
            cleanup_exec_tmp()
        except Exception:
            pass
    except Exception as e:
        print(f"  [WARN] 运行产物清理失败: {e}")


def _banner(text: str) -> None:
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


def _step(num: int, text: str) -> None:
    print(f"\n[{num}/7] {text}")


_notify_lock = threading.Lock()


def _notify(progress_callback, stage: str, message: str) -> None:
    """若提供了进度回调，则调用它。

    线程安全：并行求解阶段多个工作线程会同时调用进度回调
    （如 Web 端更新 tasks[task_id]），加锁防止并发读改写丢更新。
    """
    if progress_callback is not None:
        with _notify_lock:
            progress_callback(stage, message)


def _maybe_stop(until: str | None, stage: str, summary: dict, start_time: float) -> bool:
    """渐进式阶段停止：until 指定阶段完成时保存断点并停止，返回 True。

    人工确认节点（渐进式模式）：拆题→确认拆解；求解→确认数值（HIL）；
    论文→终审。每层都站在被确认过的地基上，避免错误积累到最后一锅端。
    """
    if until and stage in until:
        _save_checkpoint(summary, start_time)
        _banner(f"阶段「{stage}」完成，已停止（渐进式模式，等待人工确认）")
        print(f"  断点: {CHECKPOINT_FILE}")
        print(f"  继续: python main.py --resume {CHECKPOINT_FILE}")
        return True
    return False


def _call_llm_simple(prompt: str) -> str:
    """策略门控问题生成用：直接调 LLM（低温度），失败返回空。"""
    from utils.llm_client import call_llm
    return call_llm(prompt, system_prompt="你是数学建模策略顾问。", temperature=0.2)


def _merge_verified_text(*texts: str) -> str:
    """合并多段已验证结果文本，按行去重（保留顺序）。

    HIL 注入的人工值与 CSV 独立验证结果可能同时存在，二者都是参考真值，
    合并后数据审核可同时比对（互不覆盖）。
    """
    seen = set()
    merged: list[str] = []
    for text in texts:
        for line in (text or "").splitlines():
            key = line.strip()
            if key and key not in seen:
                seen.add(key)
                merged.append(key)
    return "\n".join(merged)


def _redline_text(struct: dict | None) -> str:
    """结构诊断 → 建模红线文本（供 Builder 降级重建模复用）。"""
    if not struct:
        return ""
    try:
        from utils.modeling_kb import structure_redline
        return structure_redline(struct)
    except Exception:
        return ""


def _write_verify_report(summary: dict, paper_text: str) -> Path:
    """数值一致性验收报告（9步验收的数值一致性步骤，确定性产物）。

    内容：参考真值总数 / 论文命中数 / 矛盾与负值硬伤清单 / 全部真值键。
    落盘 data/results/verify_report_<ts>.json，供人工终审对照。
    """
    from agents.audit import DataAuditor
    res = DataAuditor().run(paper_text, summary)
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "problem_path": summary.get("problem_path", ""),
        "refs_total": res.get("refs_total", 0),
        "refs_found": res.get("refs_found", 0),
        "ref_keys": res.get("ref_keys", []),
        "contradictions": res.get("contradictions", []),
        "issues": [i["problem"] for i in res.get("issues", [])],
        "score": res.get("score"),
        "note": "数值一致性验收：论文数字与人工/独立验证真值比对结果；"
                "有矛盾项时以真值为准人工复核修正。",
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / f"verify_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_path


def _infer_data_dir(problem_text: str, problem_path: str) -> str:
    """从赛题文本推断数据目录。

    优先级：
      1. 赛题中的 "data/xxx"、"数据目录" 显式路径；
      2. 赛题所在目录递归搜索数据文件（.xlsx/.csv）所在目录——b2025 附件位于
         data/b2025/，直接回退到 "赛题同级 data" 会推断出 data/data（不存在）；
      3. 回退：赛题同目录的 data 子目录。
    """
    import re
    m = re.search(r"(?:data/|数据目录[：:]?\s*)([\w/\-]+)", problem_text)
    if m:
        cand = m.group(1).strip("/")
        return str((Path(problem_path).parent / cand).resolve())
    # 按数据文件搜索候选目录，取离赛题最近的；
    # 仅当赛题明确引用数据文件名（附件N.xlsx / *.csv / 数据目录）时才搜索——
    # 否则会命中其它赛题的数据目录（flood 题无附件却搜到 b2025/bike_data）。
    base = Path(problem_path).parent
    if re.search(r"附件\d*|\.xlsx|\.csv|数据目录", problem_text):
        hit_dirs = sorted(
            {p.parent for p in base.rglob("*")
             if p.is_file() and p.suffix.lower() in (".xlsx", ".csv")},
            key=lambda d: len(d.relative_to(base).parts),
        )
        if hit_dirs:
            named = re.findall(r"([\w\u4e00-\u9fff\-]+\.(?:xlsx|csv|txt))", problem_text)
            if named:
                for d in hit_dirs:
                    dir_files = {f.name.lower() for f in d.iterdir() if f.is_file()}
                    if any(n.lower() in dir_files for n in named):
                        return str(d.resolve())
            return str(hit_dirs[0].resolve())
    # 默认：赛题同目录的 data 子目录；不存在（赛题本身就在 data/ 下）时
    # 退回赛题所在目录本身，避免推断出 data/data 这种不存在路径
    fallback = (Path(problem_path).parent / "data").resolve()
    if fallback.exists():
        return str(fallback)
    return str(Path(problem_path).parent.resolve())


def _save_checkpoint(summary: dict, start_time: float) -> Path:
    """保存断点到固定路径，供中断后 --resume 恢复。"""
    summary["_checkpoint_saved_at"] = round(time.time() - start_time, 1)
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(
        json.dumps(_clean_for_json(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  [CHECKPOINT] 断点已保存: {CHECKPOINT_FILE}")
    return CHECKPOINT_FILE


def _resume_from_file(path: str, summary: dict) -> bool:
    """尝试从断点文件恢复 summary；成功返回 True。"""
    p = Path(path)
    if not p.exists():
        print(f"[WARN] 断点文件不存在: {path}")
        return False
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] 断点文件读取失败，从头运行: {e}")
        return False
    if not loaded.get("sub_problems"):
        print("[WARN] 断点文件缺少 sub_problems，无法恢复，从头运行")
        return False
    for key, val in loaded.items():
        summary[key] = val
    # 若赛题文件已被删除，用断点中的 problem_text 重建，保证 Writer 可读
    pp = summary.get("problem_path", "")
    if pp and not Path(pp).exists() and summary.get("problem_text"):
        try:
            Path(pp).parent.mkdir(parents=True, exist_ok=True)
            Path(pp).write_text(summary["problem_text"], encoding="utf-8")
            print(f"[RESUME] 已重建赛题文件: {pp}")
        except Exception:
            pass
    return True


def run_pipeline(
    problem_path: str,
    skip_solve: bool = False,
    skip_write: bool = False,
    skip_data_check: bool = False,
    progress_callback=None,
    resume_from: str | None = None,
    until: str | None = None,
    skip_hil: bool = False,
    task_dir: str | None = None,
) -> dict:
    """执行完整的建模 pipeline（渐进式：可在指定阶段后停止，人工确认后续跑）。

    Args:
        problem_path: 赛题文件路径
        skip_solve: 是否跳过代码执行
        skip_write: 是否跳过论文生成
        skip_data_check: 是否跳过数据前置校验
        progress_callback: 可选，进度回调 callable(stage, message)，
            在流水线各阶段被调用，供 UI 实时显示进度。
        resume_from: 可选，断点文件路径（pipeline JSON/checkpoint）。
            已有子问题/算法/模型/执行/评审的阶段会被跳过，从论文步继续。
        until: 可选，跑到该阶段后停止并保存断点（渐进式人工确认节点）。
            取值：拆题/算法/建模/求解/评审/论文
        skip_hil: 强制跳过 HIL 人工确认闸门（全自动模式）
        task_dir: 可选，任务级数据目录（Web 多任务并发时通过参数传递，
            替代全局环境变量，避免不同任务的数据互相污染）。

    Returns:
        汇总结果字典，包含每个阶段的输出。
    """
    start_time = time.time()
    summary: dict = {
        "problem_path": problem_path,
        "problem_text": "",
        "sub_problems": [],
        "algorithms": {},
        "models": [],
        "executions": [],
        # 任务级数据目录（Web 多任务并发时通过参数传入，替代全局 env）
        "task_dir": task_dir or "",
    }

    # 每次运行前清理历史运行产物（防堆积；Web 并发任务也会定期清理）
    cleanup_old_artifacts()

    # ── 0. 读取赛题 / 恢复断点 ────────────────────────────────
    _banner("数学建模智能体")
    resumed = _resume_from_file(resume_from, summary) if resume_from else False
    if not resumed:
        problem_text = parse_file(problem_path)
        if not problem_text:
            print(f"[FAIL] 无法读取赛题文件: {problem_path}")
            _save_summary(summary, start_time)
            return summary

        print(f"来源: {problem_path}")
        print(f"长度: {len(problem_text)} 字符")
        print(f"\n赛题预览:\n{problem_text[:500]}{'...' if len(problem_text) > 500 else ''}")
        summary["problem_text"] = problem_text
    else:
        problem_text = summary.get("problem_text", "")
        print(f"恢复自: {resume_from}")
        print(f"赛题: {summary.get('problem_path', problem_path)}")
        print(f"已有进度: 子问题{len(summary.get('sub_problems', []))}个, "
              f"模型{len(summary.get('models', []))}个, "
              f"执行{len(summary.get('executions', []))}条")
    # 数据目录尽早确定并持久化（供验证结果按赛题加载，防跨赛题污染）
    summary.setdefault("data_dir", _infer_data_dir(problem_text, problem_path))

    sub_problems = summary.get("sub_problems", [])
    algorithm_map = summary.get("algorithms", {}) or {}
    build_results = summary.get("models", []) or []

    # ── 1. 协调者：拆题 ──────────────────────────────────────
    if sub_problems:
        print(f"[RESUME] 跳过拆题：已有 {len(sub_problems)} 个子问题")
    else:
        _step(1, "协调者 - 赛题拆解")
        _notify(progress_callback, "拆题", "正在解析赛题并拆解子问题...")
        coord = CoordinatorAgent()
        sub_problems = coord.run(problem_text)
        summary["sub_problems"] = sub_problems

        if not sub_problems:
            print("[FAIL] 拆题失败，pipeline 终止")
            _notify(progress_callback, "拆题", "拆题失败")
            _save_summary(summary, start_time)
            return summary

        for i, sp in enumerate(sub_problems, 1):
            print(f"  {i}. {sp}")
        _notify(progress_callback, "拆题", f"拆解完成，共 {len(sub_problems)} 个子问题")
        if _maybe_stop(until, "拆题", summary, start_time):
            return summary

    # ── 1.5 数据前置校验（DataChecker）────────────────────────
    # 仅当存在数据目录且赛题含【数据文件说明】时执行；无数据则跳过不阻断
    # 含"模拟数据"的赛题跳过（题目自带模拟数据生成规则，不要求真实附件）
    # resume 时已有 data_check 结果则不重跑（数据目录可能已移动，重跑会误中止）
    if (
        not skip_data_check
        and problem_text
        and not summary.get("data_check")
        and "模拟数据" not in problem_text
        and ("数据文件" in problem_text or "附件" in problem_text)
    ):
        _step(2, "数据校验 - 数据资格前置检查")
        _notify(progress_callback, "数据校验", "检查数据文件是否满足赛题要求...")
        from agents.data_checker import DataCheckerAgent
        effective_path = summary.get("problem_path") or problem_path
        data_dir = _infer_data_dir(problem_text, effective_path)
        summary["data_dir"] = data_dir  # 供验证结果按赛题加载（防跨赛题污染）
        dc = DataCheckerAgent()
        check_result = dc.run(data_dir, problem_text)
        summary["data_check"] = check_result
        if check_result["status"] == "failed":
            # 智能兜底：让 LLM 判断是否可以跳过数据校验
            try:
                from utils.intelligent_fallback import should_skip_data_check
                if should_skip_data_check(problem_text, check_result["error"]):
                    print("  [智能兜底] LLM 判断：赛题无需外部数据文件，跳过校验继续建模")
                    _notify(progress_callback, "数据校验", "LLM 判断跳过数据校验，继续建模")
                else:
                    print(f"[FAIL] {check_result['error']}")
                    _notify(progress_callback, "数据校验", "数据资格校验未通过")
                    _save_summary(summary, start_time)
                    return summary
            except Exception as e:
                print(f"[FAIL] {check_result['error']}")
                print(f"  [智能兜底] 兜底失败: {e}")
                _notify(progress_callback, "数据校验", "数据资格校验未通过")
                _save_summary(summary, start_time)
                return summary
        print(f"  [OK] 数据资格校验通过（{len(check_result['checks'])}个文件）")

    # ── 2. 建模者：推荐算法 ──────────────────────────────────
    if algorithm_map:
        print(f"[RESUME] 跳过算法推荐：已有 {len(algorithm_map)} 个子问题算法")
    else:
        _step(2, "建模者 - 算法推荐")
        _notify(progress_callback, "算法", "正在为各子问题推荐建模算法...")
        modeler = ModelerAgent()
        algo_result = modeler.run(problem_text, sub_problems)

        if algo_result["status"] != "ok":
            print(f"[FAIL] 算法推荐失败: {algo_result.get('reason')}")
            _notify(progress_callback, "算法", "算法推荐失败")
            _save_summary(summary, start_time)
            return summary

        print(f"  主算法: {algo_result['main_algorithm']}")
        print(f"  理由: {algo_result['reason']}")

        algorithm_map = {}
        for item in algo_result["sub_algorithms"]:
            algorithm_map[item["sub_problem"]] = item["algorithm"]
            print(f"  {item['sub_problem'][:40]} -> {item['algorithm']}")

        summary["algorithms"] = algorithm_map
        # 结构诊断（维度/组合/可解析化红线）持久化，供 Builder 与经验库使用
        summary["diagnostics"] = algo_result.get("diagnostics", {}) or {}
        _notify(progress_callback, "算法", f"主算法: {algo_result['main_algorithm']}")
        _save_checkpoint(summary, start_time)
        if _maybe_stop(until, "算法", summary, start_time):
            return summary

    # ── 2.75 策略门控1：建模策略分岔口（锁"不建废模"）────────
    # 分步建模 vs 联合建模——全自动无法判断"模型建得蠢不蠢"，
    # 在第一个子模型建立前强制向人工请示，人工一句话锁死结构。
    from utils.ask_gate import gate_enabled, write_ask_file, _gen_question
    if not skip_hil and gate_enabled("modeling_strategy") and \
            not (summary.get("gate_answers") or {}).get("modeling_strategy"):
        from utils.modeling_kb import classify_problem
        _step(2, "策略门控 - 建模策略请示")
        ptype = classify_problem(problem_text, *sub_problems)
        algo_lines = "\n".join(
            f"{i}. {sp} -> {algorithm_map.get(sp, '未确定')}"
            for i, sp in enumerate(sub_problems, 1)
        )
        context = f"题型: {ptype}\n子问题与算法:\n{algo_lines}"
        question = _gen_question(
            "modeling_strategy", ptype, context,
            llm=lambda p: _call_llm_simple(p),
        )
        ask_path = write_ask_file("modeling_strategy", question, context, summary)
        _save_checkpoint(summary, start_time)
        print("\n" + "=" * 64)
        print("  [!] 策略门控：建模前必须由人工拍板建模策略")
        print(f"  提问文件: {ask_path}")
        print("  请编辑该文件填写 answer，然后运行:")
        print("  python hil_resume.py {0}".format(ask_path))
        print("=" * 64)
        _notify(progress_callback, "门控", f"等待人工策略决定: {ask_path}")
        return summary

    # ── 3. 构建者：生成模型和代码 ─────────────────────────────
    if build_results:
        print(f"[RESUME] 跳过模型构建：已有 {len(build_results)} 个子问题模型")
    else:
        _step(3, "构建者 - 模型构建与代码生成")
        _notify(progress_callback, "建模", "正在生成数学模型与代码...")
        builder = BuilderAgent()
        # 人工策略决定（门控答案）注入 Builder，建模必须遵守
        _answers = summary.get("gate_answers") or {}
        _gate_text = "".join(
            f"\n【人工策略决定（必须遵守）】{v}" for k, v in _answers.items()
        )
        build_results = builder.run_batch(
            problem_text, sub_problems, algorithm_map,
            data_dir=summary.get("data_dir"),
            gate_decisions=_gate_text,
            diagnostics=summary.get("diagnostics"),
        )
        summary["models"] = build_results
        _save_checkpoint(summary, start_time)  # 保存建模结果，方便调试

        ok_count = sum(1 for r in build_results if r["status"] in ("ok", "warning"))
        print(f"  生成完成: {ok_count}/{len(build_results)}")
        _notify(progress_callback, "建模", f"模型代码生成完成 {ok_count}/{len(build_results)}")

        for i, (sp, res) in enumerate(zip(sub_problems, build_results), 1):
            status_icon = "OK" if res["status"] == "ok" else "WARN" if res["status"] == "warning" else "FAIL"
            code_lines = len(res.get("code", "").splitlines())
            print(f"  [{status_icon}] {i}. {sp[:35]}... ({code_lines}行代码)")
            if res.get("error"):
                print(f"        错误: {res['error']}")
            if res.get("missing_deps"):
                print(f"        缺少: {', '.join(res['missing_deps'])}")

    # ── 3.5 人工求解覆盖：物理推导题用人工写的核心算法替代 Builder 代码 ──
    manual_manifest = load_manifest()
    if manual_manifest and build_results:
        for res in build_results:
            entry = find_manual(res.get("sub_problem", ""), manual_manifest)
            if not entry:
                continue
            code = load_manual_code(entry)
            if not code:
                print(f"  [MANUAL] 子问题「{res['sub_problem'][:30]}」匹配到人工求解但文件缺失: {entry.get('file')}")
                continue
            res["code"] = code
            res["status"] = "ok"
            res["error"] = None
            res["manual_solution"] = str(entry.get("file", ""))
            math = load_manual_math(entry)
            if math:
                res["math_model"] = math
            if entry.get("algorithm"):
                res["algorithm"] = entry["algorithm"]
                summary["algorithms"][res["sub_problem"]] = entry["algorithm"]
            algorithm_map[res["sub_problem"]] = res["algorithm"]
            print(f"  [MANUAL] 子问题「{res['sub_problem'][:35]}」使用人工求解: {res['manual_solution']}")
    if _maybe_stop(until, "建模", summary, start_time):
        return summary

    # ── 3.9 策略门控2：灵敏度分析求解器（锁"不乱用算法"）─────
    if (
        not skip_solve and not skip_hil
        and gate_enabled("sensitivity_solver")
        and not (summary.get("gate_answers") or {}).get("sensitivity_solver")
        and any("灵敏度" in sp for sp in sub_problems)
    ):
        _step(4, "策略门控 - 灵敏度求解器请示")
        context = "赛题含灵敏度分析要求；子问题: " + "；".join(
            sp[:40] for sp in sub_problems
        )
        question = _gen_question(
            "sensitivity_solver", "优化决策", context, llm=_call_llm_simple
        )
        ask_path = write_ask_file("sensitivity_solver", question, context, summary)
        _save_checkpoint(summary, start_time)
        print("\n" + "=" * 64)
        print("  [!] 策略门控：灵敏度分析求解器需人工拍板")
        print(f"  提问文件: {ask_path}")
        print("  请编辑该文件填写 answer，然后运行:")
        print("  python hil_resume.py {0}".format(ask_path))
        print("=" * 64)
        _notify(progress_callback, "门控", f"等待人工决定: {ask_path}")
        return summary

    # ── 4. 求解者：执行代码 ──────────────────────────────────
    if not skip_solve:
        if len(summary.get("executions", [])) >= len(sub_problems) and summary.get("executions"):
            print(f"[RESUME] 跳过求解：已有 {len(summary['executions'])} 条执行记录")
        else:
            _step(4, "求解者 - 代码执行与调试")
            solver = SolverAgent()
            # 子问题数据契约链：前序子问题的执行结果注入后续子问题的运行环境
            # （result_N.json），防止各子问题代码各自硬编码数据导致结果互相矛盾
            shared_results: dict[int, dict] = {}
            # 图片持久化目录（Solver 执行完临时目录即删，图必须提前落盘）。
            # 每个子问题独立子目录（sub{i}），并行执行时避免同名图片互相覆盖。
            # 时间戳含毫秒：两个 run_pipeline 同秒启动也不会冲突（Web 并发场景）。
            # 注意：Windows time.strftime 不支持 %f 微秒，用毫秒拼接
            fig_base = RESULTS_DIR / "figures" / (
                time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
            )
            fig_base.mkdir(parents=True, exist_ok=True)

            def _solve_one(i: int, sp: str, res: dict) -> dict:
                """求解单个子问题（含失败修复链），返回 exec_result。

                独立函数供并行/串行两阶段复用：无数据契约依赖的子问题并行执行，
                依赖前序 result_N.json 的子问题在主线程按序执行。
                """
                _notify(
                    progress_callback, "求解",
                    f"执行第 {i}/{len(sub_problems)} 个子问题: {sp[:30]}...",
                )
                code = res.get("code", "")
                if not code:
                    print(f"  [SKIP] {i}. {sp[:40]}... (无代码)")
                    return {"sub_problem": sp, "status": "skipped"}

                # 每个子问题独立的图片子目录（并行时同名 figure_N.png 不冲突）
                fig_dir = fig_base / f"sub{i}"
                fig_dir.mkdir(parents=True, exist_ok=True)

                # 组装前序结果文件（数据契约链）
                extra_files: dict[str, str] = {}
                for j in range(1, i):
                    if j in shared_results:
                        extra_files[f"result_{j}.json"] = json.dumps(
                            shared_results[j], ensure_ascii=False, indent=2
                        )

                print(f"  执行 {i}. {sp[:40]}...", end=" ", flush=True)
                # 数据上下文：优先任务目录（Web 并发）；CLI 无任务目录时
                # 用 data_dir（赛题数据所在目录）兜底——否则 solver 沙箱里
                # 没有任何数据文件，LLM 只能编造模拟数据（实测 Q1 用了
                # generate_simulated_data 而非真实 bike_data.csv）
                _task_dir = (
                    summary.get("task_dir")
                    or summary.get("data_dir")
                    or None
                )
                if res.get("manual_solution"):
                    # 人工求解代码：只执行一次，不做 LLM 自动修复（视为可信）
                    raw = solver.run_code(code, extra_files=extra_files, figure_dir=fig_dir, task_dir=_task_dir)
                    if raw["success"]:
                        exec_result = {
                            "status": "ok",
                            "code": code,
                            "output": raw["stdout"],
                            "metrics": _extract_metrics(raw["stdout"]),
                            "metrics_json": raw.get("metrics_json", {}),
                            "attempts": 1,
                            "missing_deps": raw.get("missing_deps"),
                            "figures": raw.get("figures", []),
                            "manual_solution": res["manual_solution"],
                            "verification_status": "verified_metrics",
                        }
                    else:
                        exec_result = {
                            "status": "error",
                            "code": code,
                            "error": (raw.get("stderr") or "执行失败")[:500],
                            "last_stderr": raw.get("stderr", ""),
                            "safety_fail": raw.get("safety_fail", False),
                            "manual_solution": res["manual_solution"],
                            "verification_status": "unverified",
                        }
                else:
                    exec_result = solver.run(code, extra_files=extra_files, figure_dir=fig_dir, task_dir=_task_dir)

                # ── 失败回传：让 Builder 带着报错重新建模（最多1轮）──
                first_error: str | None = None

                def _rebuild_with_fallback(error_text: str) -> dict:
                    """带降级指令的重建模：原算法多轮失败后不再坚持原方案，
                    强制改用更简单可靠的启发式方法，保证子问题有数值产出
                    （宁可结果次优，不可整章"求解失败"——实测 Q4 无降级时
                    3轮修复+重建模全在同算法内空转，最终论文留白）。

                    注意：降级指令放在 feedback 前部——Builder 会截断
                    feedback[:2000]，放后面会被截掉。
                    """
                    algo = algorithm_map.get(sp, "未确定")
                    degrade = (
                        "【降级重建模——原方案已失败，必须更换算法】\n"
                        f"原算法「{algo}」生成的代码执行失败且自动修复无效。"
                        "请放弃原算法，改用更简单、可靠、30秒内可完成的方法"
                        "（如贪心、随机搜索、启发式规则、缩小规模的解析求解）。"
                        "新方案必须：输出具体数值结果并写入 metrics.json，"
                        "至少生成一张结果图表。宁可结果次优，不可无结果。\n\n"
                        "【上次代码执行报错】\n"
                    )
                    return builder.run(
                        problem_text, sp, algo,
                        feedback=degrade + error_text,
                        data_dir=summary.get("data_dir"),
                        structure_hints=(
                            (summary.get("diagnostics") or {}).get(sp)
                            and _redline_text(summary.get("diagnostics", {}).get(sp))
                        ) or "",
                    )

                def _try_rebuild(err_text: str) -> None:
                    """Builder 降级重建模并重跑；结果写回 exec_result。"""
                    nonlocal exec_result
                    rebuilt = _rebuild_with_fallback(err_text)
                    if rebuilt.get("code"):
                        res["code"] = rebuilt["code"]
                        if rebuilt.get("math_model"):
                            res["math_model"] = rebuilt["math_model"]
                        exec_result = solver.run(
                            rebuilt["code"], extra_files=extra_files,
                            figure_dir=fig_dir, task_dir=_task_dir,
                        )
                        exec_result["rebuild_attempted"] = True
                        exec_result["first_error"] = err_text

                if (
                    exec_result["status"] != "ok"
                    and exec_result.get("last_stderr")
                    and not exec_result.get("safety_fail")
                ):
                    first_error = exec_result.get("error", "") or exec_result.get("last_stderr", "")

                    # Agent Loop：让 LLM 分析错误原因
                    try:
                        from utils.agent_loop import analyze_and_fix_code
                        print(f"[Agent Loop] 分析错误...", end="", flush=True)
                        analysis = analyze_and_fix_code(first_error, code, sp)
                        if analysis["status"] == "fixed" and analysis["fixed_code"]:
                            print(f" → LLM 生成修复代码 ({analysis['rounds']} 轮)")
                            exec_result = solver.run(analysis["fixed_code"], extra_files=extra_files, figure_dir=fig_dir, task_dir=_task_dir)
                            exec_result["agent_loop_fix"] = True
                            exec_result["first_error"] = first_error
                            if exec_result["status"] != "ok":
                                # Agent Loop 修复后仍失败 → 降级重建模兜底
                                # （此前此处直接放弃，修复代码失败就没有第二次机会）
                                print(f" → 修复代码仍失败，降级重建模")
                                _try_rebuild(first_error)
                        else:
                            # Agent Loop 未能修复，回退到 Builder 重试（带降级指令）
                            print(f" → 回退到 Builder 重试（含算法降级指令）")
                            _try_rebuild(first_error)
                    except Exception as e:
                        print(f" → Agent Loop 异常: {e}，回退到 Builder")
                        _try_rebuild(first_error)

                exec_result["sub_problem"] = sp
                return exec_result

            def _needs_prior(code: str, i: int) -> bool:
                """子问题代码是否引用前序结果文件（数据契约依赖）。

                覆盖多种引用方式，且避免误伤普通变量名（如 result_analysis）：
                - 字面量：result_1.json、result_2.json（匹配 result_<数字>）
                - f-string：f"result_{j}.json"（源码含 result_{）
                - 遍历读取：glob("result_*.json")、startswith("result_") 前缀过滤
                只匹配"数字下标"或"通配/前缀过滤"模式，result_analysis 不命中。
                """
                if i <= 1:
                    return False
                patterns = (
                    r"result_\d",          # result_1 / result_12
                    r"result_\{",          # f"result_{j}"（result_ 后跟 {）
                    r'glob\(["\']result',  # glob("result_*.json")
                    r'startswith\(["\']result_',  # startswith("result_")
                )
                return any(re.search(p, code) for p in patterns)

            # ── 执行计划：无依赖的子问题并行跑（提速），有依赖的按序跑 ──
            from concurrent.futures import ThreadPoolExecutor, as_completed

            exec_map: dict[int, dict] = {}
            # 求解并行度读 solver 配置（此前误用 writer.max_workers，复制粘贴笔误）
            max_workers = int(get("solver.max_workers", 4))
            # 无代码的子问题直接标记 skipped（不进并行/串行队列，但保留记录）
            for i, (sp, res) in enumerate(zip(sub_problems, build_results), 1):
                if not res.get("code"):
                    exec_map[i] = {"sub_problem": sp, "status": "skipped"}
                    print(f"  [SKIP] {i}. {sp[:40]}... (无代码)")
            independent = [
                (i, sp, res)
                for i, (sp, res) in enumerate(zip(sub_problems, build_results), 1)
                if res.get("code") and not _needs_prior(res.get("code", ""), i)
            ]
            dependent = [
                (i, sp, res)
                for i, (sp, res) in enumerate(zip(sub_problems, build_results), 1)
                if res.get("code") and _needs_prior(res.get("code", ""), i)
            ]

            def _record_shared(i: int, er: dict) -> None:
                """执行成功的结果立即写入 shared_results（数据契约链）。

                必须在 dependent 子问题执行**之前**记录——此前记录放在
                统一落盘循环里，Q4 这类依赖前序 result_N.json 的子问题
                执行时 shared_results 还是空的，extra_files 永远为空，
                "读 result_1.json 不存在"反复修复无效（实测 Q4 失败根因）。
                """
                if isinstance(er, dict) and er.get("status") == "ok":
                    shared_results[i] = {
                        "sub_problem": sub_problems[i - 1],
                        "metrics_json": er.get("metrics_json", {}),
                        "numbers": (er.get("metrics") or {}).get("numbers", {}),
                        "key_lines": (er.get("metrics") or {}).get("key_lines", [])[:20],
                    }

            with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(independent)))) as _ex:
                _futures = {_ex.submit(_solve_one, i, sp, res): i for i, sp, res in independent}
                for _fut in as_completed(_futures):
                    _i = _futures[_fut]
                    exec_map[_i] = _fut.result()
                    _record_shared(_i, exec_map[_i])

            # 有依赖的子问题：主线程按序执行（前序 shared_results 已就绪）
            for i, sp, res in dependent:
                exec_map[i] = _solve_one(i, sp, res)
                _record_shared(i, exec_map[i])

            # ── 按子问题顺序统一落盘 ──
            for i, (sp, res) in enumerate(zip(sub_problems, build_results), 1):
                exec_result = exec_map.get(i)
                if exec_result is None:
                    continue
                if exec_result.get("status") == "skipped":
                    summary["executions"].append(exec_result)
                    continue

                # 图片路径转相对 RESULTS_DIR（solver 已持久化到 fig_dir）
                _figs = exec_result.get("figures") or []
                if _figs:
                    _rel = []
                    for _f in _figs:
                        try:
                            _rel.append(
                                str(Path(_f).relative_to(RESULTS_DIR)).replace("\\", "/")
                            )
                        except ValueError:
                            _rel.append(str(_f))
                    exec_result["figures"] = _rel
                    print(f"    图 {len(_rel)} 张已落盘: results/{_rel[0]}")
                summary["executions"].append(exec_result)

                # 记录本子问题结果（数据契约链：供后续子问题读取 result_N.json）
                if exec_result.get("status") == "ok":
                    shared_results[i] = {
                        "sub_problem": sp,
                        "metrics_json": exec_result.get("metrics_json", {}),
                        "numbers": (exec_result.get("metrics") or {}).get("numbers", {}),
                        "key_lines": (exec_result.get("metrics") or {}).get("key_lines", [])[:20],
                    }

                # 落盘：代码 + 输出 + ipynb（供人工逐行审核）
                # 先剥掉铁律断言锁——人工拿到的代码必须可直接运行，不能一跑就 AssertionError
                try:
                    from utils.notebook_utils import save_code_artifact
                    from agents.builder import remove_iron_lock
                    save_code_artifact(
                        remove_iron_lock(exec_result.get("code") or res.get("code", "")),
                        exec_result.get("output"),
                        RESULTS_DIR / "code" / time.strftime("%Y%m%d_%H%M%S"),
                        f"sub{i}",
                    )
                except Exception as e:
                    print(f"  [WARN] 代码落盘失败: {e}")

                if exec_result["status"] == "ok":
                    print(f"成功 (尝试{exec_result.get('attempts', 1)}次)")
                    output_preview = (exec_result.get("output") or "")[:200]
                    if output_preview:
                        print(f"    输出: {output_preview}")
                else:
                    print(f"失败")
                    print(f"    错误: {exec_result.get('error', '')[:150]}")
                _notify(
                    progress_callback, "求解",
                    f"第 {i}/{len(sub_problems)} 个子问题"
                    + ("执行成功" if exec_result["status"] == "ok" else "执行失败"),
                )
            _save_checkpoint(summary, start_time)
            if _maybe_stop(until, "求解", summary, start_time):
                return summary
    else:
        _step(4, "求解者 - 已跳过 (--skip-solve)")

    # ── 4.6 策略门控3：最优路径锁定（锁"不自相矛盾"）────────
    if (
        not skip_solve and not skip_hil
        and gate_enabled("path_lock")
        and not (summary.get("gate_answers") or {}).get("path_lock")
        and any(("路径" in sp or "路线" in sp) for sp in sub_problems)
    ):
        ctx_lines = []
        for ex in summary.get("executions", []):
            sp = ex.get("sub_problem", "")
            if ex.get("status") == "ok" and ("路径" in sp or "路线" in sp):
                ctx_lines.append(f"[{sp[:30]}] {(ex.get('output') or '')[:300]}")
        context = "\n".join(ctx_lines) or "（无路径子问题执行输出）"
        question = _gen_question(
            "path_lock", "优化决策", context, llm=_call_llm_simple
        )
        ask_path = write_ask_file("path_lock", question, context, summary)
        _save_checkpoint(summary, start_time)
        print("\n" + "=" * 64)
        print("  [!] 策略门控：最优路径需人工锁定")
        print(f"  提问文件: {ask_path}")
        print("  请编辑该文件填写 answer，然后运行:")
        print("  python hil_resume.py {0}".format(ask_path))
        print("=" * 64)
        _notify(progress_callback, "门控", f"等待人工决定: {ask_path}")
        return summary

    # ── 4.5 HIL 闸门：无真值子问题暂停等人工确认 ────────────
    from utils.hil import should_pause, write_pending
    if not skip_hil and should_pause(summary):
        # 按当前赛题数据目录加载验证真值（防跨赛题污染）
        data_dir = summary.get("data_dir") or _infer_data_dir(problem_text, summary.get("problem_path") or problem_path)
        summary["_verified_results"] = load_verified_results(data_dir)
        if should_pause(summary):
            pending = write_pending(summary, summary["executions"], sub_problems)
            _save_checkpoint(summary, start_time)
            print("\n" + "=" * 64)
            print("  [!] HIL 闸门：子问题数值【无 ground truth】，需人工确认")
            print(f"  待确认文件: {pending}")
            print("  请编辑该文件填写 decision（confirm / edit+value / reject），")
            print("  然后运行: python hil_resume.py {0}".format(pending))
            print("=" * 64)
            _notify(progress_callback, "HIL", f"等待人工确认: {pending}")
            return summary

    # ── 5. 评审者：结果评审 ──────────────────────────────────
    if not skip_solve:
        if summary.get("review"):
            print("[RESUME] 跳过评审：已有评审意见")
        else:
            _step(5, "评审者 - 结果评审")
            _notify(progress_callback, "评审", "正在评审求解结果的合理性...")
            reviewer = ReviewerAgent()
            review = reviewer.run(summary)
            summary["review"] = {
                "status": review["status"],
                "warnings": review["warnings"],
                "review": review["review"],
            }

            for w in review["warnings"]:
                print(f"  [WARN] {w}")
            if review["issues"]:
                print(f"  [ISSUE] {len(review['issues'])} 个子问题求解失败")
                for iss in review["issues"]:
                    print(f"    - {iss['sub_problem'][:40]}...")
            print(f"  评审意见: {review['review'][:200]}...")
            _save_checkpoint(summary, start_time)
            if _maybe_stop(until, "评审", summary, start_time):
                return summary
    else:
        _step(5, "评审者 - 已跳过 (--skip-solve)")

    # ── 6. 写作者：生成论文 ──────────────────────────────────
    # ── 7. 总审：三重质量门控（不通过则带反馈重写，循环）──────
    if not skip_write:
        _step(6, "写作者 - 论文生成")
        _notify(progress_callback, "论文", "正在生成论文（各章节并行）...")
        writer = WriterAgent()
        gate = QualityGateAgent()
        paper_result: dict | None = None
        # 注入人工/独立验证结果（数据审核以此为准，优先级高于 Builder 执行记录）。
        # 当前赛题数据目录有验证文件 → 与已有内容合并（HIL 人工值+CSV 真值共存）；
        # 无验证文件 → 只保留 HIL 人工行（子问题N: 值），清掉 checkpoint 中
        # 其它赛题残留的 CSV 真值（跨赛题污染，实测 b2025 真值泄漏进共享单车题）。
        _vr_dir = summary.get("data_dir") or _infer_data_dir(
            problem_text, summary.get("problem_path") or problem_path
        )
        _csv_text = load_verified_results(_vr_dir)
        if _csv_text:
            summary["_verified_results"] = _merge_verified_text(
                summary.get("_verified_results", ""), _csv_text
            )
        else:
            _existing = (summary.get("_verified_results") or "").splitlines()
            _human_lines = [
                l for l in _existing
                if l.strip().startswith("子问题")  # HIL edit 格式：子问题N: 值
            ]
            summary["_verified_results"] = "\n".join(_human_lines)
        max_rounds = int(get("auditor.max_rounds", 100))
        max_stagnant = int(get("auditor.max_stagnant_rounds", 2))
        feedback = ""
        audit_report: dict | None = None
        stagnant = 0
        best_overall = -1.0
        start_round = 1

        # 审计循环断点恢复：中断后从上次已审核轮次的下一轮继续
        cp = summary.pop("_checkpoint", None)
        already_passed = bool(summary.get("audit", {}).get("passed"))
        if already_passed:
            print("[RESUME] 质量门控已通过，跳过论文生成与审核循环")
            start_round = max_rounds + 1
        elif cp and cp.get("round"):
            start_round = int(cp["round"]) + 1
            feedback = cp.get("feedback", "")
            audit_report = cp.get("audit_report") or None
            best_overall = float(cp.get("best_overall", -1.0))
            stagnant = int(cp.get("stagnant", 0))
            print(f"[RESUME] 审计循环从第 {start_round} 轮继续（最好综合分 {best_overall}）")

        for round_i in range(start_round, max_rounds + 1):
            if round_i > 1:
                _step(6, f"写作者 - 根据审核反馈重写（第{round_i}轮）")
                _notify(progress_callback, "论文", f"根据审核反馈重写（第{round_i}轮）...")
            paper_result = writer.run(
                summary,
                feedback=feedback,
                feedback_by_section=audit_report.get("feedback_by_section") if audit_report else None,
            )
            summary["paper"] = {
                "status": paper_result["status"],
                "paper_path": paper_result.get("paper_path", ""),
                "warnings": paper_result.get("warnings"),
            }
            if paper_result["status"] not in ("ok", "partial"):
                print(f"  论文生成失败: {paper_result.get('error')}")
                break

            print(f"  论文已保存: {paper_result['paper_path']}")
            if paper_result["status"] == "partial":
                for w in (paper_result.get("warnings") or []):
                    print(f"    [!] {w}")

            # ── 质量门控审核 ──
            _step(7, f"总审 - 逻辑/数据/排版三重审核（第{round_i}轮）")
            _notify(progress_callback, "审核", f"逻辑/数据/排版三重审核（第{round_i}轮）...")
            audit_report = gate.run(paper_result["content"], summary)
            scores = audit_report["scores"]
            overall = audit_report["overall"]
            print(
                f"  逻辑:{scores['logic']}分  数据:{scores.get('data', '跳过')}分  "
                f"排版:{scores['format']}分  综合:{overall}分"
            )

            if audit_report["passed"]:
                print(f"  [OK] 三项均超过8分且综合超过9分，质量门控通过")
                break

            # 停滞保护：连续 N 轮综合分未提升则停止
            if overall > best_overall:
                best_overall = overall
                stagnant = 0
            else:
                stagnant += 1
                if stagnant >= max_stagnant:
                    print(
                        f"  [!] 已连续 {max_stagnant} 轮综合分未提升"
                        f"（最好 {best_overall} 分），停止重写"
                    )
                    audit_report["force_accepted"] = True
                    audit_report["accept_note"] = (
                        f"\n\n---\n> [!] **质量门控未完全通过**"
                        f"（已连续 {max_stagnant} 轮无提升）。"
                        f"最终评分：逻辑{scores['logic']}分、数据{scores.get('data', '跳过')}分、"
                        f"排版{scores['format']}分、综合{overall}分。"
                        "以下问题需人工复核修正。\n"
                    )
                    break

            if round_i >= max_rounds:
                print(f"  [!] 已达最大轮数上限({max_rounds})，接受当前论文")
                audit_report["force_accepted"] = True
                audit_report["accept_note"] = (
                    f"\n\n---\n> [!] **质量门控未完全通过**（已达轮数上限）。"
                    f"最终评分：逻辑{scores['logic']}分、数据{scores.get('data', '跳过')}分、"
                    f"排版{scores['format']}分、综合{overall}分。"
                    "以下问题需人工复核修正。\n"
                )
                break

            print(f"  [FAIL] 未通过（每项需>8分且综合>9分），反馈给写作者重写...")
            feedback = audit_report["feedback"]

            # 保存审计循环断点（中断后 --resume 从下一轮继续，不再重跑本轮）
            summary["_checkpoint"] = {
                "round": round_i,
                "paper_path": paper_result.get("paper_path", ""),
                "best_overall": best_overall,
                "stagnant": stagnant,
                "feedback": feedback,
                "audit_report": {
                    k: audit_report.get(k) for k in (
                        "scores", "overall", "feedback", "feedback_by_section",
                    )
                },
            }
            _save_checkpoint(summary, start_time)

        # 循环实际运行过（或断点带审核结果）才覆盖 audit，resume 已通过时不覆盖
        if audit_report is not None:
            summary["audit"] = {
                "passed": bool(audit_report["passed"]),
                "force_accepted": bool(audit_report.get("force_accepted")),
                "accept_note": audit_report.get("accept_note") if audit_report else None,
                "scores": audit_report["scores"] if audit_report else None,
                "overall": audit_report["overall"] if audit_report else None,
                "feedback": audit_report["feedback"] if audit_report else None,
            }

        # 审计循环结束：更新断点为最终状态（含 audit），resume 可检测已通过
        summary.pop("_checkpoint", None)
        _save_checkpoint(summary, start_time)

        # 数值一致性验收报告（确定性产物，供人工终审对照）
        try:
            last_text = paper_result.get("content", "") if paper_result else ""
            if last_text:
                report_path = _write_verify_report(summary, last_text)
                print(f"  [VERIFY] 数值一致性验收报告: {report_path}")
        except Exception as e:
            print(f"  [WARN] 验收报告生成失败: {e}")

        # 未通过但被强制接受时，把失败状态与异常清单附在论文文件末尾（不隐藏失败）
        if summary.get("audit", {}).get("force_accepted"):
            note = summary.get("audit", {}).get("accept_note")
            pp = summary.get("paper", {}).get("paper_path", "")
            if note and pp and Path(pp).exists():
                try:
                    with open(pp, "a", encoding="utf-8") as f:
                        f.write(note)
                    print(f"  [WARN] 论文未通过门控，已标注失败状态: {pp}")
                except Exception as e:
                    print(f"  [WARN] 论文失败标注写入失败: {e}")
        if _maybe_stop(until, "论文", summary, start_time):
            return summary
    else:
        _step(6, "写作者 - 已跳过 (--skip-write)")

    # ── 保存结果 ──────────────────────────────────────────────
    result_file = _save_summary(summary, start_time)

    # ── 记录经验库（无论成败都记录，供后续赛题作先验）────────
    record_from_summary(summary)
    print(f"  经验库: 已记录 {len(summary['executions'])} 条执行记录")

    _banner("Pipeline 完成")
    print(f"  耗时: {summary['elapsed_seconds']}s")
    _notify(progress_callback, "完成", f"全部流程完成，耗时 {summary['elapsed_seconds']}s")
    print(f"  子问题: {len(sub_problems)}个")
    print(f"  代码生成: {sum(1 for r in build_results if r.get('status') in ('ok', 'warning'))}/{len(build_results)}")
    solved = sum(1 for e in summary["executions"] if e.get("status") == "ok")
    print(f"  代码执行: {solved}/{len(summary['executions'])}")
    audit = summary.get("audit")
    if audit and audit.get("scores"):
        sc = audit["scores"]
        data_disp = "跳过" if sc.get("data") is None else f"{sc['data']}"
        print(
            f"  质量门控: {'通过' if audit['passed'] else '未通过'} "
            f"(逻辑{sc['logic']} 数据{data_disp} "
            f"排版{sc['format']} 综合{audit['overall']})"
        )
        if audit.get("force_accepted"):
            print(f"  [!] 已达最大重写轮数，论文被强制接受，需人工复核审核意见")
    print(f"  结果保存: {result_file}")

    return summary


def _save_summary(summary: dict, start_time: float) -> Path:
    """将汇总结果保存到 JSON 文件。"""
    summary["elapsed_seconds"] = round(time.time() - start_time, 1)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    result_file = RESULTS_DIR / f"pipeline_{timestamp}.json"
    clean = _clean_for_json(summary)
    result_file.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_file


def _clean_for_json(obj):
    """递归清理对象，使其可 JSON 序列化。"""
    if isinstance(obj, dict):
        def _clean_key(k):
            if isinstance(k, (str, int, float, bool, type(None))):
                return k
            return str(k)
        return {_clean_key(k): _clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_for_json(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # 解析参数
    args = sys.argv[1:]
    skip_solve = "--skip-solve" in args
    skip_write = "--skip-write" in args
    skip_data_check = "--skip-data-check" in args
    skip_hil = "--skip-hil" in args
    until = None
    if "--until" in args:
        i = args.index("--until")
        until = args[i + 1] if i + 1 < len(args) else None
        if until not in ("拆题", "算法", "建模", "求解", "评审", "论文"):
            print(f"[WARN] --until 需为 拆题/算法/建模/求解/评审/论文（当前: {until}），忽略")
            until = None
    resume = None
    if "--resume" in args:
        i = args.index("--resume")
        resume = args[i + 1] if i + 1 < len(args) else None
        if resume is None:
            print("[WARN] --resume 需要断点文件路径（如 --resume data/results/pipeline_checkpoint.json）")
    file_args = [a for a in args if not a.startswith("--") and a != resume]

    if file_args:
        problem_path = file_args[0]
    else:
        # 默认使用示例赛题（data/problems/ 下）
        default_problem = Path(__file__).parent / "data" / "problems" / "bike_shared.txt"
        if not default_problem.exists():
            # 兼容旧路径（data/test_problem.txt）
            fallback = Path(__file__).parent / "data" / "test_problem.txt"
            if fallback.exists():
                default_problem = fallback
            else:
                print("[FAIL] 未找到默认赛题文件 data/problems/bike_shared.txt，请指定赛题路径")
                print("用法: python main.py data/problems/xxx.txt")
                sys.exit(1)
        problem_path = str(default_problem)

    # --resume 时无需赛题文件（断点中已含赛题内容）
    if resume is None and not Path(problem_path).exists():
        print(f"[FAIL] 文件不存在: {problem_path}")
        sys.exit(1)

    run_pipeline(
        problem_path,
        skip_solve=skip_solve,
        skip_write=skip_write,
        skip_data_check=skip_data_check,
        resume_from=resume,
        until=until,
        skip_hil=skip_hil,
    )


if __name__ == "__main__":
    main()
