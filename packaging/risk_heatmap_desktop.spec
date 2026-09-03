# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir definition for the offline Windows desktop application."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


ROOT = Path(SPECPATH).resolve().parent
LICENSES = ROOT / "build" / "licenses"
if not LICENSES.is_dir():
    raise SystemExit("generated build/licenses directory is required before PyInstaller")

datas = [
    (str(ROOT / "web"), "web"),
    (str(ROOT / "data" / "scoring_anchors.json"), "data"),
    (str(ROOT / "data" / "export"), "data/export"),
    (str(ROOT / "audit_risk_register.xlsx"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(LICENSES), "licenses"),
    (str(ROOT / "tests" / "fixtures" / "generated" / "vertical_slice_report.pdf"), "fixtures"),
]
binaries = []
for package in ("rapidocr", "pypdfium2", "onnxruntime"):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)
datas += collect_data_files("keyring")

hiddenimports = [
    "desktop.smoke",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "keyring.backends.Windows",
    "keyring.backends.Windows.WinVaultKeyring",
] + collect_submodules("rapidocr") + collect_submodules("keyring.backends")

excludes = [
    "PyQt5", "PyQt6", "PySide2", "PySide6", "gtk", "gi", "cefpython3",
    "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cef",
    "tests", "node_modules", "screenshots",
]

a = Analysis(
    [str(ROOT / "desktop" / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="RiskAssessmentHeatMap", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="RiskAssessmentHeatMap")
