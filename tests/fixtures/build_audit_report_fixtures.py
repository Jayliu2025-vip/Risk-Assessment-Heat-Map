"""Build deterministic, entirely synthetic report fixtures for extraction tests."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parent / "generated"
STAMP = "SYNTHETIC TEST DATA"
FINDING = "Synthetic audit finding: approval was bypassed."


def _font(size: int) -> ImageFont.ImageFont:
    return ImageFont.truetype("arial.ttf", size)


def _finding_image(path: Path) -> None:
    image = Image.new("RGB", (1600, 760), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 55), STAMP, fill="black", font=_font(40))
    draw.text((70, 180), FINDING, fill="black", font=_font(48))
    draw.multiline_text(
        (70, 290),
        "This is synthetic evidence for automated extraction tests.\n"
        "No real audit report, person, company, or operational event is represented.",
        fill="black",
        font=_font(34),
        spacing=20,
    )
    image.save(path)


def _text_pdf(path: Path) -> None:
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    pages = (
        "Synthetic audit report page one documents a simulated approval control gap. "
        "The example is fabricated for extraction testing and contains no real evidence.",
        "Synthetic audit report page two records a made-up remediation discussion. "
        "All names, events, conclusions, and amounts are fictional test material only.",
    )
    for text in pages:
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(72, 740, STAMP)
        canvas.setFont("Helvetica", 12)
        y = 690
        for line in (text[:86], text[86:]):
            canvas.drawString(72, y, line)
            y -= 22
        canvas.showPage()
    canvas.save()


def _scan_pdf(path: Path, raster: Path) -> None:
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.drawImage(str(raster), 42, 220, width=528, height=251)
    canvas.save()


def _docx(path: Path, image: Path, mixed: bool) -> None:
    document = Document()
    document.core_properties.subject = "虚构测试资料 / SYNTHETIC TEST DATA"
    document.core_properties.comments = "Synthetic fixture; no real audit report."
    document.add_heading("虚构测试资料 / SYNTHETIC TEST DATA", level=1)
    if mixed:
        document.add_paragraph("Synthetic opening paragraph before the embedded finding.")
        document.add_picture(str(image), width=Inches(5.8))
        document.add_paragraph("Synthetic closing paragraph after the embedded finding.")
    else:
        document.add_paragraph("Synthetic first paragraph keeps document order visible.")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Synthetic control"
        table.cell(0, 1).text = "Synthetic status"
        table.cell(1, 0).text = "Approval review"
        table.cell(1, 1).text = "Bypassed in fictional sample"
        document.add_paragraph("Synthetic final paragraph follows the table in document order.")
    document.save(path)


def build() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    raster = ROOT / "synthetic_finding.png"
    _finding_image(raster)
    _text_pdf(ROOT / "text_report.pdf")
    _scan_pdf(ROOT / "scan_report.pdf", raster)
    _docx(ROOT / "report.docx", raster, mixed=False)
    _docx(ROOT / "mixed_report.docx", raster, mixed=True)
    return ROOT


if __name__ == "__main__":
    build()
