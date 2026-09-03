import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class DesktopDependencyContractTests(unittest.TestCase):
    def test_runtime_dependencies_are_pinned_and_pdfium_boundary_is_explicit(self):
        requirements = (ROOT / "requirements-desktop.txt").read_text(encoding="utf-8")
        required = (
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
        )
        lines = [line.strip() for line in requirements.splitlines() if line.strip()]
        self.assertEqual(lines, list(required))
        self.assertNotIn("pymupdf", requirements.lower())
        self.assertNotIn("fitz", requirements.lower())

    def test_build_dependencies_and_notices_cover_packaging_boundary(self):
        build = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")
        self.assertEqual(
            [line.strip() for line in build.splitlines() if line.strip()],
            ["-r requirements-desktop.txt", "pyinstaller==6.22.2", "reportlab==5.0.1"],
        )

        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        normalized_notices = " ".join(notices.split())
        self.assertIn("not a claim that license texts are already present", normalized_notices)
        self.assertIn("generate a license bundle from the exact installed wheels", normalized_notices)

        expected = {
            "pywebview": "6.2.1",
            "pypdfium2": "5.13.0",
            "python-docx": "1.2.0",
            "RapidOCR": "3.9.2",
            "ONNX Runtime": "1.29.0",
            "Pillow": "12.3.0",
            "httpx": "0.28.1",
            "keyring": "25.7.0",
            "openpyxl": "3.1.5",
            "matplotlib": "3.11.1",
            "PyInstaller": "6.22.2",
            "ReportLab": "5.0.1",
        }
        rows = {}
        for line in notices.splitlines():
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            if len(cells) != 5 or not cells[0].startswith("["):
                continue
            match = re.match(r"\[([^]]+)\]\([^)]*\)\s+([0-9][^ ]*)$", cells[0])
            if match:
                rows[match.group(1)] = (match.group(2), cells[1:])

        self.assertEqual(set(rows), set(expected))
        self.assertEqual(rows["pypdfium2"][1][0], "Apache-2.0 OR BSD-3-Clause")
        for name, version in expected.items():
            row_version, fields = rows[name]
            self.assertEqual(row_version, version)
            license_name, homepage, bundled, obligation = fields
            self.assertTrue(license_name)
            self.assertRegex(homepage, r"https?://\S+")
            self.assertTrue(bundled)
            self.assertTrue(obligation)


if __name__ == "__main__":
    unittest.main()
