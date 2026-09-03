# Synthetic desktop acceptance

This acceptance check is only a local, synthetic report-to-risk workflow. It does not use a real report, person, entity, event, API key, RAG store, or external model service. It does not establish an installer claim.

Run with the pinned desktop environment:

```powershell
& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' tools/run_synthetic_desktop_acceptance.py
```

Expected final line:

```text
DESKTOP_ACCEPTANCE_OK findings=3 accepted=2 excluded=1 period=2026H2 source_unchanged=true temp_clean=true
```

On 2026-09-03, the process-level offline verification command was:

```powershell
& 'C:\Users\ahnsl\AppData\Local\Temp\rahm-desktop-venv-01a0628b\Scripts\python.exe' tools/run_synthetic_desktop_acceptance.py --offline-verify
```

Its first evidence line is `OFFLINE_GUARD_OK loopback_only=true`, followed by the exact `DESKTOP_ACCEPTANCE_OK` line above. This installs a temporary Python socket/create-connection guard for the acceptance process only. It guards `socket.create_connection`, `socket.socket.connect`, `socket.socket.connect_ex`, and `socket.getaddrinfo`; only `localhost`, IPv4 `127/8`, and IPv6 `::1` are allowed. Non-loopback destinations are rejected before DNS or network activity.

Also on 2026-09-03, an app-specific Windows Firewall-rule attempt was **BLOCKED**: `New-NetFirewallRule` returned `拒绝访问` because the process lacked administrator rights. Cleanup evidence was `FIREWALL_RULE_REMOVED=True`. No global firewall or network-adapter setting was changed. Physical-firewall and disconnected-machine confirmation remain packaging/final-release environment checks and are not claimed complete here.

Use `--keep-output D:\safe-existing-or-new-child` only for an explicit local directory. The supplied directory is never deleted; the default run uses and removes a temporary directory.

The check creates a deterministic three-page `vertical_slice_report.pdf`: three fictional locators, including one raster-only page processed by real RapidOCR. It captures the real `ExtractionResult` and requires `第 3 页` to be `ocr`, with normalized `SYNTHETIC TEST DATA` and `LOCATOR GAMMA` text; a vision fallback fails acceptance. Every page visibly says `SYNTHETIC TEST DATA`. It runs `DesktopStore`, `TaskTempFiles`, PDF extraction, `RapidOcrEngine`, `ModelClient`, a loopback-only fake OpenAI server, `AnalysisPipeline`, review operations, preview-token-bound workbook writing, export, and scoring through `tools.common`.

Current evidence fields asserted by the check are: three pending source-grounded findings; first-finding modification through `AnalysisPipeline.review_findings`, then status changes through `DesktopStore.set_review_status`; two accepted IDs merged into the blank-ID `R025` create decision; one excluded ID; period `2026H2`; source SHA unchanged; task temporary directory removed; workbook and export remain under temporary output; score matches `tools.common.assess_all`; SQLite, logs, workbook, and exports exclude the synthetic key, full-body sentinel, absolute report path, and absolute workbook path; and the fake server sees only loopback body records without authorization material.
