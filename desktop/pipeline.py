"""Asynchronous, local-only orchestration for extracted audit-report evidence.

The SQLite store intentionally receives only task metadata and reviewed findings.
Source paths, extracted evidence, vision bytes, model credentials, and exception
details remain out of persistence and event diagnostics.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import copy
import hashlib
from pathlib import Path
import re
import threading
from typing import Any, Callable, Iterable
from uuid import uuid4

from .extraction import ExtractionResult
from .model_client import serialize_evidence_blocks
from .models import AnalysisTask, FindingDraft, ModelProfile, ValidationError
from .storage import DesktopStore
from .tempfiles import TaskTempFiles


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_RETRY_IMAGES = 10
_MAX_RETRY_IMAGE_BYTES = 20 * 1024 * 1024
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


@dataclass(slots=True)
class _ImageCache:
    suffix: str
    data: bytes


@dataclass(slots=True)
class _Runtime:
    source: Path | None = None
    evidence: str | None = None
    images: list[_ImageCache] = field(default_factory=list)
    cancellation: threading.Event = field(default_factory=threading.Event)
    future: Future[Any] | None = None


class AnalysisPipeline:
    """Run one extraction/model sequence per task with explicit safe retry paths."""

    def __init__(
        self,
        store: DesktopStore,
        temp_files: TaskTempFiles,
        extractor: Callable[[Path, Path], ExtractionResult],
        model_client_factory: Callable[[ModelProfile, str], Any],
        profile_resolver: Callable[[str], ModelProfile],
        credential_resolver: Callable[[str], str | None],
        risk_catalog: Iterable[Any] = (),
        *,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], Any] = uuid4,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.store = store
        self.temp_files = temp_files
        self.extractor = extractor
        self.model_client_factory = model_client_factory
        self.profile_resolver = profile_resolver
        self.credential_resolver = credential_resolver
        self.risk_catalog = list(risk_catalog)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.uuid_factory = uuid_factory
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis-pipeline")
        self._owns_executor = executor is None
        self._runtime: dict[str, _Runtime] = {}
        self._events: dict[str, list[dict[str, str]]] = {}
        self._lock = threading.RLock()
        self._closed = False

    def __enter__(self) -> "AnalysisPipeline":
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()

    def close(self) -> None:
        """Join owned workers so closing the desktop workflow does not leak threads."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._owns_executor:
            self._executor.shutdown(wait=True, cancel_futures=False)

    @staticmethod
    def _safe_source(value: Path | str) -> Path:
        source = Path(value)
        # Validate before hashing: neither an unsupported name nor a missing path
        # should cause an open/read operation.
        if source.suffix.lower() not in {".pdf", ".docx"}:
            raise ValueError("仅支持 PDF 或 DOCX 文件")
        if not source.exists() or not source.is_file():
            raise ValueError("所选文件不可用")
        return source

    @staticmethod
    def _file_hash(source: Path) -> str:
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
        return digest.hexdigest()

    def _now(self) -> str:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    @staticmethod
    def _code(value: object, fallback: str) -> str:
        candidate = str(value) if value is not None else ""
        return candidate if _SAFE_CODE.fullmatch(candidate) else fallback

    def _event(self, task_id: str, status: str, code: str, message: str, **extra: str) -> None:
        event: dict[str, str] = {"status": status, "code": self._code(code, "PIPELINE_FAILED"), "message": message, "timestamp": self._now()}
        event.update(extra)
        with self._lock:
            self._events.setdefault(task_id, []).append(event)

    def events(self, task_id: str) -> list[dict[str, str]]:
        with self._lock:
            return copy.deepcopy(self._events.get(task_id, []))

    def _set_status(self, task: AnalysisTask, status: str, code: str, message: str) -> AnalysisTask:
        changed = AnalysisTask(
            task_id=task.task_id, file_name=task.file_name, file_hash=task.file_hash,
            created_at=task.created_at, status=status, model_profile=task.model_profile,
            extraction_method=task.extraction_method,
        )
        self.store.save_task(changed)
        self._event(changed.task_id, changed.status, code, message)
        return changed

    def _submit(self, task: AnalysisTask, runtime: _Runtime, operation: Callable[[], None]) -> AnalysisTask:
        with self._lock:
            if self._closed:
                raise RuntimeError("分析管线已关闭")
            runtime.future = self._executor.submit(operation)
        return task

    def start(self, source_path: Path | str, model_profile: str, risk_catalog: Iterable[Any] | None = None) -> AnalysisTask:
        source = self._safe_source(source_path)
        profile = self.profile_resolver(model_profile)
        if not isinstance(profile, ModelProfile):
            raise ValidationError("模型配置不可用")
        task_id = str(self.uuid_factory())
        task = AnalysisTask(task_id, source.name, self._file_hash(source), self._now(), "提取中", profile.name, "pending")
        # Task metadata exists before a worker is accepted.  No source path is sent to SQLite.
        self.store.save_task(task)
        self._event(task_id, "提取中", "TASK_STARTED", "已开始提取")
        runtime = _Runtime(source=source)
        with self._lock:
            self._runtime[task_id] = runtime
        self.temp_files.create(task_id)
        catalog = list(risk_catalog) if risk_catalog is not None else self.risk_catalog
        return self._submit(task, runtime, lambda: self._run_extraction(task_id, source, catalog))

    def wait(self, task_id: str, timeout: float | None = None) -> AnalysisTask:
        with self._lock:
            runtime = self._runtime.get(task_id)
            future = None if runtime is None else runtime.future
        if future is not None:
            future.result(timeout=timeout)
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError("任务不存在")
        return task

    def _cancelled(self, task_id: str) -> bool:
        with self._lock:
            runtime = self._runtime.get(task_id)
            return bool(runtime and runtime.cancellation.is_set())

    def _cleanup(self, task_id: str) -> None:
        residual = self.temp_files.cleanup(task_id)
        if residual:
            task = self.store.get_task(task_id)
            if task is not None:
                # A task-scoped relative marker enables recovery without exposing
                # a source path, report content, or an arbitrary filesystem path.
                self._event(task_id, task.status, "TEMP_CLEANUP_RESIDUE", "任务临时文件未完全清理", residual_path=f"task-temp/{task_id}")

    def _cancel_failure(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if task is not None and task.status != "失败":
            self._set_status(task, "失败", "TASK_CANCELLED", "任务已取消")

    def cancel(self, task_id: str) -> AnalysisTask:
        with self._lock:
            runtime = self._runtime.get(task_id)
            if runtime is None:
                raise KeyError("任务不存在")
            runtime.cancellation.set()
        self._cancel_failure(task_id)
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError("任务不存在")
        return task

    def _extraction_failure(self, task_id: str, exc: Exception) -> None:
        if self._cancelled(task_id):
            self._cancel_failure(task_id)
            return
        task = self.store.get_task(task_id)
        if task is not None:
            self._set_status(task, "失败", self._code(getattr(exc, "code", None), "EXTRACTION_FAILED"), "报告提取失败")

    def _model_failure(self, task_id: str, exc: Exception) -> None:
        if self._cancelled(task_id):
            self._cancel_failure(task_id)
            return
        task = self.store.get_task(task_id)
        if task is not None:
            self._set_status(task, "失败", self._code(getattr(exc, "code", None), "MODEL_FAILED"), "风险分析失败")

    @staticmethod
    def _validated_findings(task_id: str, findings: Iterable[Any]) -> list[FindingDraft]:
        result: list[FindingDraft] = []
        ids: set[str] = set()
        for item in findings:
            payload = item.to_dict() if isinstance(item, FindingDraft) else dict(item)
            payload["task_id"] = task_id
            checked = FindingDraft(**payload)
            if checked.finding_id in ids:
                raise ValidationError("finding_id不得重复")
            ids.add(checked.finding_id)
            result.append(checked)
        return result

    def _cache_images(self, task_id: str, result: ExtractionResult, task_dir: Path) -> list[_ImageCache]:
        cached: list[_ImageCache] = []
        total = 0
        root = task_dir.resolve()
        for block in result.blocks:
            if block.method != "vision_required" or not block.image_path:
                continue
            if len(cached) >= _MAX_RETRY_IMAGES:
                raise ValueError("vision image limit")
            image = Path(block.image_path).resolve()
            if root not in image.parents:
                raise ValueError("vision image outside task directory")
            remaining = _MAX_RETRY_IMAGE_BYTES - total
            with image.open("rb") as handle:
                data = handle.read(remaining + 1)
            if len(data) > remaining:
                raise ValueError("vision image bytes limit")
            total += len(data)
            suffix = image.suffix.lower() if image.suffix else ".png"
            cached.append(_ImageCache(suffix=suffix, data=data))
        return cached

    def _run_extraction(self, task_id: str, source: Path, catalog: list[Any]) -> None:
        try:
            if self._cancelled(task_id):
                self._cancel_failure(task_id)
                return
            task_dir = self.temp_files.create(task_id)
            try:
                result = self.extractor(source, task_dir)
            except Exception as exc:
                self._extraction_failure(task_id, exc)
                return
            if self._cancelled(task_id):
                self._cancel_failure(task_id)
                return
            task = self.store.get_task(task_id)
            if task is None:
                return
            task = AnalysisTask(task.task_id, task.file_name, task.file_hash, task.created_at, task.status, task.model_profile, result.method)
            self.store.save_task(task)
            task = self._set_status(task, "分析中", "EXTRACTION_COMPLETED", "报告提取完成")
            evidence = serialize_evidence_blocks(result.blocks)
            try:
                images = self._cache_images(task_id, result, task_dir)
            except Exception as exc:
                self._model_failure(task_id, exc)
                return
            with self._lock:
                runtime = self._runtime[task_id]
                # Once extraction succeeds, a model retry needs only this bounded
                # cache; retain no original source location for that path.
                runtime.source = None
                runtime.evidence = evidence
                runtime.images = images
            self._run_model(task_id, catalog)
        finally:
            self._cleanup(task_id)

    def _temporary_images(self, task_id: str, cached: list[_ImageCache]) -> list[Path]:
        directory = self.temp_files.create(task_id)
        paths: list[Path] = []
        for index, image in enumerate(cached, start=1):
            target = directory / f"vision_{index:04d}{image.suffix}"
            target.write_bytes(image.data)
            paths.append(target)
        return paths

    def _call_model(self, profile: ModelProfile, credential: str, task_id: str, evidence: str, catalog: list[Any], images: list[Path]) -> list[Any]:
        client = self.model_client_factory(profile, credential)
        entered = getattr(client, "__enter__", None)
        if callable(entered):
            with client as active:
                return active.analyze(task_id, evidence, catalog, images)
        try:
            return client.analyze(task_id, evidence, catalog, images)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _run_model(self, task_id: str, catalog: list[Any]) -> None:
        try:
            if self._cancelled(task_id):
                self._cancel_failure(task_id)
                return
            task = self.store.get_task(task_id)
            with self._lock:
                runtime = self._runtime.get(task_id)
                evidence = None if runtime is None else runtime.evidence
                cached = [] if runtime is None else list(runtime.images)
            if task is None or evidence is None:
                raise ValueError("missing in-process extraction cache")
            profile = self.profile_resolver(task.model_profile)
            credential = self.credential_resolver(task.model_profile)
            if not isinstance(profile, ModelProfile) or not isinstance(credential, str) or not credential.strip():
                raise ValueError("model configuration unavailable")
            images = self._temporary_images(task_id, cached)
            response = self._call_model(profile, credential, task_id, evidence, catalog, images)
            if self._cancelled(task_id):
                self._cancel_failure(task_id)
                return
            findings = self._validated_findings(task_id, response)
            if self._cancelled(task_id):
                self._cancel_failure(task_id)
                return
            self.store.save_findings(findings)
            task = self.store.get_task(task_id)
            if task is not None:
                self._set_status(task, "待复核", "ANALYSIS_COMPLETED", "风险分析完成")
            with self._lock:
                runtime = self._runtime.get(task_id)
                if runtime is not None:
                    runtime.evidence = None
                    runtime.images.clear()
        except Exception as exc:
            self._model_failure(task_id, exc)

    def retry(self, task_id: str, source_path: Path | str | None = None, risk_catalog: Iterable[Any] | None = None) -> AnalysisTask:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError("任务不存在")
        if task.status != "失败":
            raise ValueError("仅失败任务可重试")
        catalog = list(risk_catalog) if risk_catalog is not None else self.risk_catalog
        with self._lock:
            runtime = self._runtime.get(task_id)
        if runtime is not None and runtime.evidence is not None:
            runtime.cancellation.clear()
            self.temp_files.create(task_id)
            changed = self._set_status(task, "分析中", "MODEL_RETRY_STARTED", "已重试风险分析")
            def model_retry() -> None:
                try:
                    self._run_model(task_id, catalog)
                finally:
                    self._cleanup(task_id)
            return self._submit(changed, runtime, model_retry)
        chosen: Path | None
        if source_path is not None:
            chosen = self._safe_source(source_path)
        elif runtime is not None and runtime.source is not None and runtime.source.exists():
            chosen = self._safe_source(runtime.source)
        else:
            self._event(task_id, "失败", "RETRY_SOURCE_REQUIRED", "请重新选择原始文件")
            raise ValueError("请重新选择原始文件")
        if self._file_hash(chosen) != task.file_hash:
            self._event(task_id, "失败", "RETRY_HASH_MISMATCH", "所选文件与原任务不一致")
            raise ValueError("所选文件与原任务不一致")
        runtime = runtime or _Runtime()
        runtime.source = chosen
        runtime.evidence = None
        runtime.images.clear()
        runtime.cancellation.clear()
        with self._lock:
            self._runtime[task_id] = runtime
        self.temp_files.create(task_id)
        changed = self._set_status(task, "提取中", "EXTRACTION_RETRY_STARTED", "已重新开始提取")
        return self._submit(changed, runtime, lambda: self._run_extraction(task_id, chosen, catalog))

    def review_findings(self, task_id: str, edits: Iterable[FindingDraft | dict[str, Any]]) -> list[FindingDraft]:
        existing = {item.finding_id for item in self.store.list_findings(task_id)}
        checked: list[FindingDraft] = []
        seen: set[str] = set()
        # Validate every update before save_findings opens its transaction; this
        # ensures a bad later edit cannot partially apply earlier human edits.
        for edit in edits:
            payload = edit.to_dict() if isinstance(edit, FindingDraft) else dict(edit)
            payload["task_id"] = task_id
            finding = FindingDraft(**payload)
            if finding.finding_id in seen:
                raise ValueError("finding_id不得重复")
            if finding.finding_id not in existing:
                raise KeyError("finding不存在")
            seen.add(finding.finding_id)
            checked.append(finding)
        return self.store.save_findings(checked)
