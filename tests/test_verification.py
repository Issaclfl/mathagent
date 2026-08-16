from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.verification import (
    is_verified, status_of_execution, safe_metrics_json, safe_metrics_numbers,
    parse_verified_refs,
    STATUS_METRICS, STATUS_HUMAN, STATUS_UNVERIFIED,
)
from agents.writer import WriterAgent
from agents.audit import QualityGateAgent


def test_status_of_execution():
    """默认判定：ok+指标 → verified_metrics；显式标记优先；否则 unverified。"""
    assert status_of_execution({"status": "ok", "metrics_json": {"RMSE": 0.1}}) == STATUS_METRICS
    assert status_of_execution({"status": "ok", "metrics": {"numbers": {"x": 1}}}) == STATUS_METRICS
    assert status_of_execution({"status": "ok"}) == STATUS_UNVERIFIED
    assert status_of_execution({"status": "error"}) == STATUS_UNVERIFIED
    assert status_of_execution({"status": "ok", "verification_status": STATUS_HUMAN}) == STATUS_HUMAN
    assert status_of_execution({"status": "error", "verification_status": STATUS_UNVERIFIED}) == STATUS_UNVERIFIED
    # 非法显式值归一为 unverified
    assert status_of_execution({"status": "ok", "verification_status": "假的"}) == STATUS_UNVERIFIED
    print("[PASS] test_status_of_execution")


def test_safe_metrics():
    """未验证时 safe_* 应返回空，防止数字外泄。"""
    assert safe_metrics_json({"status": "ok", "metrics_json": {"RMSE": 0.1}}) == {"RMSE": 0.1}
    assert safe_metrics_json({"status": "ok"}) == {}
    assert safe_metrics_numbers({"status": "ok", "verification_status": STATUS_UNVERIFIED,
                                 "metrics": {"numbers": {"x": 1}}}) == {}
    print("[PASS] test_safe_metrics")


def test_writer_only_cites_verified():
    """Writer 摘要只引用已验证数值；未验证写占位符。"""
    w = WriterAgent()
    sub = ["子问题A", "子问题B"]
    execs = [
        {"status": "ok", "metrics_json": {"RMSE": 0.1}, "verification_status": STATUS_METRICS},
        {"status": "ok", "metrics_json": {"RMSE": 9.9}, "verification_status": STATUS_UNVERIFIED},
    ]
    s = w._build_exec_summary(execs, sub)
    assert "RMSE=0.1" in s
    assert "未验证" in s and "RMSE=9.9" not in s
    print("[PASS] test_writer_only_cites_verified")


def test_audit_has_execution_data_requires_verified():
    """无已验证参考值时，数据审核应跳过（不再基于代码输出）。"""
    from agents.audit import DataAuditor
    da = DataAuditor()
    # 仅有未验证的执行记录，无人工真值 → _extract_refs 应回退到 metrics_json（verified_metrics）
    summary = {"sub_problems": ["A"], "executions": [
        {"status": "ok", "metrics": {"numbers": {"x": 1}}, "verification_status": STATUS_UNVERIFIED},
    ], "_verified_results": ""}
    r = da.run("论文含 1.0", summary)
    # 无任何可参考真值 → 跳过
    r2 = da.run("论文含 1.0", {"sub_problems": ["A"], "executions": [], "_verified_results": ""})
    assert r2.get("skipped") is True
    print("[PASS] test_audit_has_execution_data_requires_verified")


def test_writer_no_raw_output_leak_with_verified():
    """有已验证 metrics_json 时，不得再回退到原始输出（防止旧错误值混入）。"""
    w = WriterAgent()
    sub = ["物理核心题"]
    execs = [{
        "status": "ok", "sub_problem": "物理核心题",
        "metrics_json": {"人工验证值": 10.47},
        "verification_status": STATUS_HUMAN,
        "output": "厚度=4.72um",   # 旧错误输出
    }]
    s = w._build_exec_summary(execs, sub)
    assert "10.47" in s and "4.72" not in s
    ms = w._build_model_exec_summary(execs[0])
    assert "10.47" in ms and "4.72" not in ms
    print("[PASS] test_writer_no_raw_output_leak_with_verified")


