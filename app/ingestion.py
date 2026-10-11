"""Page-grounded extraction. Archive guards are reused from LearnMargin.

Improvements for policy documents: retained table grids, lazy page previews,
content-addressed identity, explicit OCR state, and no invented Office pages.
"""

import hashlib
import io
import re
from pathlib import Path

import fitz
from PIL import Image, ImageOps
from .vendor.archive_guard import _check_zip

EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".md",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}
MAX_BYTES = 50 * 1024 * 1024


def extract(path: Path, name=None):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("文件超过 50 MB，请拆分后导入")
    ext = path.suffix.lower()
    if ext not in EXTENSIONS:
        raise ValueError("支持 PDF、DOCX、PPTX、XLSX、TXT、MD、CSV 和图片；旧版 Office 请先另存为新格式")
    units = []

    def add(label, text, tables=None, image=False):
        if len(units) >= 300 or sum(len(u["text"]) for u in units) + len(text) > 2_000_000:
            raise ValueError("材料超过 300 个单元或 200 万字，请拆分后导入")
        units.append(
            dict(
                index=len(units) + 1,
                label=label,
                text=text,
                tables=tables or [],
                needs_ocr=image,
                method="image" if image else "native",
            )
        )

    if ext == ".pdf":
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("请导入已解除密码的 PDF")
            if len(doc) > 300:
                raise ValueError("PDF 超过 300 页，请拆分")
            for i, page in enumerate(doc):
                text = page.get_text(sort=True)
                tables = []
                try:
                    tables = [t.extract() for t in page.find_tables().tables]
                except Exception:
                    pass
                add(f"第 {i + 1} 页", text, tables, len(text.strip()) < 40)
                units[-1]["needs_visual_check"] = bool(
                    tables or "\ufffd" in text or re.search(r"[∑]|计算公式|公式为", text)
                )
    elif ext in {".docx", ".pptx", ".xlsx"}:
        _check_zip(path)
        if ext == ".docx":
            from docx import Document

            doc = Document(path)
            # Preserve source order, using actual paragraph/table labels, not page numbers.
            from docx.text.paragraph import Paragraph
            from docx.table import Table

            for child in doc.element.body:
                if child.tag.endswith("}p"):
                    text = Paragraph(child, doc).text
                    if text.strip():
                        add(f"段落 {len(units) + 1}", text)
                elif child.tag.endswith("}tbl"):
                    rows = [[c.text for c in r.cells] for r in Table(child, doc).rows]
                    add(
                        f"表格 {len(units) + 1}",
                        "\n".join(" | ".join(r) for r in rows),
                        [rows],
                    )
        elif ext == ".pptx":
            from pptx import Presentation

            for i, slide in enumerate(Presentation(path).slides):
                texts = []
                tables = []

                def scan(shapes):
                    for s in shapes:
                        if hasattr(s, "shapes"):
                            scan(s.shapes)
                        if s.has_text_frame:
                            texts.append(s.text)
                        if s.has_table:
                            rows = [[c.text for c in r.cells] for r in s.table.rows]
                            tables.append(rows)
                            texts.append("\n".join(" | ".join(r) for r in rows))

                scan(slide.shapes)
                add(f"幻灯片 {i + 1}", "\n".join(texts), tables)
        else:
            from openpyxl import load_workbook

            book = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in book:
                    if sheet.max_row and sheet.max_row > 20000:
                        raise ValueError("工作表超过 20000 行")
                    rows = [
                        [str(x) if x is not None else "" for x in row]
                        for row in sheet.iter_rows(values_only=True)
                    ]
                    add(
                        f"工作表 {sheet.title}",
                        "\n".join(" | ".join(r) for r in rows),
                        [rows],
                    )
            finally:
                book.close()
    elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
        with Image.open(path) as im:
            if im.width * im.height > 40_000_000:
                raise ValueError("图片超过 4000 万像素")
        add("图片 1", "", image=True)
    else:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
        for i in range(0, len(text), 12000):
            add(f"文本段 {i // 12000 + 1}", text[i : i + 12000])
    if not units:
        raise ValueError("文件中没有可读取的内容")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(
        id=digest[:24],
        sha256=digest,
        name=name or path.name,
        kind=ext,
        units=units,
        path=str(path),
        warnings=[],
    )


def preview(doc, index):
    if index < 1 or index > len(doc["units"]):
        raise ValueError("来源位置不存在")
    if doc["kind"] == ".pdf":
        with fitz.open(doc["path"]) as pdf:
            page = pdf[index - 1]
            scale = min(2, 1800 / max(page.rect.width, page.rect.height))
            return page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")
    if doc["kind"] in {".png", ".jpg", ".jpeg", ".webp"}:
        with Image.open(doc["path"]) as original:
            im = ImageOps.exif_transpose(original)
            im.thumbnail((1800, 1800))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    raise ValueError("此格式使用文本和表格预览")
