from __future__ import annotations

from pathlib import Path


def parse_file(file_path: str | Path) -> str:
    path = Path(file_path)

    if not path.exists():
        print(f"文件不存在：{file_path}")
        return ""

    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)

    if reader is None:
        print(f"不支持的文件格式：{suffix}")
        return ""

    return reader(path)


def _read_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk")
    except Exception as e:
        print(f"读取txt失败：{e}")
        return ""


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        print(f"读取docx失败：{e}")
        return ""


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(
            text for page in reader.pages
            if (text := page.extract_text())
        )
    except Exception as e:
        print(f"读取pdf失败：{e}")
        return ""


_READERS: dict[str, callable] = {
    ".txt": _read_txt,
    ".docx": _read_docx,
    ".pdf": _read_pdf,
}