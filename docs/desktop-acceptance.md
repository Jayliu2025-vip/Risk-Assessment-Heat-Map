# Windows desktop acceptance evidence

## Status and scope

Evidence date: 2026-09-03.

The Windows desktop report-to-risk implementation and its installer passed the current-host automated and installed-package gates below. All test reports, findings, model responses and workbooks were synthetic. No real audit report, real API credential or paid model endpoint was used.

Release qualification remains **incomplete** until the same installer is exercised on a separate clean Windows machine that has no Python installation and under a physically disconnected or administrator-enforced firewall condition. The current host proves process-level offline behavior and a self-contained packaged runtime, but it is not a substitute for those two external observations.

This feature is a report-analysis workflow. It does not implement a knowledge base, RAG, vector search or historical-report chat.

## Verified environment

- OS: Microsoft Windows 11 家庭版 中文版, version `10.0.26200`, build `26200`, x64.
- Build interpreter: CPython `3.13.14` x64 in the pinned desktop virtual environment.
- Microsoft Edge WebView2 Runtime: `152.0.4191.53`.
- PyInstaller: `6.22.2`; Inno Setup compiler: `6.7.3`.
- OCR backend: RapidOCR `3.9.2` with ONNX Runtime `1.29.0`; the build gate ran `rapidocr.exe check` successfully.
- License export: 12 locked direct distributions, with per-distribution artifact hashes and copied license/NOTICE material. RapidOCR model provenance and the openpyxl 3.1.5 PyPI sdist provenance are verified separately.

## Fresh verification matrix

Commands were run from the isolated `codex/audit-report-desktop` worktree.

| Gate | Exact command | Result |
| --- | --- | --- |
| Whitespace | `git diff --check` | Exit 0; no whitespace errors. Git only reported the expected future LF-to-CRLF checkout notices for edited Markdown/PowerShell files. |
| Python suite | `& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' -m unittest discover -s tests -v` | Final run: `Ran 208 tests in 70.110s` and `OK`. |
| Desktop UI | `npx playwright test tests/e2e/desktop_report.spec.js` | Final run: `2 passed (7.5s)`. |
| Process-level offline vertical slice | `& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' tools\run_synthetic_desktop_acceptance.py --offline-verify` | `OFFLINE_GUARD_OK loopback_only=true`; `DESKTOP_ACCEPTANCE_OK findings=3 accepted=2 excluded=1 period=2026H2 source_unchanged=true temp_clean=true`. |
| Full build | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\build_desktop.ps1 -PythonExe 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe'` | The full pipeline passed Python 207/207, Playwright 2/2, `pip check`, real RapidOCR check, 12-package license export, PyInstaller and Inno. After the prompt evidence contract added test 208, the final artifacts were rebuilt with the same script plus `-SkipTests`, followed by the independent final 208/208 and 2/2 runs above. |
| Installed-package gate | `pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_desktop_package.ps1` | Onedir synthetic smoke, silent per-user install, installed synthetic smoke and silent uninstall all passed; stderr was empty and `PACKAGE_PROCESSES=0` after verification. Earlier candidate builds were also run repeatedly to remove stdout-drain and installer handoff races before this final gate. |

The final build removed an invalid class name from the PyInstaller hidden-import list; `keyring.backends.Windows` is the real module and exposes `WinVaultKeyring`. The remaining RapidOCR TensorRT warning is for an unused optional backend; the selected ONNX Runtime backend passed its real check and OCR tests.

## Final artifact identity

- Onedir executable: `D:\project\Risk Assessment Heat Map\.worktrees\audit-report-desktop\dist\RiskAssessmentHeatMap\RiskAssessmentHeatMap.exe`
- Onedir executable SHA-256: `048DD246BBAA9815193A4BA256000D63730FB68B4774428AE288A9A94DE3D2F2`
- Installer: `D:\project\Risk Assessment Heat Map\.worktrees\audit-report-desktop\installer-output\RiskAssessmentHeatMap-Setup.exe`
- Installer SHA-256: `8BACEF44CCA00EB9119B7135A62D940CAC533153336E0FCE524DFB84A6BCB6B4`

