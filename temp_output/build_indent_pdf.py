# -*- coding: utf-8 -*-
"""转换缩进版论文为 typst 并编译 PDF"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Lawson\Desktop\2026数学建模国赛\mathagent")
sys.path.insert(0, str(ROOT))
from utils.typst_export import md_to_typst

SRC = ROOT / "data/results/paper_20260817_150809_indent.md"
TYP = SRC.with_suffix(".typ")
PDF = SRC.with_suffix(".pdf")

md = SRC.read_text(encoding="utf-8")
typ = md_to_typst(md)
TYP.write_text(typ, encoding="utf-8")
print("typ 生成 OK")

# typst 行首全角空格处理：转换器若未处理会报错；检查后决定
import re
lead = re.findall(r"^　　", typ, re.MULTILINE)
print("typ 中行首全角空格数:", len(lead))

r = subprocess.run(
    [str(ROOT / "tools/typst-x86_64-pc-windows-msvc/typst.exe"), "compile",
     str(TYP), str(PDF)],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
if r.returncode == 0:
    print("PDF 编译成功:", PDF.stat().st_size, "bytes")
else:
    err = r.stderr or r.stdout
    lines = err.splitlines()
    info = [l for l in lines if ".typ:" in l]
    print("错误:", info[0].strip() if info else lines[-1][:120])
