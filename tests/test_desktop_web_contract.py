"""Static contract for the synthetic-only desktop report review surface."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopWebContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (ROOT / "web" / "risk_heatmap.html").read_text(encoding="utf-8")
        self.script = (ROOT / "web" / "desktop_report.js").read_text(encoding="utf-8")
        self.css = (ROOT / "web" / "desktop_report.css").read_text(encoding="utf-8")

    def test_desktop_surface_is_hidden_until_the_webview_event(self) -> None:
        for element_id in (
            "desktop-report-nav", "report-step-upload", "report-step-extract",
            "report-step-review", "report-step-commit", "report-source-viewer",
            "report-finding-form", "report-change-preview", "report-workbook-name",
            "report-risk-decisions",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("desktop-report-shell[hidden]", self.css)
        self.assertIn("pywebviewready", self.script)
        self.assertIn("window.pywebview.api", self.script)
        self.assertIn("addEventListener(\"pywebviewready\"", self.script)

    def test_review_form_has_only_the_approved_fields(self) -> None:
        approved = (
            "title", "fact_summary", "source_page", "source_excerpt", "matched_risk_id",
            "domain", "likelihood", "imp_financial", "imp_compliance", "imp_operation",
            "imp_reputation", "imp_fraud", "imp_strategy", "imp_data", "imp_hse",
            "rationale", "needs_review", "review_status",
        )
        for name in approved:
            self.assertIn(f'data-finding-field="{name}"', self.html)
        for banned in ("unit", "amount", "ocr_confidence", "model_confidence", "dimension_evidence"):
            self.assertNotIn(f'data-finding-field="{banned}"', self.html)

    def test_load_hook_validates_and_replaces_one_period_atomically(self) -> None:
        self.assertIn("window.RAHMDesktop.loadPeriodData", self.html)
        for marker in ("SAFE_PERIOD", "isDesktopRisk", "isDesktopControl", "nextData", "persist();renderAll();"):
            self.assertIn(marker, self.html)
        self.assertIn('<script src="desktop_report.js"></script>', self.html)
        self.assertIn('<link rel="stylesheet" href="desktop_report.css">', self.html)
        self.assertIn('const APP_VERSION = "1.2";', self.html)

    def test_desktop_script_consumes_production_bridge_shapes(self) -> None:
        for marker in (
            "period_data.period", "period_data.risks", "period_data.controls",
            "patchFindings", "bootstrap?.domains", "image_data_url", "new_controls",
            "excluded_count", "new_risks", "updated_risks", "warnings",
        ):
            self.assertIn(marker, self.script)
        for stale_marker in ("assessed_risks||result.risks", "control_replacements", "excluded_findings"):
            self.assertNotIn(stale_marker, self.script)

    def test_desktop_script_uses_nested_scores_controls_and_race_guards(self) -> None:
        for marker in ("impact_scores", "load_controls", "report-controls-confirmed", "previewGeneration",
                       "selectedFindingId", "startBusy", "pollGeneration", "previewBusy",
                       "analysisWorkbook", "batchWorkbook", "controlsWorkbookToken"):
            self.assertIn(marker, self.script)
        self.assertNotIn("payload[key]=value;", self.script)

    def test_workbook_is_selected_before_analysis_and_cannot_switch_at_commit(self) -> None:
        self.assertIn('id="report-choose-workbook"', self.html)
        self.assertIn("选择风险目录工作簿", self.html)
        self.assertIn('id="batch-choose-workbook"', self.html)
        self.assertIn("选择当前正式工作簿", self.html)
        self.assertNotIn("选择工作簿并预览", self.html)
        self.assertIn('call("start_analysis", selectedReport, analysisWorkbook, "CATALOG"', self.script)
        self.assertIn('call("create_catalog_batch", selectedCatalogIds, batchWorkbook, period)', self.script)
        self.assertNotIn('call("choose_report", "workbook")', self.script.split("async function preview", 1)[1])

    def test_decision_ui_preserves_merge_lineage_owner_and_remediation(self) -> None:
        for marker in ("merged_finding_ids", "merged_into", "ownerDeptByFinding",
                       "remediationByFinding", "remediation_status", "report-risk-decisions"):
            self.assertIn(marker, self.script)
        self.assertNotIn('owner_dept:"审计部"', self.script)
        self.assertNotIn("被合并项标记为排除", self.script)
        self.assertIn('if (finding.review_status === "已排除") return {action:"exclude",finding_ids};', self.script)

    def test_playwright_package_contract_is_pinned(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertTrue(package["private"])
        self.assertEqual(package["scripts"], {"test:e2e": "playwright test"})
        self.assertEqual(package["devDependencies"], {"@playwright/test": "1.55.0"})
        config = (ROOT / "playwright.config.js").read_text(encoding="utf-8")
        self.assertIn("defineConfig", config)
        self.assertIn("channel: 'chrome'", config)
        self.assertIn("headless: true", config)

    def test_local_browser_dependencies_and_results_are_ignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/node_modules/", ignored)
        self.assertIn("/test-results/", ignored)

    def test_startup_is_empty_and_desktop_never_exposes_sample_action(self) -> None:
        self.assertNotIn("if(!periods().length&&window.SAMPLE_DATA) loadSample();", self.html)
        self.assertIn('$("btn-sample").addEventListener("click",loadSample);', self.html)
        self.assertIn('document.body.classList.add("desktop-mode")', self.script)
        self.assertIn("body.desktop-mode #btn-sample", self.css)


if __name__ == "__main__":
    unittest.main()
