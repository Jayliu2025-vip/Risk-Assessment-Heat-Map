"""End-to-end contract for the local, synthetic desktop workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from tools.common import assess_all, load_dataset


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
            self.assertTrue(all(request["_remote_host"] in {"127.0.0.1", "::1"} for request in result["server_requests"]))
            self.assertNotIn("authorization", str(result["server_requests"]).lower())
            raw_db = Path(result["state_db"]).read_bytes()
            for forbidden in (b"sk-synthetic", b"VERTICAL-SYNTHETIC-FULL-BODY-SENTINEL-ONLY",
                              str(Path(result["source"]).resolve()).encode("utf-8")):
                self.assertNotIn(forbidden, raw_db)


if __name__ == "__main__":
    unittest.main()
