# Windows desktop acceptance evidence

## Status and scope

Evidence date: 2026-09-04.

The Windows desktop report-to-risk implementation and its installer passed the current-host automated and installed-package gates below. All test reports, findings, model responses and workbooks were synthetic. No real audit report, real API credential or paid model endpoint was used.

Release qualification remains **incomplete** until the same installer is exercised on a separate clean Windows machine that has no Python installation and under a physically disconnected or administrator-enforced firewall condition. The current host proves process-level offline behavior and a self-contained packaged runtime, but it is not a substitute for those two external observations.

This feature is a report-analysis workflow. It does not implement a knowledge base, RAG, vector search or historical-report chat.

## Verified environment

- OS: Microsoft Windows 11 家庭版 中文版, version `10.0.26200`, build `26200`, x64.
- Build interpreter: CPython `3.13.14` x64 in the pinned desktop virtual environment.
- Microsoft Edge WebView2 Runtime: `152.0.4191.53`.
- PyInstaller: `6.22.2`; Inno Setup compiler: `6.7.3`.
- OCR backend: RapidOCR `3.9.2` with ONNX Runtime `1.29.0`; the build gate ran `rapidocr.exe check` successfully.
- License closure: 58 exact Windows/CPython 3.13 distributions are locked; PyInstaller Analysis identified 52 distributions in the final application and all are covered. Four non-distribution components are also inventoried: CPython, the PyInstaller bootloader, Microsoft WebView2 SDK and Microsoft Visual C++ Runtime. CPython contributes 30 explicitly hashed native files and 13 copied PSF/Windows/third-party notice files, including the complete versioned `Doc/license.rst` and libmpdec 4.0.0 for `_decimal.pyd`; no Python-base directory exemption remains. The manifest contains artifact and license hashes without build-machine paths.

## Fresh verification matrix

Commands were run from the isolated `codex/audit-report-desktop` worktree.

