import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopDependencyContractTests(unittest.TestCase):
    def test_runtime_dependencies_are_pinned_and_pdfium_boundary_is_explicit(self):
        requirements = (ROOT / "requirements-desktop.txt").read_text(encoding="utf-8")
        required = {
            "pywebview==6.2.1",
            "pypdfium2==5.13.0",
            "python-docx==1.2.0",
            "rapidocr==3.9.2",
            "onnxruntime==1.29.0",
            "Pillow==12.3.0",
            "httpx==0.28.1",
            "keyring==25.7.0",
            "openpyxl==3.1.5",
            "matplotlib==3.11.1",
        }
        self.assertTrue(required.issubset(set(requirements.splitlines())))
        self.assertNotIn("pymupdf", requirements.lower())
        self.assertNotIn("fitz", requirements.lower())

    def test_build_dependencies_and_notices_cover_packaging_boundary(self):
        build = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
        self.assertIn("-r requirements-desktop.txt", build)
        self.assertIn("pyinstaller==6.22.2", build)
        self.assertIn("reportlab==5.0.1", build)

        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for term in (
            "pywebview",
            "pypdfium2",
            "PDFium",
            "RapidOCR",
            "ONNX Runtime",
            "keyring",
            "PyInstaller",
        ):
            self.assertIn(term, notices)


if __name__ == "__main__":
    unittest.main()
