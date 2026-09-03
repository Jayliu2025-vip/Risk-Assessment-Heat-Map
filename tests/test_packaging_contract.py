"""Contracts for the self-contained Windows desktop package.

These checks intentionally inspect the authored build inputs: producing an
installer is an integration concern and is exercised by the build scripts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    def test_pyinstaller_spec_declares_onedir_resources_hidden_imports_and_exclusions(self):
        spec = (ROOT / "packaging" / "risk_heatmap_desktop.spec").read_text(encoding="utf-8")
        for required in (
            '"desktop" / "app.py"',
            "RiskAssessmentHeatMap",
            "web",
            "scoring_anchors.json",
            "audit_risk_register.xlsx",
            "THIRD_PARTY_NOTICES.md",
            "build/licenses",
            "rapidocr",
            "pypdfium2",
            "webview.platforms.edgechromium",
            "keyring.backends.Windows",
            "PyQt5",
            "PyQt6",
            "PySide2",
            "PySide6",
            "cefpython",
            "COLLECT",
        ):
            self.assertIn(required, spec)
        self.assertIn("exclude_binaries=True", spec)

    def test_inno_script_is_per_user_and_installs_complete_onedir(self):
        script = (ROOT / "packaging" / "RiskAssessmentHeatMap.iss").read_text(encoding="utf-8")
        for required in (
            "PrivilegesRequired=lowest",
            "{localappdata}\\Programs\\RiskAssessmentHeatMap",
            "[Files]",
            "recursesubdirs",
            "WebView2",
            "[Icons]",
            "unins000.exe",
            "RiskAssessmentHeatMap-Setup.exe",
        ):
            self.assertIn(required, script)

    def test_inno_uses_the_installed_webview2_runtime_guid_and_never_blocks_silent_setup(self):
        script = (ROOT / "packaging" / "RiskAssessmentHeatMap.iss").read_text(encoding="utf-8")
        guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        self.assertIn("SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" + guid, script)
        self.assertIn("SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + guid, script)
        self.assertIn("RegQueryStringValue(HKLM64", script)
        self.assertNotIn("{F1E7E0A6-DF20-4A1F-B9F0-6A5D07D19F31}", script)
        self.assertIn("not WizardSilent", script)
        self.assertIn("Log(", script)

    def test_verifier_bounds_installer_and_uninstaller_and_captures_logs(self):
        script = (ROOT / "tools" / "verify_desktop_package.ps1").read_text(encoding="utf-8")
        self.assertNotIn("& $InstallerPath", script)
        self.assertNotIn("& $uninstaller", script)
        self.assertIn("AddSeconds(300)", script)
        self.assertIn("INSTALL_TIMEOUT", script)
        self.assertIn("UNINSTALL_TIMEOUT", script)
        self.assertIn("installer-log", script)
        self.assertIn("Stop-Process -Id $process.Id", script)
        self.assertIn("CompletionProbe", script)
        self.assertIn("Get-CimInstance Win32_Process", script)
        self.assertIn("$PID", script)
        self.assertIn("Installation process succeeded.", script)
        self.assertIn("Uninstallation process succeeded.", script)
        self.assertIn("Log closed.", script)
        self.assertIn("$verified", script)

    def test_build_script_has_narrow_destructive_path_guard_and_iscc_blocker(self):
        script = (ROOT / "tools" / "build_desktop.ps1").read_text(encoding="utf-8")
        self.assertIn("Assert-AllowedBuildPath", script)
        for allowed in (
            "build\\risk_heatmap_desktop",
            "dist\\RiskAssessmentHeatMap",
            "installer-output",
            "build\\licenses",
            "INNO_SETUP_NOT_FOUND",
        ):
            self.assertIn(allowed, script)
        self.assertNotIn("git clean", script.lower())
        self.assertNotIn("rm -rf", script.lower())

    def test_license_exporter_writes_hashed_manifest_for_available_distribution(self):
        output = Path(tempfile.mkdtemp(prefix="rahm-license-test-")) / "licenses"
        command = [
            sys.executable,
            str(ROOT / "tools" / "export_third_party_licenses.py"),
            "--output",
            str(output),
            "--packages",
            "pip",
            "--allow-noncritical",
        ]
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertIn("LICENSE_EXPORT_OK", completed.stdout)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("pip", manifest["packages"][0]["name"].lower())
        copied = output / manifest["packages"][0]["files"][0]["path"]
        self.assertEqual(
            manifest["packages"][0]["files"][0]["sha256"],
            hashlib.sha256(copied.read_bytes()).hexdigest(),
        )

    def test_critical_export_requires_verified_vendored_rapidocr_model_notice(self):
        output = Path(tempfile.mkdtemp(prefix="rahm-critical-license-test-")) / "licenses"
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "export_third_party_licenses.py"), "--output", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        rapidocr = next(record for record in manifest["packages"] if record["name"].lower() == "rapidocr")
        self.assertEqual("v3.9.2", rapidocr["vendored_provenance"]["tag"])
        self.assertEqual("095232a4c94f7f0e6600ba5bba1177010ad696d4", rapidocr["vendored_provenance"]["commit"])
        self.assertEqual(
            {"PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx"},
            set(rapidocr["vendored_provenance"]["models"]),
        )

    def test_synthetic_smoke_runs_before_gui_and_prints_only_marker(self):
        completed = subprocess.run(
            [sys.executable, "-m", "desktop.app", "--synthetic-smoke"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("PACKAGED_DESKTOP_SMOKE_OK\n", completed.stdout)
