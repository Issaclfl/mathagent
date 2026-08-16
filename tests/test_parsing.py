from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.coordinator import _strip_numbering, _dedup
from agents.modeler import _parse_llm_json, _match_algorithm, _match_subproblem
from agents.builder import validate_code, check_dependencies


def test_strip_numbering():
    """测试序号去除。"""
    assert _strip_numbering("1. 子问题一") == "子问题一"
    assert _strip_numbering("（1）子问题一") == "子问题一"
    assert _strip_numbering("第一、子问题一") == "子问题一"
    assert _strip_numbering("- 子问题一") == "子问题一"
    assert _strip_numbering("**1.** 子问题一") == "子问题一"
    assert _strip_numbering("子问题1：子问题一") == "子问题一"
    print("[PASS] test_strip_numbering")


def test_dedup():
    """测试去重。"""
    assert _dedup(["a", "b", "a", "c"]) == ["a", "b", "c"]
    assert _dedup([]) == []
    assert _dedup(["a"]) == ["a"]
    print("[PASS] test_dedup")


def test_parse_llm_json():
    """测试JSON解析。"""
    # 正常JSON
    text1 = '{"key": "value"}'
    assert _parse_llm_json(text1) == {"key": "value"}

    # Markdown代码块包裹
    text2 = '```json\n{"key": "value"}\n```'
    assert _parse_llm_json(text2) == {"key": "value"}

    # 带前后文本
    text3 = '这是结果：{"key": "value"} 以上。'
    assert _parse_llm_json(text3) == {"key": "value"}

    # 尾部逗号修复
    text4 = '{"key": "value",}'
    assert _parse_llm_json(text4) == {"key": "value"}

    # 无效JSON
    text5 = '这不是JSON'
    assert _parse_llm_json(text5) is None

    print("[PASS] test_parse_llm_json")


def test_match_algorithm():
    """测试算法匹配。"""
    pool = {"线性规划", "整数规划", "遗传算法"}
    alias = {"SVM": "支持向量机(SVM)"}

    # 精确匹配
    assert _match_algorithm("线性规划", pool, alias) == "线性规划"

    # 别名匹配
    assert _match_algorithm("SVM", pool, alias) == "支持向量机(SVM)"

    # 空字符串
    assert _match_algorithm("", pool, alias) == "未确定"

    print("[PASS] test_match_algorithm")


def test_match_subproblem():
    """测试子问题匹配。"""
    original = ["确定投放数量", "规划停放区域", "设计调度方案"]

    # 精确匹配
    assert _match_subproblem("确定投放数量", original) == "确定投放数量"

    # 子串匹配
    assert _match_subproblem("投放数量", original) == "确定投放数量"

    # 无匹配
    assert _match_subproblem("完全不同的内容", original) is None

    print("[PASS] test_match_subproblem")


def test_validate_code():
    """测试代码验证。"""
    # 有效代码
    valid = "print('hello')"
    is_valid, _ = validate_code(valid)
    assert is_valid

    # 无效代码
    invalid = "def foo(:"
    is_valid, error = validate_code(invalid)
    assert not is_valid
    assert "语法错误" in error

    # 空代码
    is_valid, error = validate_code("")
    assert not is_valid
    assert "代码为空" in error

    print("[PASS] test_validate_code")


def test_code_security():
    """测试代码安全检查。"""
    # 危险属性调用（os 导入放行，但 os.system 被 DANGEROUS_ATTRS 拦截）
    code1 = "import os; os.system('rm -rf /')"
    is_valid, error = validate_code(code1)
    assert not is_valid
    assert "system" in error

    # 危险函数调用
    code2 = "eval('print(1)')"
    is_valid, error = validate_code(code2)
    assert not is_valid
    assert "eval" in error

    # 危险模块导入
    code3 = "import subprocess; print('hello')"
    is_valid, error = validate_code(code3)
    assert not is_valid
    assert "subprocess" in error

    # 安全代码
    code4 = "import numpy as np; print(np.array([1,2,3]))"
    is_valid, _ = validate_code(code4)
    assert is_valid

    print("[PASS] test_code_security")


def test_check_dependencies():
    """测试依赖检查。"""
    # 缺少依赖
    code1 = "import pulp; print('hello')"
    missing = check_dependencies(code1)
    # pulp 可能未安装，所以可能在 missing 中

    # 已安装依赖
    code2 = "import numpy as np; print('hello')"
    missing = check_dependencies(code2)
    assert "numpy" not in missing

    print("[PASS] test_check_dependencies")


if __name__ == "__main__":
    test_strip_numbering()
    test_dedup()
    test_parse_llm_json()
    test_match_algorithm()
    test_match_subproblem()
    test_validate_code()
    test_code_security()
    test_check_dependencies()
    print("\n所有测试通过！")
