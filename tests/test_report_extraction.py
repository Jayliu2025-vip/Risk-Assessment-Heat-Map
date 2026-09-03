from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import unittest

from desktop.extraction import ExtractionError, extract_report, text_is_usable
from desktop.ocr import RapidOcrEngine


FIXTURES = Path(__file__).parent / "fixtures" / "generated"


class FakeOcr:
    def __init__(self, text: str = "Synthetic audit finding: approval was bypassed."):
        self.text = text
        self.calls: list[Path] = []

    def read(self, image_path: Path) -> str:
        self.calls.append(Path(image_path))
        return self.text


class ReportExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="report-extraction-"))

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_text_is_usable_rejects_blank_short_and_replacement_text(self):
        self.assertFalse(text_is_usable(" \n\t "))
        self.assertFalse(text_is_usable("short text"))
        self.assertFalse(text_is_usable("a" * 41 + "\ufffd" * 10))
        self.assertTrue(text_is_usable("a" * 40))

    def test_text_pdf_has_two_text_blocks_without_ocr(self):
        ocr = FakeOcr()
        result = extract_report(FIXTURES / "text_report.pdf", self.temp, ocr)
        self.assertEqual(result.method, "text")
        self.assertEqual([block.locator for block in result.blocks], ["第 1 页", "第 2 页"])
        self.assertTrue(all(block.method == "text" for block in result.blocks))
        self.assertEqual(ocr.calls, [])

    def test_scanned_pdf_routes_page_through_ocr(self):
        ocr = FakeOcr()
        result = extract_report(FIXTURES / "scan_report.pdf", self.temp, ocr)
        self.assertEqual(result.method, "ocr")
        self.assertEqual(len(ocr.calls), 1)
        self.assertEqual(result.blocks[0].locator, "第 1 页")
        self.assertEqual(result.blocks[0].method, "ocr")

    def test_failed_ocr_routes_to_vision_and_keeps_contained_render(self):
        result = extract_report(FIXTURES / "scan_report.pdf", self.temp, FakeOcr("too short"))
        block = result.blocks[0]
        self.assertEqual(result.method, "vision_required")
        self.assertEqual(block.method, "vision_required")
        self.assertTrue(block.needs_review)
        self.assertIsNotNone(block.image_path)
        image = Path(block.image_path)
        self.assertTrue(image.is_file())
        self.assertIn(self.temp.resolve(), image.resolve().parents)

    def test_docx_preserves_paragraph_table_order_and_serializes_cells(self):
        result = extract_report(FIXTURES / "report.docx", self.temp, FakeOcr())
        self.assertEqual(result.method, "text")
        self.assertEqual([block.locator for block in result.blocks], ["Word 段落 1", "Word 段落 2", "Word 表格 1", "Word 段落 3"])
        self.assertIn("Synthetic control\tSynthetic status", result.blocks[2].text)
        self.assertIn("Approval review\tBypassed", result.blocks[2].text)

    def test_mixed_docx_routes_embedded_image_in_document_order(self):
        ocr = FakeOcr()
        result = extract_report(FIXTURES / "mixed_report.docx", self.temp, ocr)
        self.assertEqual(result.method, "mixed")
        self.assertEqual([block.method for block in result.blocks], ["text", "text", "ocr", "text"])
        self.assertEqual(result.blocks[2].locator, "Word 段落 3")
        self.assertEqual(len(ocr.calls), 1)

    def test_unsupported_and_corrupt_inputs_have_stable_safe_errors(self):
        legacy = self.temp / "old.doc"
        legacy.write_bytes(b"synthetic")
        unsupported = self.temp / "input.txt"
        unsupported.write_text("synthetic", encoding="utf-8")
        corrupt_pdf = self.temp / "bad.pdf"
        corrupt_pdf.write_bytes(b"not a pdf")
        corrupt_docx = self.temp / "bad.docx"
        corrupt_docx.write_bytes(b"not a docx")
        cases = ((legacy, "DOC_LEGACY_UNSUPPORTED"), (unsupported, "FILE_TYPE_UNSUPPORTED"), (corrupt_pdf, "PDF_READ_FAILED"), (corrupt_docx, "DOCX_READ_FAILED"))
        for path, code in cases:
            with self.subTest(path=path.name):
                with self.assertRaises(ExtractionError) as caught:
                    extract_report(path, self.temp, FakeOcr())
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(str(path.parent), caught.exception.message)

    def test_temp_root_must_contain_generated_outputs(self):
        outside = self.temp / "missing" / "nested"
        with self.assertRaises(ExtractionError) as caught:
            extract_report(FIXTURES / "scan_report.pdf", outside, FakeOcr())
        self.assertEqual(caught.exception.code, "TEMP_DIR_INVALID")

    def test_rapid_ocr_engine_joins_injected_result_texts(self):
        @dataclass
        class Result:
            txts: list[str]

        engine = RapidOcrEngine(engine=lambda _: Result(["alpha", "beta"]))
        self.assertEqual(engine.read(Path("synthetic.png")), "alpha\nbeta")

    def test_real_local_ocr_smoke_reads_synthetic_scan(self):
        result = extract_report(FIXTURES / "scan_report.pdf", self.temp, RapidOcrEngine())
        normalized = " ".join(result.blocks[0].text.lower().split())
        self.assertIn("synthetic", normalized)
        self.assertIn("approval", normalized)


if __name__ == "__main__":
    unittest.main()
