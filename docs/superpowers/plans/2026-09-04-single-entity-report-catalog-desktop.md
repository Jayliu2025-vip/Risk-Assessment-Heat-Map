# Single-Entity Report Catalog Desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop sample-first single-report overlay with the approved single-entity persistent report catalog, reusable multi-report assessment batches, and prototype-aligned workspace UI.

**Architecture:** Add a file-backed `CatalogStore` under a user-selected root while keeping transient analysis state in `DesktopStore`. Extend `DesktopBridge` with workspace, catalog finalization, trash, and catalog-batch APIs; reuse the existing pipeline, decision validation, workbook preview token, deterministic scoring, and versioned writer. Rewrite the desktop-only HTML/CSS/JS surface as four isolated views while keeping the browser heatmap behavior available without automatic sample loading.

**Tech Stack:** Python 3.13, dataclasses, JSON atomic writes, SQLite settings, pywebview/WebView2, vanilla HTML/CSS/JavaScript, unittest, Playwright.

---

### Task 1: File-backed single-entity catalog

**Files:**
- Create: `desktop/catalog.py`
- Modify: `desktop/models.py`
- Test: `tests/test_desktop_catalog.py`

- [x] Write failing tests for workspace initialization, entity mismatch, safe project/date paths, atomic report records, index rebuild, trash, clear, batch snapshots, and absence of original paths/full bodies.
- [x] Run `python -m unittest tests.test_desktop_catalog -v` and verify failures are caused by the missing catalog implementation.
- [x] Implement validated workspace/report/batch records and `CatalogStore` with exact-root containment and atomic JSON writes.
- [x] Re-run `python -m unittest tests.test_desktop_catalog -v` and verify all catalog tests pass.

### Task 2: Persist only the catalog-root preference in SQLite

**Files:**
- Modify: `desktop/storage.py`
- Modify: `tests/test_desktop_storage.py`

- [x] Write failing tests showing settings round-trip and that report content never enters `state.db`.
- [x] Run the focused storage tests and confirm the expected missing-method failure.
- [x] Add parameterized `get_setting`/`set_setting` methods and a two-column `app_settings` table.
- [x] Re-run storage tests and confirm existing schema/order contracts remain valid.

### Task 3: Bridge catalog and batch APIs

**Files:**
- Modify: `desktop/bridge.py`
- Modify: `desktop/app.py`
- Modify: `desktop/storage.py`
- Modify: `tests/test_desktop_bridge.py`
- Modify: `tests/test_desktop_security.py`

- [x] Write failing bridge tests for folder selection, workspace configuration, bootstrap catalog metadata, catalog finalization after complete review, report trash/clear, catalog batch creation, provenance cloning, workbook binding, invalid risk-ID remapping, and completed batch snapshot recording.
- [x] Run focused bridge/security tests and confirm failures reflect missing public APIs.
- [x] Inject a catalog factory, expose the approved JSON-only APIs, reuse current task/workbook locks, and remove transient task rows only after an atomic catalog save.
- [x] Re-run focused tests and verify catalog operations cannot escape the configured root.

### Task 4: Default-empty browser and desktop behavior

**Files:**
- Modify: `web/risk_heatmap.html`
- Modify: `tests/test_desktop_web_contract.py`
- Modify: `tests/test_release_consistency.py`

- [x] Write failing tests that prohibit automatic `loadSample()` during `boot()` and require a desktop-only hidden sample action.
- [x] Run focused static/release tests and observe the existing auto-load failure.
- [x] Remove automatic sample loading, preserve the explicit browser demo button, and expose a desktop dashboard host for the existing heatmap main element.
- [x] Re-run focused tests and verify an empty state does not synthesize periods or risk rows.

### Task 5: Prototype-aligned desktop workspace

**Files:**
- Modify: `web/risk_heatmap.html`
- Rewrite: `web/desktop_report.css`
- Rewrite: `web/desktop_report.js`
- Modify: `tests/test_desktop_web_contract.py`
- Modify: `tests/e2e/desktop_report.spec.js`

- [x] Rewrite the Playwright contract first for the empty report catalog, single-entity setup, report ingestion/review/finalization, multi-report selection, “相似发现处理”, current-control confirmation, versioned commit, and dashboard unlock.
- [x] Run the desktop Playwright test and confirm it fails on the legacy overlay.
- [x] Implement the four-view workspace, fixed three-column review, catalog filters/selection, explicit no-model state, destructive confirmations, batch grouping, and dashboard handoff while preserving accessible labels and server-side validation.
- [x] Re-run Playwright at 1440×920 and 1120×720 and confirm no horizontal overflow or hidden review actions.

### Task 6: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/使用手册.md`
- Modify: `docs/desktop-acceptance.md`
- Test: `tests/test_desktop_documentation.py`

- [x] Update documentation to describe the single-entity catalog root, no original-file retention, upload-date/project selection, recoverable deletion, exact report versions, batch semantics, and no default sample data.
- [x] Run documentation tests and repair only factual contract mismatches.
- [x] Run `python -m unittest discover -s tests -v`, `npx playwright test tests/e2e --reporter=line`, and `git diff --check`.
- [x] Launch the desktop source with a synthetic state/catalog root, inspect the empty/catalog/review/batch/dashboard views through WebView2, and capture final screenshots without reading real reports.
