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

Use `--keep-output D:\safe-existing-or-new-child` only for an explicit local directory. The supplied directory is never deleted; the default run uses and removes a temporary directory.

The check creates a deterministic three-page `vertical_slice_report.pdf`: three fictional locators, including one raster-only page processed by real RapidOCR. Every page visibly says `SYNTHETIC TEST DATA`. It runs `DesktopStore`, `TaskTempFiles`, PDF extraction, `RapidOcrEngine`, `ModelClient`, a loopback-only fake OpenAI server, `AnalysisPipeline`, review operations, preview-token-bound workbook writing, export, and scoring through `tools.common`.

Current evidence fields asserted by the check are: three pending source-grounded findings; two accepted IDs merged into the blank-ID `R025` create decision; one excluded ID; period `2026H2`; source SHA unchanged; task temporary directory removed; workbook and export remain under temporary output; score matches `tools.common.assess_all`; SQLite/log bytes exclude the synthetic key, full-body sentinel, and absolute source path; and the fake server sees only loopback body records without authorization material.