`build/`, `dist/` and `installer-output/` are ignored build products and are not committed to Git.

## Requirement-by-requirement review

| Design §11 item | Evidence | Status |
| --- | --- | --- |
| 1. Install and start without user-installed Python | Inno performs a per-user install; both onedir and installed `--synthetic-smoke` used the bundled Python runtime. | Current-host pass; separate no-Python clean-machine observation pending. |
| 2. Text PDF, scanned PDF and DOCX share one workflow | `test_report_extraction` covers text/scanned PDF, DOCX, table and inline-image ordering; the vertical fixture includes a real raster page. | Pass. |
| 3. Local extraction → OCR → optional vision fallback | Extraction tests cover each route; the vertical acceptance requires its raster page to be handled by real OCR rather than a vacuous vision fallback. | Pass. |
| 4. OpenAI-compatible cloud/local model configuration | Model-client and bridge tests cover URL normalization, TLS/loopback rules, connection tests, vision opt-in, timeout/rate/error mapping and Windows Credential Locker. | Pass. |
| 5. Minimal pending findings before formal data | Domain/storage/web contracts limit fields and prevent model self-approval; source locators, involved units, amounts and independent dimension evidence remain available for review without storing report bodies. | Pass. |
| 6. Modify, merge, split, accept and exclude | Bridge tests and Playwright cover the review operations, validation and race guards. | Pass. |
| 7. Existing deterministic scoring is authoritative | Writer/vertical tests recompute through `tools.common`; model-provided final risk values are rejected/ignored. | Pass. |
| 8. Versioned Excel and original preservation | Preview-token, atomic write, collision and source-hash tests pass; vertical acceptance reports `source_unchanged=true`. | Pass. |
| 9. No knowledge base/RAG/vector/report chat | Product boundary is explicit in README/manual/design; no such route, schema or UI is added. | Pass. |
| 10. Tests, data minimization and cleanup | 208 Python tests, 2 Playwright tests, privacy scans, `temp_clean=true`, bounded package verifier and zero package processes after uninstall. | Current-host pass; physical-disconnect observation pending. |

## Synthetic vertical-slice details

The acceptance creates a deterministic three-page `vertical_slice_report.pdf` with three fictional locators. One page is raster-only and must be processed by real RapidOCR; every page visibly says `SYNTHETIC TEST DATA`. It runs `DesktopStore`, `TaskTempFiles`, PDF extraction, OCR, an OpenAI-compatible client against a loopback fake server, `AnalysisPipeline`, review operations, preview-token-bound workbook writing, CSV export and scoring through `tools.common`.

The gate requires three source-grounded pending findings; a modification, merge and exclusion; two accepted IDs; a blank-ID create decision allocated as `R025`; period `2026H2`; unchanged source hash; removed task temporary files; workbook/export containment; and absence of the synthetic key, full-body sentinel and absolute source/workbook paths from SQLite, logs, workbook and exports.

## Known limitations and external release checks

1. Windows Firewall rule creation was attempted narrowly for an earlier acceptance run, but `New-NetFirewallRule` returned `拒绝访问` without administrator rights. Cleanup was verified as `FIREWALL_RULE_REMOVED=True`; no global firewall or network-adapter setting was changed. The process-level socket guard blocks DNS and non-loopback connect paths and passed, but a physically disconnected/admin-enforced run remains outstanding.
2. Windows 11 Home on this host does not provide a separate clean-machine observation. Before calling the desktop first version release-complete, install the exact SHA-256 artifact above on a clean Windows 10/11 x64 account or machine without Python, run the installed workflow with only the synthetic fixture/fake model, then uninstall and record zero residual application processes/files.
3. Two historical failed-verifier temporary directories may remain under `%TEMP%` (`rahm-installed-smoke-e433b28b645b4f848461ec0a59424ef7` and `rahm-installed-smoke-1ca3b42892914e309c64e764df6abdf7`). Their application processes were terminated and the final verifier does not use them. Automated recursive removal was rejected by the host command policy, so they were not deleted by bypassing that safety control.
