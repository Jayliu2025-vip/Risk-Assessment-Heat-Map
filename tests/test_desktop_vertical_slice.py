"""End-to-end contract for the local, synthetic desktop workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from tools.common import assess_all, load_dataset


class AlwaysFailingOcr:
    def read(self, image_path: Path) -> str:
        from desktop.ocr import OcrError
        raise OcrError("OCR_FAILED", "synthetic test failure")


class DesktopVerticalSliceTests(unittest.TestCase):
    def test_synthetic_desktop_acceptance_returns_a_private_verified_result(self) -> None:
        from tools.run_synthetic_desktop_acceptance import run_acceptance

        with tempfile.TemporaryDirectory() as temporary:
            result = run_acceptance(Path(temporary), keep_output=True)
            self.assertEqual(result["findings"], 3)
            self.assertEqual(result["accepted"], 2)
            self.assertEqual(result["excluded"], 1)
            self.assertEqual(result["period"], "2026H2")
            self.assertIn("2026H2", result["periods"])
            workbook = load_workbook(result["workbook"], data_only=False)
            try:
                self.assertTrue(any(workbook["风险登记册"].cell(row, 1).value == "R025"
                                    for row in range(4, workbook["风险登记册"].max_row + 1)))
            finally:
                workbook.close()
            config, risks, controls = load_dataset(result["export_dir"] / "2026H2", result["export_dir"] / "config.json")
            self.assertEqual(result["residual"], assess_all(risks, controls, config))
            self.assertTrue(result["source_unchanged"])
            self.assertTrue(result["temp_clean"])
            self.assertEqual(result["source_sha256"], result["post_source_sha256"])
            self.assertFalse(Path(result["task_temp_dir"]).exists())
            self.assertEqual(result["ocr"], {"locator": "第 3 页", "method": "ocr"})
            self.assertTrue(all(request["_remote_host"] in {"127.0.0.1", "::1"} for request in result["server_requests"]))
            self.assertNotIn("authorization", str(result["server_requests"]).lower())
            raw_db = Path(result["state_db"]).read_bytes()
            for forbidden in (b"sk-synthetic", b"VERTICAL-SYNTHETIC-FULL-BODY-SENTINEL-ONLY",
                              str(Path(result["report"]).resolve()).encode("utf-8"),
                              str(Path(result["source"]).resolve()).encode("utf-8")):
                self.assertNotIn(forbidden, raw_db)
            report_path = str(Path(result["report"]).resolve()).encode("utf-8")
            self.assertTrue(all(report_path not in Path(path).read_bytes() for path in result["output_files"]))

    def test_acceptance_rejects_ocr_vision_fallback(self) -> None:
        from tools.run_synthetic_desktop_acceptance import AcceptanceError, run_acceptance

        with tempfile.TemporaryDirectory() as temporary:
            with patch("tools.run_synthetic_desktop_acceptance.RapidOcrEngine", return_value=AlwaysFailingOcr()):
                with self.assertRaisesRegex(AcceptanceError, "OCR_NOT_PROVEN"):
                    run_acceptance(Path(temporary), keep_output=True)

    def test_acceptance_rejects_broken_pending_review_api(self) -> None:
        from desktop.pipeline import AnalysisPipeline
        from tools.run_synthetic_desktop_acceptance import AcceptanceError, run_acceptance

        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(AnalysisPipeline, "review_findings", return_value=[]):
                with self.assertRaisesRegex(AcceptanceError, "REVIEW_API_INVALID"):
                    run_acceptance(Path(temporary), keep_output=True)

    def test_offline_mode_blocks_external_socket_before_any_request(self) -> None:
        from tools.run_synthetic_desktop_acceptance import run_acceptance

        with tempfile.TemporaryDirectory() as temporary:
            result = run_acceptance(Path(temporary), keep_output=True, offline_verify=True)
        self.assertTrue(result["offline_guard"])


if __name__ == "__main__":
    unittest.main()
