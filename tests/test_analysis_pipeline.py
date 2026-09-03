"""TDD contracts for asynchronous, local-only report analysis orchestration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import sqlite3
import tempfile
import threading
import unittest

from desktop.extraction import ExtractionError, ExtractionResult
from desktop.models import ExtractedBlock, FindingDraft, ModelProfile
from desktop.storage import DesktopStore
from desktop.tempfiles import TaskTempFiles
from tools.common import DIMS

from desktop.pipeline import AnalysisPipeline


def finding(task_id: str, finding_id: str = "F-1", status: str = "待确认") -> FindingDraft:
    return FindingDraft(
        task_id=task_id, finding_id=finding_id, title="虚构发现", fact_summary="虚构事实",
        source_page="第 1 页", source_excerpt="虚构审批记录", matched_risk_id="R-1",
        domain="资金活动", likelihood=3, impact_scores={dimension: 2 for dimension in DIMS},
        rationale="虚构依据", needs_review=True, review_status=status,
    )


class FakeExtractor:
    def __init__(self, *, fail: bool = False, block_after: threading.Event | None = None) -> None:
        self.calls = 0
        self.fail = fail
        self.entered = threading.Event()
        self.release = block_after

    def __call__(self, path: Path, task_dir: Path) -> ExtractionResult:
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            self.release.wait(2)
        if self.fail:
            raise ExtractionError("PDF_READ_FAILED", "synthetic report body must never be exposed")
        image = task_dir / "vision.png"
        image.write_bytes(b"synthetic-vision")
        return ExtractionResult([
            ExtractedBlock("第 1 页", "private normalized report body", "text"),
            ExtractedBlock("第 2 页", "需要视觉复核", "vision_required", True, str(image)),
        ], "mixed")


class FakeModel:
    def __init__(self, *, fail: bool = False, release: threading.Event | None = None) -> None:
        self.fail = fail
        self.calls = 0
        self.release = release
        self.entered = threading.Event()
        self.seen_images: list[Path] = []

    def analyze(self, task_id: str, evidence: str, catalog: list[dict], images: list[Path]) -> list[FindingDraft]:
        self.calls += 1
        self.seen_images = list(images)
        self.entered.set()
        if self.release is not None:
            self.release.wait(2)
        if self.fail:
            raise RuntimeError("key=secret-key report=synthetic report body")
        return [finding(task_id, f"F-{number}") for number in range(1, 4)]


class FakeFactory:
    def __init__(self, model: FakeModel) -> None:
        self.model = model
        self.calls = 0

    def __call__(self, profile: ModelProfile, key: str) -> FakeModel:
        self.calls += 1
        return self.model


class TrackingStore(DesktopStore):
    def __init__(self, path: Path) -> None:
        self.write_threads: list[int] = []
        super().__init__(path)

    def save_task(self, task):
        self.write_threads.append(threading.get_ident())
        return super().save_task(task)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "synthetic_report.pdf"
        self.source.write_bytes(b"synthetic source only")
        self.store = TrackingStore(self.root / "state.sqlite3")
        self.tasks = TaskTempFiles(self.root / "task-temp")
        self.profile = ModelProfile("synthetic", "http://127.0.0.1:9999", "synthetic", True)
        self.catalog = [{"risk_id": "R-1", "name": "虚构风险"}]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def pipeline(self, extractor: FakeExtractor | None = None, model: FakeModel | None = None) -> tuple[AnalysisPipeline, FakeExtractor, FakeModel]:
        active_extractor = extractor or FakeExtractor()
        active_model = model or FakeModel()
        pipeline = AnalysisPipeline(
            self.store, self.tasks, active_extractor, FakeFactory(active_model),
            lambda name: self.profile, lambda name: "secret-key", self.catalog,
            clock=lambda: datetime(2026, 9, 3, tzinfo=timezone.utc),
        )
        self.addCleanup(pipeline.close)
        return pipeline, active_extractor, active_model

    def test_success_has_ordered_status_events_findings_and_no_temp_residue(self) -> None:
        pipeline, _, model = self.pipeline()
        task = pipeline.start(self.source, "synthetic")
        complete = pipeline.wait(task.task_id, 2)
        self.assertEqual(complete.status, "待复核")
        self.assertEqual([event["status"] for event in pipeline.events(task.task_id)], ["提取中", "分析中", "待复核"])
        self.assertEqual(len(self.store.list_findings(task.task_id)), 3)
        self.assertEqual(len(model.seen_images), 1)
        self.assertFalse(self.tasks.task_dir(task.task_id).exists())
        self.assertEqual(self.store.write_threads[0], threading.get_ident())
        self.assertTrue(any(thread != threading.get_ident() for thread in self.store.write_threads[1:]))

    def test_model_failure_retries_from_process_memory_without_extracting_again(self) -> None:
        model = FakeModel(fail=True)
        pipeline, extractor, _ = self.pipeline(model=model)
        task = pipeline.start(self.source, "synthetic")
        self.assertEqual(pipeline.wait(task.task_id, 2).status, "失败")
        self.assertEqual(extractor.calls, 1)
        model.fail = False
        self.assertEqual(pipeline.wait(pipeline.retry(task.task_id).task_id, 2).status, "待复核")
        self.assertEqual(extractor.calls, 1)
        self.assertFalse(self.tasks.task_dir(task.task_id).exists())

    def test_restart_retry_requires_matching_reselected_file(self) -> None:
        model = FakeModel(fail=True)
        pipeline, _, _ = self.pipeline(model=model)
        task = pipeline.start(self.source, "synthetic")
        pipeline.wait(task.task_id, 2)
        pipeline.close()
        restarted_model = FakeModel()
        restarted = AnalysisPipeline(self.store, self.tasks, FakeExtractor(), FakeFactory(restarted_model), lambda name: self.profile, lambda name: "secret-key", self.catalog)
        self.addCleanup(restarted.close)
        with self.assertRaises(ValueError):
            restarted.retry(task.task_id)
        mismatch = self.root / "other.pdf"
        mismatch.write_bytes(b"different synthetic source")
        with self.assertRaises(ValueError):
            restarted.retry(task.task_id, mismatch)
        self.assertEqual(restarted.wait(restarted.retry(task.task_id, self.source).task_id, 2).status, "待复核")

    def test_extraction_and_model_failure_events_are_sanitized(self) -> None:
        pipeline, _, _ = self.pipeline(extractor=FakeExtractor(fail=True))
        task = pipeline.start(self.source, "synthetic")
        pipeline.wait(task.task_id, 2)
        events = pipeline.events(task.task_id)
        self.assertEqual(events[-1]["code"], "PDF_READ_FAILED")
        self.assertNotIn("synthetic report body", str(events))
        pipeline.close()
        other, _, _ = self.pipeline(model=FakeModel(fail=True))
        failed = other.start(self.source, "synthetic")
        other.wait(failed.task_id, 2)
        self.assertEqual(other.events(failed.task_id)[-1]["code"], "MODEL_FAILED")
        self.assertNotIn("secret-key", str(other.events(failed.task_id)))

    def test_cancel_before_or_after_extraction_never_persists_findings(self) -> None:
        held = threading.Event()
        extractor = FakeExtractor(block_after=held)
        pipeline, _, _ = self.pipeline(extractor=extractor)
        task = pipeline.start(self.source, "synthetic")
        extractor.entered.wait(1)
        pipeline.cancel(task.task_id)
        held.set()
        self.assertEqual(pipeline.wait(task.task_id, 2).status, "失败")
        self.assertEqual(pipeline.events(task.task_id)[-1]["code"], "TASK_CANCELLED")
        self.assertEqual(self.store.list_findings(task.task_id), [])
        model_release = threading.Event()
        model = FakeModel(release=model_release)
        after, _, _ = self.pipeline(model=model)
        late = after.start(self.source, "synthetic")
        self.assertTrue(model.entered.wait(1))
        after.cancel(late.task_id)
        model_release.set()
        self.assertEqual(after.wait(late.task_id, 2).status, "失败")
        self.assertEqual(after.events(late.task_id)[-1]["code"], "TASK_CANCELLED")
        self.assertEqual(self.store.list_findings(late.task_id), [])

    def test_cleanup_residue_is_safe_and_source_is_untouched(self) -> None:
        class FailingCleanup(TaskTempFiles):
            def cleanup(self, task_id: str):
                return [self.task_dir(task_id)]
        tasks = FailingCleanup(self.root / "residue")
        model = FakeModel()
        pipeline = AnalysisPipeline(self.store, tasks, FakeExtractor(), FakeFactory(model), lambda name: self.profile, lambda name: "secret-key", self.catalog)
        self.addCleanup(pipeline.close)
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        task = pipeline.start(self.source, "synthetic")
        pipeline.wait(task.task_id, 2)
        last = pipeline.events(task.task_id)[-1]
        self.assertEqual(last["code"], "TEMP_CLEANUP_RESIDUE")
        self.assertNotIn("synthetic_report.pdf", str(last))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)

    def test_persistence_has_no_path_evidence_or_key_and_review_is_atomic(self) -> None:
        pipeline, _, _ = self.pipeline()
        task = pipeline.start(self.source, "synthetic")
        pipeline.wait(task.task_id, 2)
        blob = (self.root / "state.sqlite3").read_bytes()
        self.assertIn(task.file_name.encode(), blob)
        self.assertIn(task.file_hash.encode(), blob)
        self.assertNotIn(str(self.source).encode(), blob)
        self.assertNotIn(b"secret-key", blob)
        self.assertNotIn(b"private normalized report body", blob)
        before = self.store.list_findings(task.task_id)
        valid = asdict(before[0]); valid["review_status"] = "已接受"
        bad = asdict(before[1]); bad["finding_id"] = "unknown"
        with self.assertRaises(KeyError):
            pipeline.review_findings(task.task_id, [valid, bad])
        self.assertEqual(self.store.list_findings(task.task_id)[0].review_status, "待确认")
        with self.assertRaises(ValueError):
            pipeline.review_findings(task.task_id, [valid, valid])
        updated = pipeline.review_findings(task.task_id, [valid])
        self.assertEqual(updated[0].review_status, "已接受")


if __name__ == "__main__":
    unittest.main()