def test_parse_verified_refs_bare_keyvalue():
    """裸键值行：RMSE=15.2 / 厚度: 10.471 / 科学计数法 / 带点键（表格解析出的键）。"""
    assert parse_verified_refs("RMSE=15.2") == {"RMSE": 15.2}
    assert parse_verified_refs("厚度: 10.471") == {"厚度": 10.471}
    refs = parse_verified_refs("数值=2.82e-24")
    assert abs(refs["数值"] - 2.82e-24) < 1e-30
    # 表格解析出的键含点号（文件名.行标识.列名）
    refs2 = parse_verified_refs("厚度计算结果.附件1.xlsx.厚度_um=10.471")
    assert refs2.get("厚度计算结果.附件1.xlsx.厚度_um") == 10.471
    assert parse_verified_refs("") == {}
    assert parse_verified_refs("没有数字的行") == {}
    print("[PASS] test_parse_verified_refs_bare_keyvalue")


def test_parse_verified_refs_hil_line():
    """HIL 人工行（新格式与旧格式均需可解析）。"""
    refs = parse_verified_refs("子问题1: 42.5")
    assert refs.get("子问题1") == 42.5
    # 旧格式：全角括号 + "人工值" 前缀
    refs2 = parse_verified_refs("子问题1（预测销量）: 人工值 42.5")
    assert abs(refs2.get("子问题1（预测销量）") - 42.5) < 1e-9
    print("[PASS] test_parse_verified_refs_hil_line")


def test_parse_verified_refs_csv_table():
    """验证 CSV 的 pandas to_string 表格文本（load_verified_results 输出格式）。

    多行表格按行标识（首个非数值列）建键，每行真值都保留，不被覆盖。
    """
    # 与 data/b2025/厚度计算结果.csv 的 to_string(index=False) 一致
    table = (
        "厚度计算结果:\n"
        "      附件  材料  折射率 入射角  厚度_um\n"
        "附件1.xlsx SiC 3.40 10° 10.471\n"
        "附件2.xlsx SiC 3.40 15° 10.389\n"
        "附件3.xlsx  Si 3.44 10°  7.581\n"
        "附件4.xlsx  Si 3.44 15°  7.645"
    )
    refs = parse_verified_refs(table)
    assert refs.get("厚度计算结果.附件1.xlsx.厚度_um") == 10.471
    assert refs.get("厚度计算结果.附件4.xlsx.厚度_um") == 7.645
    assert refs.get("厚度计算结果.附件1.xlsx.折射率") == 3.4
    # 每行的厚度真值都必须保留（不能被最后一行覆盖）
    assert len([k for k in refs if k.endswith(".厚度_um")]) == 4
    # 非数值列（附件名/入射角 10°）不产生键值
    assert "附件1.xlsx" not in refs
    assert "10°" not in refs
    print("[PASS] test_parse_verified_refs_csv_table")


def test_writer_appends_verified_refs():
    """Writer 执行摘要追加参考真值，论文引用值与数据审核参考一致。"""
    w = WriterAgent()
    summary = {
        "sub_problems": ["厚度"],
        "executions": [{
            "status": "ok", "metrics_json": {"厚度": 4.72},
            "verification_status": STATUS_METRICS,
        }],
        "_verified_results": "子问题1: 10.471",
    }
    s = w._build_exec_summary(summary["executions"], summary["sub_problems"])
    s = w._append_verified_refs(s, summary)
    assert "10.471" in s
    print("[PASS] test_writer_appends_verified_refs")


if __name__ == "__main__":
    test_status_of_execution()
    test_safe_metrics()
    test_writer_only_cites_verified()
    test_audit_has_execution_data_requires_verified()
    test_writer_no_raw_output_leak_with_verified()
    test_parse_verified_refs_bare_keyvalue()
    test_parse_verified_refs_hil_line()
    test_parse_verified_refs_csv_table()
    test_writer_appends_verified_refs()
    print("\n所有测试通过！")
