"""Local PDF and DOCX extraction with explicit OCR and vision-review routing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pypdfium2
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from desktop.models import ExtractedBlock


class OcrReader(Protocol):
    def read(self, image_path: Path) -> str: ...


class ExtractionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(slots=True)
class ExtractionResult:
    blocks: list[ExtractedBlock]
    method: str


def text_is_usable(text: str) -> bool:
    compact = "".join(text.split()) if isinstance(text, str) else ""
    if len(compact) < 40:
        return False
    printable = sum(char.isprintable() and char != "\ufffd" for char in compact)
    return printable / len(compact) >= 0.90


def _safe_temp_root(temp_dir: Path) -> Path:
    root = Path(temp_dir)
    if not root.exists() or not root.is_dir():
        raise ExtractionError("TEMP_DIR_INVALID", "任务临时目录不可用")
    return root.resolve()


def _output_path(root: Path, filename: str) -> Path:
    target = (root / filename).resolve()
    if root not in target.parents:
        raise ExtractionError("TEMP_DIR_INVALID", "任务临时目录不可用")
    return target


def _close(resource: object | None) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _read_ocr(ocr: OcrReader, image_path: Path, locator: str) -> ExtractedBlock:
    text = ocr.read(image_path)
    if text_is_usable(text):
        return ExtractedBlock(locator, text, "ocr", image_path=str(image_path))
    return ExtractedBlock(locator, "需要视觉复核：OCR文本质量不足。", "vision_required", True, str(image_path))


def _render_pdf_page(page: object, output_path: Path) -> None:
    bitmap = None
    image = None
    try:
        bitmap = page.render(scale=2.0)
        image = bitmap.to_pil()
        image.save(output_path, format="PNG")
    finally:
        if image is not None:
            image.close()
        _close(bitmap)


def _extract_pdf(path: Path, temp_root: Path, ocr: OcrReader) -> list[ExtractedBlock]:
    document = None
    try:
        document = pypdfium2.PdfDocument(path)
        blocks: list[ExtractedBlock] = []
        for index in range(len(document)):
            page = text_page = None
            locator = f"第 {index + 1} 页"
            try:
                page = document[index]
                try:
                    text_page = page.get_textpage()
                    text = text_page.get_text_bounded()
                except Exception:
                    text = ""
                if text_is_usable(text):
                    blocks.append(ExtractedBlock(locator, text, "text"))
                else:
                    image_path = _output_path(temp_root, f"pdf_page_{index + 1:04d}.png")
                    _render_pdf_page(page, image_path)
                    blocks.append(_read_ocr(ocr, image_path, locator))
            finally:
                _close(text_page)
                _close(page)
        return blocks
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("PDF_READ_FAILED", f"无法读取PDF文件：{path.name}") from exc
    finally:
        _close(document)


def _image_suffix(content_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }.get(content_type, ".img")


def _paragraph_images(paragraph: Paragraph, temp_root: Path, sequence: int) -> list[Path]:
    images: list[Path] = []
    for image_index, blip in enumerate(paragraph._p.xpath(".//a:blip"), start=1):
        relationship_id = blip.get(qn("r:embed"))
        if not relationship_id:
            continue
        relationship = paragraph.part.rels.get(relationship_id)
        if relationship is None or not hasattr(relationship.target_part, "blob"):
            continue
        suffix = _image_suffix(getattr(relationship.target_part, "content_type", ""))
        image_path = _output_path(temp_root, f"word_image_{sequence:04d}_{image_index:02d}{suffix}")
        image_path.write_bytes(relationship.target_part.blob)
        images.append(image_path)
    return images


def _table_text(table: Table) -> str:
    return "\n".join("\t".join(cell.text.strip() for cell in row.cells) for row in table.rows)


def _extract_docx(path: Path, temp_root: Path, ocr: OcrReader) -> list[ExtractedBlock]:
    try:
        document = Document(path)
        blocks: list[ExtractedBlock] = []
        paragraph_count = table_count = 0
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraph_count += 1
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if text:
                    blocks.append(ExtractedBlock(f"Word 段落 {paragraph_count}", text, "text"))
                for image_path in _paragraph_images(paragraph, temp_root, paragraph_count):
                    blocks.append(_read_ocr(ocr, image_path, f"Word 段落 {paragraph_count}"))
            elif child.tag.endswith("}tbl"):
                table_count += 1
                text = _table_text(Table(child, document)).strip()
                if text:
                    blocks.append(ExtractedBlock(f"Word 表格 {table_count}", text, "text"))
        return blocks
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("DOCX_READ_FAILED", f"无法读取Word文件：{path.name}") from exc


def _aggregate_method(blocks: list[ExtractedBlock]) -> str:
    methods = {block.method for block in blocks}
    if len(methods) == 1:
        return next(iter(methods), "text")
    return "mixed"


def extract_report(path: Path, temp_dir: Path, ocr: OcrReader) -> ExtractionResult:
    source = Path(path)
    if not source.exists():
        raise ExtractionError("INPUT_NOT_FOUND", f"输入文件不存在：{source.name}")
    if not source.is_file():
        raise ExtractionError("INPUT_NOT_FILE", f"输入不是文件：{source.name}")
    temp_root = _safe_temp_root(temp_dir)
    suffix = source.suffix.lower()
    if suffix == ".doc":
        raise ExtractionError("DOC_LEGACY_UNSUPPORTED", f"不支持旧版Word文件：{source.name}")
    if suffix == ".pdf":
        blocks = _extract_pdf(source, temp_root, ocr)
    elif suffix == ".docx":
        blocks = _extract_docx(source, temp_root, ocr)
    else:
        raise ExtractionError("FILE_TYPE_UNSUPPORTED", f"不支持的文件类型：{source.name}")
    return ExtractionResult(blocks, _aggregate_method(blocks))
