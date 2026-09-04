"""Release-license closure contracts for the Windows/Python 3.13 build."""

from __future__ import annotations

import importlib.util
import json
from importlib import metadata
from pathlib import Path
import sys
import tempfile
import unittest

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "packaging" / "distribution_packages.lock.json"
EXPORTER_PATH = ROOT / "tools" / "export_third_party_licenses.py"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("license_exporter", EXPORTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _installed_closure(roots: list[str]) -> dict[str, str]:
    environment = default_environment()
    installed = {canonicalize_name(item.metadata["Name"]): item for item in metadata.distributions()}
    closure: dict[str, str] = {}
    pending = list(roots)
    while pending:
        requested = pending.pop()
        name = canonicalize_name(requested)
        if name in closure:
            continue
        distribution = installed[name]
        closure[name] = distribution.version
        for raw_requirement in distribution.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            pending.append(requirement.name)
    return closure


class PackagingLicenseClosureTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    def test_lock_freezes_complete_windows_python313_distribution_closure(self):
        self.assertEqual(2, self.lock["schema"])
        self.assertEqual("win32", self.lock["target"]["sys_platform"])
        self.assertEqual("3.13", self.lock["target"]["python_version"])
        roots = self.lock["roots"]
        self.assertEqual(
            {"pyinstaller", "reportlab"},
            {canonicalize_name(item["name"]) for item in roots if item["scope"] == "build"},
        )
        locked = {canonicalize_name(item["name"]): item["version"] for item in self.lock["packages"]}
        resolved = _installed_closure([item["name"] for item in roots])
        self.assertEqual(resolved, locked)

    def test_known_transitive_and_native_distributions_are_locked(self):
        locked = {canonicalize_name(item["name"]) for item in self.lock["packages"]}
        expected = {
            "numpy",
            "lxml",
            "certifi",
            "opencv-python",
            "shapely",
            "pythonnet",
            "httpcore",
            "anyio",
            "clr-loader",
            "cffi",
            "pyinstaller-hooks-contrib",
            "setuptools",
        }
        self.assertTrue(expected.issubset(locked), sorted(expected - locked))

    def test_native_component_lock_names_every_packaged_runtime_artifact(self):
        components = {item["name"]: item for item in self.lock["components"]}
        cpython = components["CPython"]
        self.assertEqual(30, len(cpython["artifact_locators"]))
        self.assertEqual(set(cpython["artifact_locators"]), set(cpython["artifact_hashes"]))
        for required in (
            "DLLs/libcrypto-3.dll", "DLLs/libssl-3.dll", "DLLs/libffi-8.dll",
            "DLLs/sqlite3.dll", "DLLs/tcl86t.dll", "DLLs/tk86t.dll",
            "DLLs/zlib1.dll", "DLLs/_ssl.pyd", "DLLs/_sqlite3.pyd",
            "vcruntime140.dll", "vcruntime140_1.dll",
        ):
            self.assertIn(required, cpython["artifact_locators"])
            self.assertRegex(cpython["artifact_hashes"][required], r"^[0-9a-f]{64}$")
        notices = cpython["vendored_provenance"]["additional_license_files"]
        notice_names = {Path(item["license_path"]).name for item in notices}
        self.assertTrue(
            {
                "CPYTHON-WINDOWS-LICENSE.txt", "CPYTHON-DOC-LICENSE.rst",
                "OPENSSL-3.0.21-LICENSE.txt",
                "SQLITE-PUBLIC-DOMAIN.txt", "TCL-8.6.15-LICENSE.txt",
                "TK-8.6.15-LICENSE.txt", "ZLIB-1.3.1-LICENSE.txt",
                "LIBFFI-3.4.4-LICENSE.txt", "BZIP2-1.0.8-LICENSE.txt",
                "XZ-5.2.5-COPYING.txt", "LIBMPDEC-4.0.0-LICENSE.txt",
                "EXPAT-COPYING.txt",
            }.issubset(notice_names)
        )
        libmpdec = next(item for item in notices if item["license_path"].endswith("LIBMPDEC-4.0.0-LICENSE.txt"))
        self.assertEqual("4.0.0", libmpdec["bundled_version"])
        self.assertIn("DLLs/_decimal.pyd", cpython["artifact_locators"])
        complete_doc = ROOT / "licenses" / "CPython-3.13.14" / "third-party" / "CPYTHON-DOC-LICENSE.rst"
        complete_text = complete_doc.read_text(encoding="utf-8")
        for heading in ("mimalloc", "Mersenne Twister", "libmpdec"):
            self.assertIn(heading, complete_text)
        webview = components["Microsoft WebView2 SDK"]["artifact_locators"]
        self.assertEqual(5, len(webview))
        self.assertIn("webview/lib/runtimes/win-x64/native/WebView2Loader.dll", webview)
        self.assertEqual(
            ["RiskAssessmentHeatMap.exe"],
            components["PyInstaller bootloader"]["collect_native_names"],
        )
        redist = components["Microsoft Visual C++ Redistributable"]
        self.assertEqual("prerequisite", redist["kind"])
        self.assertEqual("VC_redist.x64-14.50.35719.exe", redist["artifact_locator"])
        self.assertEqual(
            "8995548dfffcde7c49987029c764355612ba6850ee09a7b6f0fddc85bdc5c280",
            redist["artifact_sha256"],
        )
        self.assertEqual("14.50.35719.0", redist["file_version"])
        self.assertNotIn("ambient_native_names", redist)
        self.assertNotIn("license_distribution", redist)

    def test_every_wheel_without_notice_has_frozen_vendored_provenance(self):
        missing_wheel_notices = {
            "antlr4-python3-runtime",
            "et-xmlfile",
            "flatbuffers",
            "openpyxl",
            "proxy-tools",
            "rapidocr",
            "tqdm",
        }
        packages = {canonicalize_name(item["name"]): item for item in self.lock["packages"]}
        for name in missing_wheel_notices:
            provenance = packages[name].get("vendored_provenance")
            self.assertIsInstance(provenance, dict, name)
            self.assertIn(
                provenance["provenance_type"],
                {"pypi_sdist", "upstream_tag", "pypi_sdist_plus_upstream_commit"},
            )
            self.assertRegex(provenance["source_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(provenance["license_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(provenance["source_url"].startswith("https://"))
            self.assertTrue(provenance["source_filename"])
            self.assertTrue(provenance["license_path"])

    def test_exported_manifest_covers_lock_and_runtime_components_without_absolute_paths(self):
        exporter = _load_exporter()
        output = Path(tempfile.mkdtemp(prefix="rahm-license-closure-")) / "licenses"
        manifest = exporter.export_licenses(output)
        locked = {canonicalize_name(item["name"]) for item in self.lock["packages"]}
        exported = {canonicalize_name(item["name"]) for item in manifest["packages"]}
        self.assertEqual(locked, exported)
        component_names = {item["name"] for item in manifest["components"]}
        self.assertEqual(
            {
                "CPython",
                "PyInstaller bootloader",
                "Microsoft WebView2 SDK",
                "Microsoft Visual C++ Redistributable",
            },
            component_names,
        )
        cpython = next(item for item in manifest["components"] if item["name"] == "CPython")
        self.assertEqual(30, len(cpython["artifacts"]))
        self.assertEqual(13, len(cpython["files"]))
        self.assertEqual(
            self.lock["components"][0]["artifact_hashes"],
            {item["path"]: item["sha256"] for item in cpython["artifacts"]},
        )
        redist = next(
            item for item in manifest["components"]
            if item["name"] == "Microsoft Visual C++ Redistributable"
        )
        self.assertEqual(
            "8995548dfffcde7c49987029c764355612ba6850ee09a7b6f0fddc85bdc5c280",
            redist["artifact_sha256"],
        )
        for record in [*manifest["packages"], *manifest["components"]]:
            self.assertRegex(record["artifact_sha256"], r"^[0-9a-f]{64}$")
            for copied in record["files"]:
                self.assertNotIn(":\\", copied["source_file"])
                self.assertFalse(copied["source_file"].startswith("/"))

    def test_analysis_audit_blocks_detected_distribution_missing_from_lock(self):
        exporter = _load_exporter()
        numpy_distribution = metadata.distribution("numpy")
        lxml_distribution = metadata.distribution("lxml")
        numpy_source = next(
            Path(numpy_distribution.locate_file(item))
            for item in numpy_distribution.files or ()
            if item.as_posix().endswith("numpy/__init__.py")
        )
        lxml_source = next(
            Path(lxml_distribution.locate_file(item))
            for item in lxml_distribution.files or ()
            if item.as_posix().endswith("lxml/__init__.py")
        )
        temp = Path(tempfile.mkdtemp(prefix="rahm-analysis-audit-"))
        toc = temp / "Analysis-00.toc"
        toc.write_text(repr(([('numpy', str(numpy_source), 'PYMODULE'), ('lxml', str(lxml_source), 'PYMODULE')],)), encoding="utf-8")
        incomplete_lock = {"packages": [{"name": "numpy", "version": metadata.version("numpy")}], "components": []}
        with self.assertRaisesRegex(exporter.LicenseMaterialUnavailable, "lxml"):
            exporter.audit_analysis_toc(toc, incomplete_lock)

    def test_analysis_audit_blocks_ambient_native_runtime_outside_python_and_wheels(self):
        exporter = _load_exporter()
        temp = Path(tempfile.mkdtemp(prefix="rahm-ambient-native-"))
        ambient = temp / "ambient-runtime.dll"
        ambient.write_bytes(b"ambient")
        toc = temp / "Analysis-00.toc"
        toc.write_text(repr(([('ambient-runtime.dll', str(ambient), 'BINARY')],)), encoding="utf-8")
        with self.assertRaisesRegex(exporter.LicenseMaterialUnavailable, "ambient-runtime.dll"):
            exporter.audit_analysis_toc(toc, {"packages": [], "components": []})

    def test_analysis_audit_blocks_unlisted_native_file_inside_python_base(self):
        exporter = _load_exporter()
        python_exe = Path(sys.base_prefix) / "python.exe"
        self.assertTrue(python_exe.is_file())
        temp = Path(tempfile.mkdtemp(prefix="rahm-python-native-"))
        toc = temp / "Analysis-00.toc"
        toc.write_text(repr(([('python.exe', str(python_exe), 'BINARY')],)), encoding="utf-8")
        component_only_lock = {"packages": [], "components": self.lock["components"]}
        with self.assertRaisesRegex(exporter.LicenseMaterialUnavailable, "python.exe"):
            exporter.audit_analysis_toc(toc, component_only_lock)

    def test_cpython_component_rejects_artifact_hash_drift(self):
        exporter = _load_exporter()
        component = dict(next(item for item in self.lock["components"] if item["name"] == "CPython"))
        component["artifact_hashes"] = dict(component["artifact_hashes"])
        component["artifact_hashes"]["python313.dll"] = "0" * 64
        output = Path(tempfile.mkdtemp(prefix="rahm-cpython-hash-")) / "licenses"
        with self.assertRaisesRegex(exporter.LicenseMaterialUnavailable, "python313.dll.*hash-mismatch"):
            exporter._copy_component(component, output)

    def test_dist_audit_rejects_license_manifest_missing_locked_component(self):
        exporter = _load_exporter()
        temp = Path(tempfile.mkdtemp(prefix="rahm-dist-license-audit-"))
        toc = temp / "Analysis-00.toc"
        toc.write_text(repr(()), encoding="utf-8")
        dist = temp / "dist"
        licenses = dist / "_internal" / "licenses"
        licenses.mkdir(parents=True)
        (dist / "RiskAssessmentHeatMap.exe").write_bytes(b"bootloader")
        (dist / "_internal" / "python313.dll").write_bytes(b"python")
        (licenses / "manifest.json").write_text(
            json.dumps({"packages": [], "components": [{"name": "CPython"}]}),
            encoding="utf-8",
        )
        incomplete = {
            "packages": [],
            "components": [
                {"name": "Microsoft WebView2 SDK"},
            ],
        }
        with self.assertRaisesRegex(exporter.LicenseMaterialUnavailable, "Microsoft WebView2 SDK"):
            exporter.audit_analysis_toc(toc, incomplete, dist)

    def test_dist_audit_rejects_incomplete_cpython_manifest_inventory(self):
        exporter = _load_exporter()
        temp = Path(tempfile.mkdtemp(prefix="rahm-cpython-manifest-audit-"))
        toc = temp / "Analysis-00.toc"
        toc.write_text(repr(()), encoding="utf-8")
        dist = temp / "dist"
        licenses = dist / "_internal" / "licenses"
        licenses.mkdir(parents=True)
        (dist / "RiskAssessmentHeatMap.exe").write_bytes(b"bootloader")
        python_dll = dist / "_internal" / "python313.dll"
        python_dll.write_bytes(b"python")
        python_hash = exporter._sha256(python_dll)
        (licenses / "manifest.json").write_text(
            json.dumps({"packages": [], "components": [{"name": "CPython", "artifacts": [], "files": []}]}),
            encoding="utf-8",
        )
        lock = {
            "packages": [],
            "components": [{
                "name": "CPython",
                "artifact_locators": ["python313.dll"],
                "artifact_hashes": {"python313.dll": python_hash},
                "vendored_provenance": {
                    "license_sha256": "1" * 64,
                    "additional_license_files": [],
                },
            }],
        }
        with self.assertRaisesRegex(exporter.LicenseMaterialUnavailable, "manifest-artifact-inventory"):
            exporter.audit_analysis_toc(toc, lock, dist)

    def test_build_runs_analysis_audit_after_pyinstaller(self):
        script = (ROOT / "tools" / "build_desktop.ps1").read_text(encoding="utf-8")
        pyinstaller = script.index("-m PyInstaller")
        audit = script.index("--audit-analysis")
        self.assertGreater(audit, pyinstaller)
        self.assertIn("risk_heatmap_desktop\\Analysis-00.toc", script)
        self.assertIn("--audit-collect", script)
        self.assertIn("risk_heatmap_desktop\\COLLECT-00.toc", script)
        self.assertIn("$OriginalPath", script)
        self.assertIn("$env:PATH =", script)
        self.assertIn("finally { $env:PATH = $OriginalPath }", script)
        self.assertIn("platform.python_version() == '3.13.14'", script)
        self.assertIn("[switch]$Offline", script)
        self.assertIn("packaging\\cache\\VC_redist.x64-14.50.35719.exe", script)
        self.assertIn("8995548dfffcde7c49987029c764355612ba6850ee09a7b6f0fddc85bdc5c280", script.lower())
        self.assertIn("14.50.35719.0", script)
        self.assertIn("Get-AuthenticodeSignature", script)
        self.assertIn("VC_REDIST_CACHE_MISSING", script)
        self.assertIn("VC_REDIST_HASH_MISMATCH", script)
        self.assertIn("VC_REDIST_SIGNATURE_INVALID", script)
        self.assertIn("packaging/cache/", (ROOT / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
