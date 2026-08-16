from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.builder import inject_iron_lock, remove_iron_lock, validate_code


def test_inject_real_assert():
    """注入的必须是真实 assert False（物理死锁），而非注释。"""
    locked = inject_iron_lock("print('hi')")
    first = locked.splitlines()[0].strip()
    assert first.startswith("assert False"), f"首行不是真 assert: {first!r}"
    try:
        exec(locked)
        raise AssertionError("代码竟能直接运行，铁律失效!")
    except AssertionError:
        pass
    print("[PASS] test_inject_real_assert")


def test_roundtrip():
    """Solver 剥除后应还原为原始可执行代码。"""
    code = "print('hi')"
    locked = inject_iron_lock(code)
    assert remove_iron_lock(locked) == code
    assert remove_iron_lock(code) == code  # 无锁代码无副作用
    print("[PASS] test_roundtrip")


def test_validate_passes_on_locked():
    """安全检查应接受锁定代码（assert 为合法语法）。"""
    ok, err = validate_code(inject_iron_lock("import numpy as np\nprint(np.array([1]))"))
    assert ok, f"锁定代码被错误拦截: {err}"
    print("[PASS] test_validate_passes_on_locked")


if __name__ == "__main__":
    test_inject_real_assert()
    test_roundtrip()
    test_validate_passes_on_locked()
    print("\n所有测试通过！")
