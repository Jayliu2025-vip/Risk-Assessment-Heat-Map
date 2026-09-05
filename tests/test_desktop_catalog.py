from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from desktop.models import AnalysisTask, FindingDraft
from tools.common import DIMS


class CatalogStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "catalog"
        self.now = datetime(2026, 9, 4, 6, 30, tzinfo=timezone.utc)
        self.ids = iter(
            [uuid.UUID("11111111-1111-4111-8111-111111111111"),
             uuid.UUID("22222222-2222-4222-8222-222222222222"),
             uuid.UUID("33333333-3333-4333-8333-333333333333")]
        )

    def store(self):
        from desktop.catalog import CatalogStore
        return CatalogStore(self.root, clock=lambda: self.now, id_factory=lambda: next(self.ids))

    @staticmethod
    def task(task_id: str = "T-1") -> AnalysisTask:
        return AnalysisTask(
            task_id=task_id,
            file_name="synthetic-report.pdf",
            file_hash="a" * 64,
            created_at="2026-09-04T06:00:00Z",
            status="待复核",
            model_profile="synthetic",
            extraction_method="text",
        )

    @staticmethod
    def finding(task_id: str = "T-1", finding_id: str = "F-1", status: str = "已接受") -> FindingDraft:
        return FindingDraft(
            task_id=task_id,
            finding_id=finding_id,
            title="供应商准入复核不充分",
            fact_summary="虚构抽样发现准入复核记录不完整",
            source_page="第 12 页",
            source_excerpt="虚构关键摘录：未见独立复核记录",
            matched_risk_id="R004",
            domain="采购与外包",
            likelihood=3,
            impact_scores={dim: 2 for dim in DIMS},
            rationale="虚构评分依据",
            needs_review=True,
            review_status=status,
        )

    def test_workspace_is_single_entity_and_cannot_be_relabelled(self) -> None:
        from desktop.catalog import CatalogError
        store = self.store()
        created = store.initialize("虚构主体甲")
        self.assertEqual(created["entity_name"], "虚构主体甲")
        self.assertEqual(created["entity_id"], "ENT-111111111111")
        self.assertEqual(store.initialize("虚构主体甲"), created)
        with self.assertRaisesRegex(CatalogError, "WORKSPACE_ENTITY_MISMATCH"):
            store.initialize("虚构主体乙")
        payload = json.loads((self.root / "workspace.json").read_text(encoding="utf-8"))
        self.assertNotIn(str(self.root), json.dumps(payload, ensure_ascii=False))

    def test_save_report_writes_only_structured_information_and_rebuilds_index(self) -> None:
        store = self.store()
        store.initialize("虚构主体甲")
        report = store.save_report(
            self.task(), [self.finding()], audit_project="采购/专项审计",
            report_title="采购管理专项审计报告", report_date="2026-08-28",
        )
        self.assertEqual(report["upload_date"], "2026-09-04")
        self.assertEqual(report["recognition_version"], 1)
        self.assertEqual(report["audit_project"], "采购/专项审计")
        self.assertEqual(report["findings"][0]["provenance"]["source_page"], "第 12 页")
        metadata = store.list_reports()
        self.assertEqual(metadata[0]["report_id"], report["report_id"])
        self.assertEqual(metadata[0]["finding_count"], 1)
        record_path = self.root / metadata[0]["record_path"]
        self.assertTrue(record_path.is_file())
        self.assertNotIn("采购/专项审计", record_path.as_posix())
        serialized = record_path.read_text(encoding="utf-8")
        self.assertNotIn("C:\\secret\\original-report.pdf", serialized)
        self.assertNotIn("完整报告正文不得持久化", serialized)
        (self.root / "catalog-index.json").unlink()
        rebuilt = store.list_reports()
        self.assertEqual([item["report_id"] for item in rebuilt], [report["report_id"]])
        self.assertTrue((self.root / "catalog-index.json").is_file())
        (self.root / "catalog-index.json").write_text("{broken index", encoding="utf-8")
        repaired = store.list_reports()
        self.assertEqual([item["report_id"] for item in repaired], [report["report_id"]])
        self.assertEqual(json.loads((self.root / "catalog-index.json").read_text(encoding="utf-8"))["reports"][0]["report_id"], report["report_id"])

    def test_report_requires_completed_human_review_and_valid_optional_date(self) -> None:
        from desktop.catalog import CatalogError
        store = self.store()
        store.initialize("虚构主体甲")
        with self.assertRaisesRegex(CatalogError, "REPORT_REVIEW_INCOMPLETE"):
            store.save_report(self.task(), [self.finding(status="待确认")], audit_project="采购审计", report_title="报告")
        with self.assertRaisesRegex(CatalogError, "REPORT_DATE_INVALID"):
            store.save_report(self.task(), [self.finding()], audit_project="采购审计", report_title="报告", report_date="2026/08/28")

    def test_trash_one_and_clear_all_are_root_scoped_and_recoverable(self) -> None:
        store = self.store()
        store.initialize("虚构主体甲")
        first = store.save_report(self.task("T-1"), [self.finding("T-1")], audit_project="采购审计", report_title="报告一")
        second = store.save_report(self.task("T-2"), [self.finding("T-2")], audit_project="合同审计", report_title="报告二")
        moved = store.trash_report(first["report_id"])
        self.assertTrue((self.root / moved["trash_path"]).is_file())
        self.assertEqual([item["report_id"] for item in store.list_reports()], [second["report_id"]])
        cleared = store.clear_reports()
        self.assertEqual(cleared["count"], 1)
        self.assertEqual(store.list_reports(), [])
        trash_records = list((self.root / "trash").rglob("report-v*.json"))
        self.assertEqual(len(trash_records), 2)
        self.assertTrue(all(self.root.resolve() in path.resolve().parents for path in trash_records))

    def test_batch_snapshot_is_immutable_and_references_exact_report_version(self) -> None:
        from desktop.catalog import CatalogError
        store = self.store()
        store.initialize("虚构主体甲")
        report = store.save_report(self.task(), [self.finding()], audit_project="采购审计", report_title="报告一")
        snapshot = store.save_batch(
            batch_id="BATCH-2026H2-001",
            period="2026H2",
            report_refs=[{"report_id": report["report_id"], "recognition_version": 1, "file_hash": "a" * 64}],
            workbook={"file_name": "audit_risk_register.xlsx", "file_hash": "b" * 64},
            decisions=[{"action": "merge", "risk_id": "R004", "finding_ids": ["F-1"]}],
            output={"file_name": "audit_risk_register_20260904_1430.xlsx", "file_hash": "c" * 64},
        )
        self.assertEqual(snapshot["report_refs"][0]["recognition_version"], 1)
        with self.assertRaisesRegex(CatalogError, "BATCH_EXISTS"):
            store.save_batch(
                batch_id="BATCH-2026H2-001", period="2026H2", report_refs=[], workbook={}, decisions=[], output={}
            )
        self.assertEqual(store.load_batch("BATCH-2026H2-001"), snapshot)


if __name__ == "__main__":
    unittest.main()
