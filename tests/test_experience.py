from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.experience import _classify, load_experience, save_experience, record


def test_classify():
    assert _classify("预测未来销量") == "预测"
    assert _classify("优化投放数量") == "优化"
    assert _classify("综合评价方案") == "评价"
    assert _classify("任意内容") == "其他"
    print("[PASS] test_classify")


def test_save_load_roundtrip(tmp_dir: Path):
    """save_experience / load_experience 往返。"""
    from utils import experience

    orig_path, orig_lock = experience.EXPERIENCE_PATH, experience.EXPERIENCE_LOCK
    experience.EXPERIENCE_PATH = tmp_dir / "experience.json"
    experience.EXPERIENCE_LOCK = tmp_dir / "experience.json.lock"
    try:
        save_experience([{"a": 1}])
        assert load_experience() == [{"a": 1}]
    finally:
        experience.EXPERIENCE_PATH, experience.EXPERIENCE_LOCK = orig_path, orig_lock
    print("[PASS] test_save_load_roundtrip")


def test_record_no_deadlock():
    """回归：record() 持锁后不得再嵌套加锁（否则死锁）。

    在子进程内连续调用两次 record，用超时保护防止测试本身挂死。
    """
    proj = str(Path(__file__).parent.parent)
    code = (
        "import sys, tempfile; sys.path.insert(0, r'%s');\n"
        "from pathlib import Path;\n"
        "import utils.experience as exp;\n"
        "d = Path(tempfile.mkdtemp());\n"
        "exp.EXPERIENCE_PATH = d / 'experience.json';\n"
        "exp.EXPERIENCE_LOCK = d / 'experience.json.lock';\n"
        "exp.record('x', '线性规划', True);\n"
        "exp.record('y', '回归分析', False);\n"
        "print('OK', len(exp.load_experience()))\n"
    ) % proj
    try:
        r = subprocess.run(
            [sys.executable, "-u", "-c", code],
            capture_output=True,
            timeout=20,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("record() 嵌套加锁导致死锁")
    assert r.returncode == 0, f"子进程异常: {r.stderr}"
    assert "OK 2" in r.stdout
    print("[PASS] test_record_no_deadlock")


if __name__ == "__main__":
    test_classify()
    with tempfile.TemporaryDirectory() as td:
        test_save_load_roundtrip(Path(td))
    test_record_no_deadlock()
    print("\n所有测试通过！")
