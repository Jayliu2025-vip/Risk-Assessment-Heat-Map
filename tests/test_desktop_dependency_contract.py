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
        expected_licenses = {
            "pywebview": "BSD-3-Clause",
            "pypdfium2": "Apache-2.0 OR BSD-3-Clause",
            "python-docx": "MIT",
            "RapidOCR": "Apache-2.0",
            "ONNX Runtime": "MIT",
            "Pillow": "MIT-CMU",
            "httpx": "BSD-3-Clause",
            "keyring": "MIT",
            "openpyxl": "MIT",
            "matplotlib": "Matplotlib license (PSF-compatible)",
            "PyInstaller": "GPL-2.0-or-later (bootloader exception)",
            "ReportLab": "BSD-3-Clause",
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
        for name, version in expected.items():
            row_version, fields = rows[name]
            self.assertEqual(row_version, version)
            license_name, homepage, bundled, obligation = fields
            self.assertEqual(license_name, expected_licenses[name])
            self.assertRegex(homepage, r"https://\S+")
            self.assertTrue(bundled)
            self.assertTrue(obligation)
            self.assertNotIn(obligation.lower(), {"-", "none", "n/a"})

        pypdfium2 = rows["pypdfium2"][1]
        self.assertIn("native PDFium binaries", pypdfium2[2])
        self.assertIn("PDFium is separately licensed under BSD-3-Clause", pypdfium2[2])
        self.assertIn("copy the wheel's bundled PDFium license files", pypdfium2[3])

        rapidocr = rows["RapidOCR"][1]
        self.assertIn("OCR model assets", rapidocr[2])
        self.assertIn("retain notices", rapidocr[3])
        self.assertIn("exact model files", rapidocr[3])

        onnx = rows["ONNX Runtime"][1]
        self.assertIn("native runtime binaries", onnx[2])
        self.assertIn("retain any notices", onnx[3])

        pywebview = rows["pywebview"][1]
        self.assertIn("Windows webview", pywebview[2])
        self.assertIn("BSD-3-Clause", pywebview[3])

        keyring = rows["keyring"][1]
        self.assertIn("OS components", keyring[2])
        self.assertIn("MIT", keyring[3])

        pyinstaller = rows["PyInstaller"][1]
        self.assertIn("native binary", pyinstaller[2])
        self.assertIn("bootloader exception", pyinstaller[3])
        self.assertIn("retain its license files", pyinstaller[3])


if __name__ == "__main__":
    unittest.main()
