"""代码落盘：把求解代码保存为 .py / .ipynb / 输出 .txt，便于人工逐行审核。

nbformat 可用时生成标准 notebook；不可用时用最小合法 ipynb v4 JSON 兜底（不报错）。
"""
from __future__ import annotations

import json
from pathlib import Path


def make_notebook(code: str, outputs: str | None = None) -> dict:
    """构造最小合法 ipynb v4。"""
    import random
    import string

    cell: dict = {
        "cell_type": "code",
        "execution_count": None,
        "id": "".join(random.choices(string.ascii_lowercase + string.digits, k=8)),
        "metadata": {},
        "outputs": [],
        "source": code.splitlines(keepends=True),
    }
    if outputs:
        cell["outputs"] = [{
            "name": "stdout",
            "output_type": "stream",
            "text": outputs.splitlines(keepends=True),
        }]
    return {
        "cells": [cell],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def save_code_artifact(code: str, output: str | None, out_dir: Path, name: str) -> Path:
    """保存 code → .py + .ipynb，output → _output.txt。返回 out_dir。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.py").write_text(code, encoding="utf-8")
    if output:
        (out_dir / f"{name}_output.txt").write_text(output, encoding="utf-8")
    nb = make_notebook(code, output)
    try:
        import nbformat
        nbformat.write(nbformat.from_dict(nb), out_dir / f"{name}.ipynb")
    except ImportError:
        (out_dir / f"{name}.ipynb").write_text(
            json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return out_dir