| Gate | Exact command | Result |
| --- | --- | --- |
| Whitespace | `git diff --check` | Exit 0; no whitespace errors. Git only reported the expected future LF-to-CRLF checkout notices for edited Markdown/PowerShell files. |
| Python suite | `& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' -m unittest discover -s tests -v` | Final run: `Ran 236 tests in 87.436s` and `OK`. |
| Desktop UI | `npx playwright test tests/e2e/desktop_report.spec.js` | Final run: `3 passed (9.2s)`. |
| Process-level offline vertical slice | `& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' tools\run_synthetic_desktop_acceptance.py --offline-verify` | `OFFLINE_GUARD_OK loopback_only=true`; `DESKTOP_ACCEPTANCE_OK findings=3 accepted=2 excluded=1 period=2026H2 source_unchanged=true temp_clean=true`. |
| Final offline build | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\build_desktop.ps1 -PythonExe 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' -SkipTests -Offline` | `pip check`, real RapidOCR check, verified cached Microsoft prerequisite, 58-distribution/4-component license export, 30-file CPython native inventory, PyInstaller Analysis and COLLECT audits, onedir and Inno installer passed. The independent final 236/236 and 3/3 suites above ran against the same source. |
| Installed-package gate | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_desktop_package.ps1` | Onedir synthetic smoke, silent per-user install, installed synthetic smoke and silent uninstall all passed; stderr was empty and `PACKAGE_PROCESSES=0` after verification. Earlier candidate builds were also run repeatedly to remove stdout-drain and installer handoff races before this final gate. |

The final build removed an invalid class name from the PyInstaller hidden-import list; `keyring.backends.Windows` is the real module and exposes `WinVaultKeyring`. The remaining RapidOCR TensorRT warning is for an unused optional backend; the selected ONNX Runtime backend passed its real check and OCR tests.

## Final artifact identity

- Onedir executable: `D:\project\Risk Assessment Heat Map\.worktrees\audit-report-desktop\dist\RiskAssessmentHeatMap\RiskAssessmentHeatMap.exe`
- Onedir executable SHA-256: `F5CA9EF2717D2E348516E79E8E771B3907F343D6872B9B24012483C4DC8F13E3`
- Installer: `D:\project\Risk Assessment Heat Map\.worktrees\audit-report-desktop\installer-output\RiskAssessmentHeatMap-Setup.exe`
- Installer SHA-256: `23BFD812E91570E3D3BBD83799432A2779AFB70B68DE458F04BB75D9EC0959C5`
- License manifest SHA-256: `0F6A45B031CBF7B7FAD346BEE123B825425E2451890A6546E14C2923E76CA027`

`build/`, `dist/` and `installer-output/` are ignored build products and are not committed to Git.

## Requirement-by-requirement review

| Design §11 item | Evidence | Status |
| --- | --- | --- |
| 1. Install and start without user-installed Python | Inno performs a per-user install; both onedir and installed `--synthetic-smoke` used the bundled Python runtime. | Current-host pass; separate no-Python clean-machine observation pending. |
| 2. Text PDF, scanned PDF and DOCX share one workflow | `test_report_extraction` covers text/scanned PDF, DOCX, table and inline-image ordering; the vertical fixture includes a real raster page. | Pass. |
| 3. Local extraction → OCR → optional vision fallback | Extraction tests cover each route; the vertical acceptance requires its raster page to be handled by real OCR rather than a vacuous vision fallback. | Pass. |
| 4. OpenAI-compatible cloud/local model configuration | Model-client and bridge tests cover URL normalization, TLS/loopback rules, connection tests, vision opt-in, timeout/rate/error mapping and Windows Credential Locker. | Pass. |
| 5. Minimal pending findings before formal data | Domain/storage/web contracts limit fields and prevent model self-approval; source locators, involved units, amounts and independent dimension evidence remain available for review without storing report bodies. | Pass. |
| 6. Modify, merge, split, accept and exclude | Bridge tests and three Playwright flows cover review operations, merge lineage, merge-then-split/exclude, validation and race guards. | Pass. |
| 7. Existing deterministic scoring is authoritative | Writer/vertical tests recompute through `tools.common`; model-provided final risk values are rejected/ignored. | Pass. |
| 8. Versioned Excel and original preservation | Preview-token, atomic write, collision and source-hash tests pass; vertical acceptance reports `source_unchanged=true`. | Pass. |
| 9. No knowledge base/RAG/vector/report chat | Product boundary is explicit in README/manual/design; no such route, schema or UI is added. | Pass. |
| 10. Tests, data minimization and cleanup | 236 Python tests, 3 Playwright tests, privacy scans, model-catalog projection, `temp_clean=true`, bounded package verifier and zero package processes after uninstall. | Current-host pass; physical-disconnect observation pending. |

## Synthetic vertical-slice details

The acceptance creates a deterministic three-page `vertical_slice_report.pdf` with three fictional locators. One page is raster-only and must be processed by real RapidOCR; every page visibly says `SYNTHETIC TEST DATA`. It runs `DesktopStore`, `TaskTempFiles`, PDF extraction, OCR, an OpenAI-compatible client against a loopback fake server, `AnalysisPipeline`, review operations, preview-token-bound workbook writing, CSV export and scoring through `tools.common`.

The gate requires three source-grounded pending findings; a modification, merge and exclusion; two accepted IDs; a blank-ID create decision allocated as `R025`; period `2026H2`; unchanged source hash; removed task temporary files; workbook/export containment; and absence of the synthetic key, full-body sentinel and absolute source/workbook paths from SQLite, logs, workbook and exports.

## Known limitations and external release checks

1. Windows Firewall rule creation was attempted narrowly for an earlier acceptance run, but `New-NetFirewallRule` returned `拒绝访问` without administrator rights. Cleanup was verified as `FIREWALL_RULE_REMOVED=True`; no global firewall or network-adapter setting was changed. The process-level socket guard blocks DNS and non-loopback connect paths and passed, but a physically disconnected/admin-enforced run remains outstanding.
2. Windows 11 Home on this host does not provide a separate clean-machine observation. Before calling the desktop first version release-complete, install the exact SHA-256 artifact above on a clean Windows 10/11 x64 account or machine without Python, run the installed workflow with only the synthetic fixture/fake model, then uninstall and record zero residual application processes/files. This host already has Microsoft Visual C++ Runtime 14.50.35719, so it verified the prerequisite detection-and-skip path; the missing-runtime `runas`/UAC path passed compilation and contract tests but was not exercised by uninstalling a machine-level runtime.
3. Two historical failed-verifier temporary directories may remain under `%TEMP%` (`rahm-installed-smoke-e433b28b645b4f848461ec0a59424ef7` and `rahm-installed-smoke-1ca3b42892914e309c64e764df6abdf7`). Their application processes were terminated and the final verifier does not use them. Automated recursive removal was rejected by the host command policy, so they were not deleted by bypassing that safety control.
