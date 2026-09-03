"""Synthetic contract tests for the pywebview desktop bridge."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import inspect
from pathlib import Path
import tempfile
import unittest

from desktop.models import AnalysisTask, FindingDraft, ModelProfile
from desktop.storage import DesktopStore
from tools.common import DIMS


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finding(task_id: str, finding_id: str = "F-1", **changes):
    value = FindingDraft(
        task_id=task_id, finding_id=finding_id, title="合成发现", fact_summary="合成事实",
        source_page="第 1 页", source_excerpt="合成摘录", matched_risk_id="R001",
        domain="采购与外包", likelihood=3, impact_scores={dim: 2 for dim in DIMS},
        rationale="合成依据", needs_review=True,
    )
    for key, item in changes.items():
        setattr(value, key, item)
    return value


class Window:
    def __init__(self, selected: list[str] | None = None):
        self.selected = selected or []
        self.calls = []

    def create_file_dialog(self, **kwargs):
        self.calls.append(kwargs)
        return self.selected


class CredentialMemory:
    def __init__(self): self.values = {}
    def set_password(self, service, name, secret): self.values[(service, name)] = secret
    def get_password(self, service, name): return self.values.get((service, name))
    def set_api_key(self, name, secret): self.values[name] = secret
    def get_api_key(self, name): return self.values.get(name)


class Pipeline:
    def __init__(self, store): self.store, self.calls, self.cleaned = store, [], []
    def start(self, source_path, model_profile, risk_catalog):
        self.calls.append((Path(source_path), model_profile, list(risk_catalog)))
        task = AnalysisTask("T-1", Path(source_path).name, digest(Path(source_path)), "2026-09-03T00:00:00Z", "待复核", model_profile, "text")
        self.store.save_task(task)
        return task
    def events(self, task_id): return [{"status": "待复核", "code": "DONE", "message": "完成", "timestamp": "x"}]
    def review_findings(self, task_id, edits):
        checked = [item if isinstance(item, FindingDraft) else FindingDraft(**item) for item in edits]
        return self.store.save_findings(checked)
    def cleanup_task(self, task_id): self.cleaned.append(task_id)


class Writer:
    def __init__(self): self.preview_calls, self.commit_calls = [], []
    def preview_changes(self, source, decisions, findings):
        self.preview_calls.append((Path(source), decisions, findings))
        return {"commit_token": "token-1", "new_risks": [], "periods": ["2026H1"]}
    def write_versioned_workbook(self, source, decisions, findings, *, expected_commit_token):
        self.commit_calls.append((Path(source), decisions, findings, expected_commit_token))
        return type("Result", (), {"workbook_path": Path("C:/synthetic/out.xlsx"), "export_dir": Path("C:/synthetic/export"), "periods": ["2026H1"], "assessed_risks": [{"risk_id": "R001"}]})()


class Client:
    def __init__(self, profile, key): self.profile, self.key = profile, key
    def test_connection(self): return True
    def close(self): pass


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = DesktopStore(self.root / "state.db")
        self.pipeline = Pipeline(self.store)
        self.writer = Writer()
        self.window = Window()
        self.report = self.root / "synthetic.pdf"
        self.report.write_bytes(b"synthetic-pdf")
        self.workbook = self.root / "synthetic.xlsx"
        self.workbook.write_bytes(b"synthetic-workbook")
        from desktop.bridge import DesktopBridge
        self.bridge = DesktopBridge(
            store=self.store, pipeline=self.pipeline, credential_store=CredentialMemory(),
            model_client_factory=Client, workbook_writer=self.writer,
            risk_catalog=[{"risk_id": "R001", "name": "合成风险"}],
            pdf_preview_renderer=lambda path, page: b"png-bytes",
        )
        self.bridge.attach_window(self.window)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def profile(self):
        return {"name": "synthetic", "base_url": "https://model.example.test", "model": "test", "supports_vision": False, "api_key": "sk-synthetic-secret"}

    def select(self, path, purpose="report"):
        self.window.selected = [str(path)]
        return self.bridge.choose_report(purpose)

    def seed_task(self, task_id="T-1", source=None):
        source = source or self.report
        self.store.save_task(AnalysisTask(task_id, source.name, digest(source), "2026-09-03T00:00:00Z", "待复核", "synthetic", "text"))
        self.store.save_findings([finding(task_id)])

    def test_exact_js_public_allowlist(self):
        actual = {name for name, value in inspect.getmembers(type(self.bridge), inspect.isfunction) if not name.startswith("_")}
        self.assertEqual(actual, {"get_bootstrap", "choose_report", "get_source_preview", "save_model_profile", "test_model_profile", "start_analysis", "get_task", "get_findings", "save_finding", "merge_findings", "split_finding", "preview_commit", "commit_to_workbook", "cleanup_task"})

    def test_choose_report_returns_token_only_and_rejects_wrong_purpose(self):
        chosen = self.select(self.report)
        self.assertEqual(chosen["ok"], True)
        self.assertEqual(chosen["basename"], "synthetic.pdf")
        self.assertNotIn(str(self.report), str(chosen))
        wrong = self.bridge.start_analysis(chosen["selection_token"], "synthetic")
        self.assertFalse(wrong["ok"])
        self.assertEqual(wrong["code"], "MODEL_PROFILE_NOT_FOUND")
        workbook = self.select(self.workbook, "workbook")
        self.assertEqual(self.bridge.start_analysis(workbook["selection_token"], "synthetic")["code"], "SELECTION_PURPOSE_INVALID")
        self.assertEqual(self.bridge.start_analysis("stale", "synthetic")["code"], "SELECTION_NOT_FOUND")

    def test_profile_never_echoes_secret_and_connection_returns_hostname(self):
        saved = self.bridge.save_model_profile(self.profile())
        self.assertTrue(saved["ok"])
        self.assertNotIn("api_key", saved)
        self.assertNotIn("sk-synthetic-secret", str(saved))
        tested = self.bridge.test_model_profile("synthetic")
        self.assertEqual(tested, {"ok": True, "hostname": "model.example.test"})
        self.assertNotIn("sk-synthetic-secret", str(self.bridge.get_bootstrap()))

    def test_start_task_findings_are_serializable_and_never_source_path(self):
        self.bridge.save_model_profile(self.profile())
        selected = self.select(self.report)
        started = self.bridge.start_analysis(selected["selection_token"], "synthetic")
        self.assertTrue(started["ok"])
        self.assertNotIn(str(self.report), str(started))
        self.store.save_findings([finding("T-1")])
        self.assertEqual(self.bridge.get_task("T-1")["task"]["task_id"], "T-1")
        self.assertEqual(self.bridge.get_findings("T-1")["findings"][0]["finding_id"], "F-1")

    def test_error_sanitizer_hides_secret_path_and_report_body(self):
        self.bridge._pipeline = type("Bad", (), {"start": lambda *_: (_ for _ in ()).throw(RuntimeError("sk-secret C:\\secret\\report.pdf 完整报告正文"))})()
        result = self.bridge.start_analysis("missing", "synthetic")
        self.assertFalse(result["ok"])
        for forbidden in ("sk-secret", "C:\\secret", "完整报告正文"):
            self.assertNotIn(forbidden, str(result))

    def test_source_preview_hash_pdf_docx_and_reselect_contract(self):
        self.seed_task()
        selected = self.select(self.report)
        self.bridge._task_sources["T-1"] = (self.report, selected["selection_token"])
        pdf = self.bridge.get_source_preview("T-1", "F-1")
        self.assertEqual(pdf["kind"], "pdf")
        self.assertTrue(pdf["image_data_url"].startswith("data:image/png;base64,"))
        self.report.write_bytes(b"changed")
        self.assertEqual(self.bridge.get_source_preview("T-1", "F-1")["code"], "SOURCE_HASH_CHANGED")
        self.assertEqual(self.bridge.get_source_preview("other", "F-1")["code"], "SOURCE_RESELECT_REQUIRED")
        docx = self.root / "synthetic.docx"; docx.write_bytes(b"x")
        self.seed_task("T-docx", docx)
        self.store.save_findings([finding("T-docx", "F-docx", source_page="第 2 段", source_excerpt="有限摘录")])
        token = self.select(docx)["selection_token"]
        self.bridge._task_sources["T-docx"] = (docx, token)
        preview = self.bridge.get_source_preview("T-docx", "F-docx")
        self.assertEqual(preview, {"ok": True, "kind": "text", "source_page": "第 2 段", "source_excerpt": "有限摘录"})

    def test_source_preview_reattaches_a_matching_report_after_bridge_restart(self):
        self.seed_task()
        restarted = type(self.bridge)(
            store=self.store, pipeline=Pipeline(self.store), credential_store=CredentialMemory(),
            model_client_factory=Client, workbook_writer=self.writer,
            risk_catalog=[{"risk_id": "R001", "name": "合成风险"}],
            pdf_preview_renderer=lambda path, page: b"png-bytes",
        )
        restarted.attach_window(self.window)
        self.window.selected = [str(self.report)]
        token = restarted.choose_report("report")["selection_token"]
        preview = restarted.get_source_preview("T-1", "F-1", token)
        self.assertEqual(preview["kind"], "pdf")
        self.assertEqual(restarted._task_sources["T-1"][1], token)
        wrong = self.root / "other.pdf"; wrong.write_bytes(b"different synthetic report")
        mismatched = type(self.bridge)(
            store=self.store, pipeline=Pipeline(self.store), credential_store=CredentialMemory(),
            model_client_factory=Client, workbook_writer=self.writer,
            risk_catalog=[{"risk_id": "R001", "name": "合成风险"}],
            pdf_preview_renderer=lambda path, page: b"png-bytes",
        )
        mismatched.attach_window(self.window)
        self.window.selected = [str(wrong)]
        wrong_token = mismatched.choose_report("report")["selection_token"]
        mismatch = mismatched.get_source_preview("T-1", "F-1", wrong_token)
        self.assertEqual(mismatch["code"], "SOURCE_HASH_CHANGED")
        self.assertNotIn(str(wrong), str(mismatch))

    def test_human_save_merge_and_split_validate_before_atomic_write(self):
        self.seed_task()
        self.store.save_findings([finding("T-1", "F-2")])
        payload = asdict(finding("evil", "wrong", review_status="已接受"))
        saved = self.bridge.save_finding("T-1", "F-1", payload)
        self.assertEqual(saved["finding"]["task_id"], "T-1")
        self.assertEqual(saved["finding"]["finding_id"], "F-1")
        merged = self.bridge.merge_findings("T-1", ["F-1", "F-2"], asdict(finding("x", "x")))
        self.assertTrue(merged["ok"])
        self.assertEqual([item.review_status for item in self.store.list_findings("T-1")], ["待确认", "已排除"])
        before = [asdict(item) for item in self.store.list_findings("T-1")]
        invalid = self.bridge.split_finding("T-1", "F-1", [asdict(finding("x", "new")), {"finding_id": "bad"}])
        self.assertFalse(invalid["ok"])
        self.assertEqual([asdict(item) for item in self.store.list_findings("T-1")], before)
        split = self.bridge.split_finding("T-1", "F-1", [asdict(finding("x", "new-a")), asdict(finding("x", "new-b"))])
        self.assertTrue(split["ok"])
        by_id = {item.finding_id: item.review_status for item in self.store.list_findings("T-1")}
        self.assertEqual(by_id["F-1"], "已排除")
        self.assertEqual(by_id["new-a"], "待确认")

    def test_preview_and_commit_bind_selection_token_and_return_output_paths(self):
        self.seed_task()
        selected = self.select(self.workbook, "workbook")
        decision = {"action": "exclude", "finding_ids": ["F-1"]}
        preview = self.bridge.preview_commit("T-1", selected["selection_token"], [decision])
        self.assertEqual(preview["commit_token"], "token-1")
        bad = self.bridge.commit_to_workbook("T-1", selected["selection_token"], [decision], "wrong")
        self.assertEqual(bad["code"], "PREVIEW_STALE")
        done = self.bridge.commit_to_workbook("T-1", selected["selection_token"], [decision], "token-1")
        self.assertEqual(done["workbook_path"], str(Path("C:/synthetic/out.xlsx")))
        self.assertEqual(done["export_dir"], str(Path("C:/synthetic/export")))

    def test_cleanup_only_forgets_runtime_mappings(self):
        self.seed_task()
        selected = self.select(self.report)
        self.bridge._task_sources["T-1"] = (self.report, selected["selection_token"])
        result = self.bridge.cleanup_task("T-1")
        self.assertTrue(result["ok"])
        self.assertEqual(self.store.get_task("T-1").task_id, "T-1")
        self.assertTrue(self.report.exists())
        self.assertNotIn("T-1", self.bridge._task_sources)

    def test_cleanup_task_is_scoped_to_its_report_and_workbook_preview(self):
        second_report = self.root / "second.pdf"; second_report.write_bytes(b"second synthetic report")
        self.seed_task("T-1", self.report)
        self.seed_task("T-2", second_report)
        report_one = self.select(self.report)["selection_token"]
        report_two = self.select(second_report)["selection_token"]
        self.bridge._task_sources.update({"T-1": (self.report, report_one), "T-2": (second_report, report_two)})
        first_book = self.select(self.workbook, "workbook")["selection_token"]
        second_book_file = self.root / "second.xlsx"; second_book_file.write_bytes(b"second synthetic workbook")
        second_book = self.select(second_book_file, "workbook")["selection_token"]
        decision = [{"action": "exclude", "finding_ids": ["F-1"]}]
        self.bridge.preview_commit("T-1", first_book, decision)
        self.bridge.preview_commit("T-2", second_book, decision)
        cleaned = self.bridge.cleanup_task("T-1")
        self.assertTrue(cleaned["ok"])
        self.assertEqual(self.pipeline.cleaned, ["T-1"])
        self.assertNotIn("T-1", self.bridge._task_sources)
        self.assertNotIn(report_one, self.bridge._selections)
        self.assertNotIn(first_book, self.bridge._selections)
        self.assertNotIn(first_book, self.bridge._commit_previews)
        self.assertEqual(self.bridge._task_sources["T-2"], (second_report, report_two))
        self.assertIn(report_two, self.bridge._selections)
        self.assertIn(second_book, self.bridge._selections)
        self.assertIn(second_book, self.bridge._commit_previews)


class AppBootstrapTests(unittest.TestCase):
    def test_main_creates_private_edge_window_and_closes_pipeline(self):
        from desktop import app

        class PipelineClose:
            def __init__(self): self.closed = False
            def close(self): self.closed = True

        class Bridge:
            def __init__(self): self.pipeline = PipelineClose(); self.window = None
            def __getattr__(self, name):
                if name == "attach_window": return lambda window: setattr(self, "window", window)
                raise AttributeError(name)

        class Event:
            def __init__(self): self.callbacks = []
            def __iadd__(self, callback): self.callbacks.append(callback); return self

        class Window:
            def __init__(self): self.events = type("Events", (), {"closed": Event()})()

        class Webview:
            def __init__(self): self.calls = []; self.window = Window()
            def create_window(self, **kwargs): self.calls.append(kwargs); return self.window
            def start(self, **kwargs):
                self.calls.append(("start", kwargs))
                for callback in self.window.events.closed.callbacks: callback()

        webview, bridge = Webview(), Bridge()
        app.main(webview_module=webview, bridge_factory=lambda: bridge,
                 resource_provider=lambda _: Path("C:/synthetic/risk_heatmap.html"))
        created = webview.calls[0]
        self.assertEqual(created["title"], "审计风险评估热力图谱")
        self.assertEqual(created["url"], Path("C:/synthetic/risk_heatmap.html").as_uri())
        self.assertEqual((created["width"], created["height"], created["min_size"]), (1440, 920, (1120, 720)))
        self.assertIs(created["js_api"], bridge)
        self.assertIs(bridge.window, webview.window)
        self.assertEqual(webview.calls[1], ("start", {"gui": "edgechromium", "private_mode": True, "debug": False}))
        self.assertTrue(bridge.pipeline.closed)


if __name__ == "__main__":
    unittest.main()
