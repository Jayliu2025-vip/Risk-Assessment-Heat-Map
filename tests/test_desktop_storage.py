import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields
from pathlib import Path

from desktop.models import AnalysisTask, FindingDraft, ModelProfile, ValidationError
from desktop.credentials import CredentialStore
from desktop.storage import DesktopStore
from desktop.tempfiles import TaskTempFiles
from tools.common import DIMS


class DesktopStoreTests(unittest.TestCase):
    def task(self, task_id="T-02", created_at="2026-09-03T10:00:00Z"):
        return AnalysisTask(task_id, "report.pdf", "a" * 64, created_at, "待复核", "local", "text")

    def finding(self, task_id="T-02", finding_id="F-02"):
        return FindingDraft(
            task_id=task_id, finding_id=finding_id, title="审批复核缺失",
            fact_summary="抽样发现复核缺失", source_page="12", source_excerpt="未见复核签字",
            matched_risk_id="R001", domain="采购与外包", likelihood=3,
            impact_scores={dim: 2 for dim in DIMS}, rationale="控制执行不充分",
            needs_review=True,
        )

    def make_store(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        store = DesktopStore(Path(td.name) / "state.db")
        self.addCleanup(store.close)
        return store

    def test_task_roundtrip_and_schema_have_only_approved_columns_in_field_order(self):
        store = self.make_store()
        original = self.task()
        store.save_task(original)
        self.assertEqual(asdict(store.get_task(original.task_id)), asdict(original))
        expected = [field.name for field in fields(AnalysisTask)]
        self.assertEqual(store.table_columns("analysis_tasks"), expected)
        self.assertEqual(store.table_columns("findings"), [field.name for field in fields(FindingDraft)])
        self.assertEqual(store.table_columns("model_profiles"), ["name", "base_url", "model", "supports_vision"])

    def test_finding_and_profile_roundtrip_status_update_and_deterministic_order(self):
        store = self.make_store()
        store.save_task(self.task("T-late", "2026-09-04T00:00:00Z"))
        store.save_task(self.task("T-early", "2026-09-03T00:00:00Z"))
        store.save_findings([self.finding("T-late", "F-20"), self.finding("T-late", "F-10")])
        self.assertEqual([item.finding_id for item in store.list_findings("T-late")], ["F-10", "F-20"])
        changed = store.set_review_status("T-late", "F-10", "已接受")
        self.assertEqual(changed.review_status, "已接受")
        updated = store.update_finding(self.finding("T-late", "F-20"))
        self.assertEqual(updated.finding_id, "F-20")
        self.assertEqual([item.task_id for item in store.list_findings()], ["T-late", "T-late"])
        profile = ModelProfile("local", "https://model.example.test", "small", True)
        store.save_model_profile(profile)
        self.assertEqual([asdict(item) for item in store.list_model_profiles()], [asdict(profile)])

    def test_finding_id_is_task_scoped_and_task_delete_cascades(self):
        store = self.make_store()
        store.save_task(self.task("T-one"))
        store.save_task(self.task("T-two"))
        first = self.finding("T-one", "F-shared")
        second = self.finding("T-two", "F-shared")
        second.title = "T-two original"
        store.save_findings([first, second])
        first.title = "T-one revised"
        store.save_findings([first])
        self.assertEqual(store.list_findings("T-one")[0].title, "T-one revised")
        self.assertEqual(store.list_findings("T-two")[0].title, "T-two original")
        connection = sqlite3.connect(store.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with connection:
                connection.execute("DELETE FROM analysis_tasks WHERE task_id = ?", ("T-one",))
        finally:
            connection.close()
        self.assertEqual(store.list_findings("T-one"), [])
        self.assertFalse(hasattr(store, "delete_task"))

    def test_invalid_raw_database_row_is_rejected_when_read(self):
        store = self.make_store()
        store.save_task(self.task())
        connection = sqlite3.connect(store.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                connection.execute(
                    "INSERT INTO findings (task_id, finding_id, title, fact_summary, source_page, source_excerpt, matched_risk_id, domain, likelihood, impact_scores, rationale, needs_review, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("T-02", "invalid", "title", "fact", "1", "excerpt", "R001", "not-a-domain", 3, "{}", "why", 1, "待确认"),
                )
        finally:
            connection.close()
        with self.assertRaises(ValidationError):
            store.list_findings("T-02")

    def test_invalid_review_status_is_rejected_without_persisting_invalid_row(self):
        store = self.make_store()
        store.save_task(self.task())
        store.save_findings([self.finding()])
        with self.assertRaises(ValidationError):
            store.set_review_status("T-02", "F-02", "not-a-review-status")
        self.assertEqual(store.list_findings("T-02")[0].review_status, "待确认")

    def test_database_does_not_persist_secrets_full_source_or_absolute_report_path(self):
        store = self.make_store()
        task = self.task()
        profile = ModelProfile("local", "https://model.example.test", "small", True)
        finding = self.finding()
        store.save_task(task)
        store.save_model_profile(profile)
        store.save_findings([finding])
        class MemoryKeyring:
            def __init__(self):
                self.values = {}

            def set_password(self, service, name, secret):
                self.values[(service, name)] = secret

        CredentialStore(MemoryKeyring()).set_api_key("local", "sk-synthetic-secret")
        with tempfile.TemporaryDirectory() as td:
            temp = TaskTempFiles(Path(td) / "temp")
            source = temp.create(task.task_id) / "source.txt"
            source.write_text("虚构报告完整正文\nC:\\synthetic\\reports\\full-report.pdf", encoding="utf-8")
            self.assertEqual(temp.cleanup(task.task_id), [])
        payload = store.db_path.read_bytes()
        for forbidden in (b"sk-synthetic-secret", "虚构报告完整正文".encode(), b"C:\\synthetic\\reports\\full-report.pdf"):
            self.assertNotIn(forbidden, payload)
        self.assertIn(finding.source_excerpt.encode(), payload)

    def test_store_created_on_main_thread_persists_from_worker_thread(self):
        store = self.make_store()
        self.assertFalse(hasattr(store, "connection"))

        def persist_from_worker():
            task = self.task("T-worker")
            finding = self.finding("T-worker", "F-worker")
            store.save_task(task)
            store.save_findings([finding])
            return store.get_task(task.task_id), store.list_findings(task.task_id)

        with ThreadPoolExecutor(max_workers=1) as pool:
            task, findings = pool.submit(persist_from_worker).result()
        self.assertEqual(task.task_id, "T-worker")
        self.assertEqual([item.finding_id for item in findings], ["F-worker"])


if __name__ == "__main__":
    unittest.main()
