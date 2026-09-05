"""Portable, file-backed catalog for reviewed audit-report information."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
import uuid

from .models import AnalysisTask, FindingDraft


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class CatalogError(ValueError):
    """Stable catalog error carrying a user-safe code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _required_text(value: Any, field: str, *, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError("CATALOG_VALIDATION", f"{field}不能为空")
    checked = value.strip()
    if len(checked) > maximum:
        raise CatalogError("CATALOG_VALIDATION", f"{field}过长")
    return checked


def _optional_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or _DATE.fullmatch(value.strip()) is None:
        raise CatalogError("REPORT_DATE_INVALID", "报告日期必须为 YYYY-MM-DD")
    checked = value.strip()
    try:
        datetime.strptime(checked, "%Y-%m-%d")
    except ValueError as exc:
        raise CatalogError("REPORT_DATE_INVALID", "报告日期不存在") from exc
    return checked


def _safe_name(value: str) -> str:
    cleaned = _WINDOWS_UNSAFE.sub("-", value).strip(" .-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "未命名项目")[:64].rstrip(" .")


class CatalogStore:
    """Store reviewed report information below one exact user-selected root."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        candidate = Path(root).expanduser()
        if not candidate.is_absolute():
            raise CatalogError("CATALOG_ROOT_INVALID", "信息目录必须是绝对路径")
        self.root = candidate.resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.id_factory = id_factory or uuid.uuid4

    @property
    def workspace_path(self) -> Path:
        return self.root / "workspace.json"

    @property
    def index_path(self) -> Path:
        return self.root / "catalog-index.json"

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime):
            raise CatalogError("CATALOG_CLOCK_INVALID", "目录时钟无效")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")

    def _inside(self, path: Path, *, allow_root: bool = False) -> Path:
        resolved = path.resolve(strict=False)
        if (not allow_root and resolved == self.root) or (resolved != self.root and self.root not in resolved.parents):
            raise CatalogError("CATALOG_PATH_ESCAPE", "目录操作超出信息目录")
        return resolved

    def _write_json(self, path: Path, payload: Mapping[str, Any], *, overwrite: bool = True) -> None:
        target = self._inside(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise CatalogError("BATCH_EXISTS", "批次快照已经存在")
        temp = self._inside(target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp")
        data = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with temp.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if not overwrite and target.exists():
                raise CatalogError("BATCH_EXISTS", "批次快照已经存在")
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError("CATALOG_RECORD_INVALID", "目录记录无法读取") from exc
        if not isinstance(value, dict):
            raise CatalogError("CATALOG_RECORD_INVALID", "目录记录必须是对象")
        return value

    def initialize(self, entity_name: str) -> dict[str, Any]:
        name = _required_text(entity_name, "主体名称", maximum=120)
        self.root.mkdir(parents=True, exist_ok=True)
        self._inside(self.root, allow_root=True)
        if self.workspace_path.exists():
            current = self._read_json(self.workspace_path)
            if current.get("entity_name") != name:
                raise CatalogError("WORKSPACE_ENTITY_MISMATCH", "已有信息目录不能改换主体")
            return current
        now = self._now()
        workspace = {
            "schema_version": self.SCHEMA_VERSION,
            "entity_id": f"ENT-{self.id_factory().hex[:12]}",
            "entity_name": name,
            "created_at": self._iso(now),
        }
        self._write_json(self.workspace_path, workspace, overwrite=False)
        self._write_index([])
        return workspace

    def workspace(self) -> dict[str, Any] | None:
        if not self.workspace_path.is_file():
            return None
        return self._read_json(self._inside(self.workspace_path))

    def _require_workspace(self) -> dict[str, Any]:
        workspace = self.workspace()
        if workspace is None:
            raise CatalogError("WORKSPACE_NOT_CONFIGURED", "请先设置单主体信息目录")
        return workspace

    def _write_index(self, reports: list[dict[str, Any]]) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": self._iso(self._now()),
            "reports": sorted(reports, key=lambda item: (item["upload_date"], item["uploaded_at"], item["report_id"]), reverse=True),
        }
        self._write_json(self.index_path, payload)

    @staticmethod
    def _metadata(record: Mapping[str, Any], record_path: Path, root: Path) -> dict[str, Any]:
        return {
            "report_id": record["report_id"],
            "recognition_version": record["recognition_version"],
            "entity_id": record["entity_id"],
            "entity_name": record["entity_name"],
            "audit_project": record["audit_project"],
            "upload_date": record["upload_date"],
            "uploaded_at": record["uploaded_at"],
            "report_date": record.get("report_date", ""),
            "report_title": record["report_title"],
            "file_name": record["file_name"],
            "file_hash": record["file_hash"],
            "model_profile": record["model_profile"],
            "extraction_method": record["extraction_method"],
            "status": record["status"],
            "finding_count": len(record.get("findings", [])),
            "record_path": record_path.relative_to(root).as_posix(),
        }

    def _scan_reports(self) -> list[dict[str, Any]]:
        projects = self.root / "projects"
        if not projects.is_dir():
            return []
        workspace = self._require_workspace()
        reports: list[dict[str, Any]] = []
        for path in projects.glob("*/*/*/report-v*.json"):
            resolved = self._inside(path)
            if not resolved.is_file():
                continue
            record = self._read_json(resolved)
            if record.get("schema_version") != self.SCHEMA_VERSION or record.get("entity_id") != workspace.get("entity_id"):
                continue
            reports.append(self._metadata(record, resolved, self.root))
        return reports

    def _index_reports(self) -> list[dict[str, Any]]:
        if not self.index_path.is_file():
            reports = self._scan_reports()
            self._write_index(reports)
            return reports
        try:
            index = self._read_json(self._inside(self.index_path))
        except CatalogError:
            reports = self._scan_reports()
            self._write_index(reports)
            return reports
        values = index.get("reports")
        if not isinstance(values, list):
            raise CatalogError("CATALOG_INDEX_INVALID", "目录索引无效")
        return [dict(item) for item in values if isinstance(item, Mapping)]

    def list_reports(self) -> list[dict[str, Any]]:
        if self.workspace() is None:
            return []
        reports = self._index_reports()
        valid = []
        for item in reports:
            relative = item.get("record_path")
            if not isinstance(relative, str):
                continue
            path = self._inside(self.root / relative)
            if path.is_file():
                valid.append(item)
        if len(valid) != len(reports):
            valid = self._scan_reports()
            self._write_index(valid)
        return sorted(valid, key=lambda item: (item["upload_date"], item["uploaded_at"], item["report_id"]), reverse=True)

    def save_report(
        self,
        task: AnalysisTask,
        findings: Iterable[FindingDraft],
        *,
        audit_project: str,
        report_title: str,
        report_date: str | None = None,
        report_id: str | None = None,
    ) -> dict[str, Any]:
        workspace = self._require_workspace()
        checked_task = AnalysisTask(**asdict(task))
        checked_findings = [FindingDraft(**asdict(item)) for item in findings]
        if not checked_findings or any(item.review_status == "待确认" for item in checked_findings):
            raise CatalogError("REPORT_REVIEW_INCOMPLETE", "全部发现必须接受或排除")
        if any(item.task_id != checked_task.task_id for item in checked_findings):
            raise CatalogError("REPORT_TASK_MISMATCH", "发现不属于当前报告任务")
        project = _required_text(audit_project, "审计项目", maximum=120)
        title = _required_text(report_title, "报告名称", maximum=240)
        formal_date = _optional_date(report_date)
        now = self._now()
        upload_date = now.date().isoformat()
        identifier = report_id or f"REP-{self.id_factory().hex}"
        if _SAFE_ID.fullmatch(identifier) is None:
            raise CatalogError("REPORT_ID_INVALID", "报告编号无效")
        existing = [item for item in self.list_reports() if item["report_id"] == identifier]
        version = max((int(item["recognition_version"]) for item in existing), default=0) + 1
        project_id = f"PRJ-{hashlib.sha256(project.encode('utf-8')).hexdigest()[:12]}"
        directory = self._inside(self.root / "projects" / f"{project_id}--{_safe_name(project)}" / upload_date / identifier)
        record_path = self._inside(directory / f"report-v{version}.json")
        provenance_base = {
            "source_report_id": identifier,
            "source_report_title": title,
            "source_upload_date": upload_date,
            "source_audit_project": project,
        }
        serialized_findings = []
        for finding in checked_findings:
            serialized_findings.append({
                "finding": asdict(finding),
                "provenance": {
                    **provenance_base,
                    "source_finding_id": finding.finding_id,
                    "source_page": finding.source_page,
                },
            })
        record = {
            "schema_version": self.SCHEMA_VERSION,
            "report_id": identifier,
            "recognition_version": version,
            "entity_id": workspace["entity_id"],
            "entity_name": workspace["entity_name"],
            "audit_project": project,
            "upload_date": upload_date,
            "uploaded_at": self._iso(now),
            "report_date": formal_date,
            "report_title": title,
            "file_name": checked_task.file_name,
            "file_hash": checked_task.file_hash,
            "model_profile": checked_task.model_profile,
            "extraction_method": checked_task.extraction_method,
            "status": "已完成",
            "findings": serialized_findings,
        }
        self._write_json(record_path, record, overwrite=False)
        reports = [item for item in self.list_reports() if not (item["report_id"] == identifier and int(item["recognition_version"]) == version)]
        reports.append(self._metadata(record, record_path, self.root))
        self._write_index(reports)
        return record

    def load_report(self, report_id: str, recognition_version: int | None = None) -> dict[str, Any]:
        if not isinstance(report_id, str) or _SAFE_ID.fullmatch(report_id) is None:
            raise CatalogError("REPORT_ID_INVALID", "报告编号无效")
        matches = [item for item in self.list_reports() if item["report_id"] == report_id]
        if recognition_version is not None:
            matches = [item for item in matches if int(item["recognition_version"]) == recognition_version]
        if not matches:
            raise CatalogError("REPORT_NOT_FOUND", "报告信息不存在")
        selected = max(matches, key=lambda item: int(item["recognition_version"]))
        return self._read_json(self._inside(self.root / selected["record_path"]))

    def trash_report(self, report_id: str) -> dict[str, Any]:
        matches = [item for item in self.list_reports() if item["report_id"] == report_id]
        if not matches:
            raise CatalogError("REPORT_NOT_FOUND", "报告信息不存在")
        selected = max(matches, key=lambda item: int(item["recognition_version"]))
        source_file = self._inside(self.root / selected["record_path"])
        source_dir = self._inside(source_file.parent)
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        destination_dir = self._inside(self.root / "trash" / f"{stamp}--{report_id}")
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        if destination_dir.exists():
            raise CatalogError("TRASH_TARGET_EXISTS", "回收站目标已经存在")
        os.replace(source_dir, destination_dir)
        remaining = [item for item in self.list_reports() if item["report_id"] != report_id]
        self._write_index(remaining)
        destination_file = self._inside(destination_dir / source_file.name)
        return {"report_id": report_id, "trash_path": destination_file.relative_to(self.root).as_posix()}

    def clear_reports(self) -> dict[str, Any]:
        report_ids = list(dict.fromkeys(item["report_id"] for item in self.list_reports()))
        moved = [self.trash_report(report_id) for report_id in report_ids]
        return {"count": len(moved), "reports": moved}

    def save_batch(
        self,
        *,
        batch_id: str,
        period: str,
        report_refs: Iterable[Mapping[str, Any]],
        workbook: Mapping[str, Any],
        decisions: Iterable[Mapping[str, Any]],
        output: Mapping[str, Any],
    ) -> dict[str, Any]:
        workspace = self._require_workspace()
        identifier = _required_text(batch_id, "batch_id", maximum=96)
        if _SAFE_ID.fullmatch(identifier) is None:
            raise CatalogError("BATCH_ID_INVALID", "批次编号无效")
        checked_period = _required_text(period, "period", maximum=32)
        if _SAFE_ID.fullmatch(checked_period) is None:
            raise CatalogError("BATCH_PERIOD_INVALID", "评估期间无效")
        path = self._inside(self.root / "batches" / identifier / "batch.json")
        if path.exists():
            raise CatalogError("BATCH_EXISTS", "批次快照已经存在")
        snapshot = {
            "schema_version": self.SCHEMA_VERSION,
            "batch_id": identifier,
            "created_at": self._iso(self._now()),
            "entity_id": workspace["entity_id"],
            "entity_name": workspace["entity_name"],
            "period": checked_period,
            "report_refs": [dict(item) for item in report_refs],
            "workbook": dict(workbook),
            "decisions": [dict(item) for item in decisions],
            "output": dict(output),
        }
        self._write_json(path, snapshot, overwrite=False)
        return snapshot

    def load_batch(self, batch_id: str) -> dict[str, Any]:
        if not isinstance(batch_id, str) or _SAFE_ID.fullmatch(batch_id) is None:
            raise CatalogError("BATCH_ID_INVALID", "批次编号无效")
        path = self._inside(self.root / "batches" / batch_id / "batch.json")
        if not path.is_file():
            raise CatalogError("BATCH_NOT_FOUND", "批次不存在")
        return self._read_json(path)
