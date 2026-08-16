"""数据前置校验智能体 - 建模前强制检查数据资格。

在建模之前检查用户提供的数据是否满足赛题要求。
任一检查不通过则抛出 DataNotQualifiedError，终止后续流程，
防止 LLM 因数据不足而"编造"或"偷懒用部分数据"。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from agents.base import BaseAgent


class DataNotQualifiedError(Exception):
    """数据资格校验未通过。"""


_SYNONYMS = {
    "时间": ("timestamp", "time", "datetime", "date"),
    "日期": ("date", "datetime", "timestamp"),
    "时段": ("hour", "time", "时段"),
    "波长": ("波长", "波数", "wavelength", "wavenumber", "wave"),
    "波数": ("波长", "波数", "wavelength", "wavenumber", "wave"),
    "反射率": ("反射率", "reflectance", "reflectivity", "反射"),
}


def _column_matches(keyword: str, cols: list[str]) -> bool:
    """关键词与列名匹配：子串匹配，兼容中英文同义表述（时间/timestamp 等）。"""
    kw = keyword.lower()
    if any(kw in c for c in cols):
        return True
    for s in _SYNONYMS.get(kw, ()):
        if any(s in c for c in cols):
            return True
    return False


class DataCheckerAgent(BaseAgent):
    """数据前置校验智能体。

    根据赛题要求，对数据文件进行结构化校验（行数、时间范围、关键字段等）。
    校验规则由赛题文本中的【数据文件说明】或用户自定义规则驱动。
    """

    def __init__(self) -> None:
        super().__init__(role="数据资格校验专家")

    def run(self, data_dir: str, problem_text: str = "") -> dict:
        """校验数据目录下的数据文件。

        Args:
            data_dir: 数据文件所在目录
            problem_text: 赛题文本（含数据说明），用于提取校验规则

        Returns:
            {
                "status": "ok" | "failed",
                "checks": [{"file": str, "passed": bool, "message": str}],
                "error": str | None
            }
        """
        data_path = Path(data_dir)
        if not data_path.exists():
            return self._fail(f"数据目录不存在: {data_dir}")

        # 收集数据文件（递归扫描子目录：附件可能在 data/b2025/ 等子目录）。
        # 跳过验证结果文件（文件名含"验证"/"厚度计算结果"，与 utils/verified_results.py
        # 的 _VERIFIED_KEYWORDS 对齐）——它们是 ground truth，不是建模输入，不参与资格校验
        _VERIFIED_FILE_KEYWORDS = ("验证", "厚度计算结果")
        all_files = (
            sorted(data_path.rglob("*.csv")) + sorted(data_path.rglob("*.xlsx"))
        )
        files = [
            f for f in all_files
            if not any(kw in f.stem for kw in _VERIFIED_FILE_KEYWORDS)
        ]
        if not files:
            return self._fail(f"数据目录 {data_dir} 下未找到 .csv 或 .xlsx 文件")

        # 从赛题提取校验规则
        rules = self._extract_rules(problem_text)

        checks = []
        for f in files:
            result = self._check_file(f, rules)
            checks.append(result)

        passed = all(c["passed"] for c in checks)
        if not passed:
            failed = [c for c in checks if not c["passed"]]
            msg = "；".join(f"{c['file']}: {c['message']}" for c in failed)
            return {
                "status": "failed",
                "checks": checks,
                "error": f"数据资格校验未通过: {msg}",
            }

        self.update_state("data_checks", checks)
        return {"status": "ok", "checks": checks, "error": None}

    # ── 校验规则提取 ──────────────────────────────────────

    @staticmethod
    def _extract_rules(problem_text: str) -> dict:
        """从赛题文本提取校验规则（行数/时间/字段等关键词）。

        默认规则：无（只做基础可读性检查）。
        若赛题含"至少 N 行"、"N 天"、"时间分辨率"等，可提取。
        """
        rules = {"min_rows": None, "keywords": []}
        if not problem_text:
            return rules
        m = re.search(r"至少\s*(\d+)\s*(?:行|个|天|条)", problem_text)
        if m:
            rules["min_rows"] = int(m.group(1))
        # 提取必须包含的关键词（如"时间"、"日期"列）
        for kw in ("时间", "日期", "时段", "波数", "波长", "反射率"):
            if kw in problem_text:
                rules["keywords"].append(kw)
        return rules

    # ── 单文件校验 ────────────────────────────────────────

    def _check_file(self, path: Path, rules: dict) -> dict:
        """校验单个数据文件。"""
        try:
            if path.suffix == ".csv":
                df = self._read_csv(path)
            else:
                df = pd.read_excel(path)
        except Exception as e:
            return {"file": path.name, "passed": False, "message": f"读取失败: {e}"}

        if df is None:
            return {"file": path.name, "passed": False, "message": "读取失败: 无法识别编码"}

        nrows = len(df)
        if nrows == 0:
            return {"file": path.name, "passed": False, "message": "文件为空"}

        # 最小行数校验
        if rules.get("min_rows") and nrows < rules["min_rows"]:
            return {
                "file": path.name, "passed": False,
                "message": f"仅 {nrows} 行，少于要求的 {rules['min_rows']} 行",
            }

        # 关键列校验（子串匹配，容忍"波数 (cm-1)"这类带单位后缀的列名）
        cols = [str(c).lower() for c in df.columns]
        missing = [
            kw for kw in rules.get("keywords", [])
            if not _column_matches(kw, cols)
        ]
        if missing:
            return {
                "file": path.name, "passed": False,
                "message": f"缺少关键列: {missing}",
            }

        return {"file": path.name, "passed": True, "message": f"{nrows} 行数据，校验通过"}

    @staticmethod
    def _read_csv(path: Path):
        """读取 CSV，依次尝试 utf-8 → utf-8-sig → gbk → gb18030。

        中文比赛附件导出的 CSV 常为 GBK 编码，单一 utf-8 会误报读取失败。
        """
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
            try:
                return pd.read_csv(path, encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception:
                return None
        return None

    def _fail(self, msg: str) -> dict:
        return {"status": "failed", "checks": [], "error": msg}


# ── 兼容函数接口 ──────────────────────────────────────────────


def data_checker(data_dir: str, problem_text: str = "") -> dict:
    """兼容旧的函数调用方式。"""
    return DataCheckerAgent().run(data_dir, problem_text)
