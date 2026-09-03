"""Minimal, parameterized SQLite persistence for desktop review state."""

from dataclasses import asdict, fields
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .models import AnalysisTask, FindingDraft, ModelProfile, ValidationError


_TASK_COLUMNS = tuple(field.name for field in fields(AnalysisTask))
_FINDING_COLUMNS = tuple(field.name for field in fields(FindingDraft))
_PROFILE_COLUMNS = tuple(field.name for field in fields(ModelProfile))
_TABLE_COLUMNS = {
    "analysis_tasks": _TASK_COLUMNS,
    "findings": _FINDING_COLUMNS,
    "model_profiles": _PROFILE_COLUMNS,
}


class DesktopStore:
    """Use short-lived SQLite connections so callers may use worker threads."""

    def __init__(self, path: Path) -> None:
        self.db_path = Path(path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def close(self) -> None:
        """Compatibility no-op: operations do not retain a connection."""

    def _create_schema(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS analysis_tasks ("
                    "task_id TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_hash TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, status TEXT NOT NULL, model_profile TEXT NOT NULL, extraction_method TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS findings ("
                    "task_id TEXT NOT NULL, finding_id TEXT NOT NULL, title TEXT NOT NULL, fact_summary TEXT NOT NULL, "
                    "source_page TEXT NOT NULL, source_excerpt TEXT NOT NULL, matched_risk_id TEXT NOT NULL, domain TEXT NOT NULL, "
                    "likelihood INTEGER, impact_scores TEXT NOT NULL, rationale TEXT NOT NULL, needs_review INTEGER NOT NULL, "
                    "review_status TEXT NOT NULL, PRIMARY KEY (task_id, finding_id), "
                    "FOREIGN KEY (task_id) REFERENCES analysis_tasks(task_id) ON DELETE CASCADE)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS model_profiles ("
                    "name TEXT PRIMARY KEY, base_url TEXT NOT NULL, model TEXT NOT NULL, supports_vision INTEGER NOT NULL)"
                )
        finally:
            connection.close()

    @staticmethod
    def _task_values(task: AnalysisTask) -> tuple[object, ...]:
        return tuple(asdict(task)[column] for column in _TASK_COLUMNS)

    @staticmethod
    def _finding_values(finding: FindingDraft) -> tuple[object, ...]:
        values = asdict(finding)
        values["impact_scores"] = json.dumps(values["impact_scores"], ensure_ascii=False, separators=(",", ":"))
        values["needs_review"] = int(values["needs_review"])
        return tuple(values[column] for column in _FINDING_COLUMNS)

    @staticmethod
    def _profile_values(profile: ModelProfile) -> tuple[object, ...]:
        values = asdict(profile)
        values["supports_vision"] = int(values["supports_vision"])
        return tuple(values[column] for column in _PROFILE_COLUMNS)

    @staticmethod
    def _row_task(row: sqlite3.Row) -> AnalysisTask:
        return AnalysisTask(**{column: row[column] for column in _TASK_COLUMNS})

    @staticmethod
    def _row_finding(row: sqlite3.Row) -> FindingDraft:
        payload = {column: row[column] for column in _FINDING_COLUMNS}
        try:
            payload["impact_scores"] = json.loads(payload["impact_scores"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValidationError("impact_scores must be valid JSON") from exc
        if payload["needs_review"] not in (0, 1, False, True):
            raise ValidationError("needs_review must be boolean")
        payload["needs_review"] = bool(payload["needs_review"])
        return FindingDraft(**payload)

    @staticmethod
    def _row_profile(row: sqlite3.Row) -> ModelProfile:
        payload = {column: row[column] for column in _PROFILE_COLUMNS}
        if payload["supports_vision"] not in (0, 1, False, True):
            raise ValidationError("supports_vision must be boolean")
        payload["supports_vision"] = bool(payload["supports_vision"])
        return ModelProfile(**payload)

    def save_task(self, task: AnalysisTask) -> AnalysisTask:
        checked = AnalysisTask(**asdict(task))
        placeholders = ", ".join("?" for _ in _TASK_COLUMNS)
        columns = ", ".join(_TASK_COLUMNS)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in _TASK_COLUMNS if column != "task_id")
        connection = self._connect()
        try:
            with connection:
                connection.execute(f"INSERT INTO analysis_tasks ({columns}) VALUES ({placeholders}) ON CONFLICT(task_id) DO UPDATE SET {assignments}", self._task_values(checked))
        finally:
            connection.close()
        return checked

    def get_task(self, task_id: str) -> AnalysisTask | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT task_id, file_name, file_hash, created_at, status, model_profile, extraction_method FROM analysis_tasks WHERE task_id = ?", (task_id,)).fetchone()
            return None if row is None else self._row_task(row)
        finally:
            connection.close()

    def list_tasks(self) -> list[AnalysisTask]:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT task_id, file_name, file_hash, created_at, status, model_profile, extraction_method FROM analysis_tasks ORDER BY created_at DESC, task_id DESC").fetchall()
            return [self._row_task(row) for row in rows]
        finally:
            connection.close()

    def save_findings(self, findings: Iterable[FindingDraft]) -> list[FindingDraft]:
        checked = [FindingDraft(**asdict(finding)) for finding in findings]
        columns = ", ".join(_FINDING_COLUMNS)
        placeholders = ", ".join("?" for _ in _FINDING_COLUMNS)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in _FINDING_COLUMNS if column not in {"task_id", "finding_id"})
        connection = self._connect()
        try:
            with connection:
                for finding in checked:
                    connection.execute(f"INSERT INTO findings ({columns}) VALUES ({placeholders}) ON CONFLICT(task_id, finding_id) DO UPDATE SET {assignments}", self._finding_values(finding))
        finally:
            connection.close()
        return checked

    def commit_analysis_result(self, task: AnalysisTask, findings: Iterable[FindingDraft]) -> tuple[AnalysisTask, list[FindingDraft]]:
        """Atomically publish a completed analysis task and its model findings."""
        checked_task = AnalysisTask(**asdict(task))
        if checked_task.status != "待复核":
            raise ValidationError("分析结果任务状态必须为待复核")
        checked_findings = [FindingDraft(**asdict(finding)) for finding in findings]
        if any(finding.task_id != checked_task.task_id for finding in checked_findings):
            raise ValidationError("finding task_id必须与任务一致")
        finding_ids = [finding.finding_id for finding in checked_findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValidationError("finding_id不得重复")
        task_placeholders = ", ".join("?" for _ in _TASK_COLUMNS)
        task_columns = ", ".join(_TASK_COLUMNS)
        task_assignments = ", ".join(f"{column}=excluded.{column}" for column in _TASK_COLUMNS if column != "task_id")
        finding_columns = ", ".join(_FINDING_COLUMNS)
        finding_placeholders = ", ".join("?" for _ in _FINDING_COLUMNS)
        finding_assignments = ", ".join(f"{column}=excluded.{column}" for column in _FINDING_COLUMNS if column not in {"task_id", "finding_id"})
        connection = self._connect()
        try:
            with connection:
                connection.execute(f"INSERT INTO analysis_tasks ({task_columns}) VALUES ({task_placeholders}) ON CONFLICT(task_id) DO UPDATE SET {task_assignments}", self._task_values(checked_task))
                for finding in checked_findings:
                    connection.execute(f"INSERT INTO findings ({finding_columns}) VALUES ({finding_placeholders}) ON CONFLICT(task_id, finding_id) DO UPDATE SET {finding_assignments}", self._finding_values(finding))
        finally:
            connection.close()
        return checked_task, checked_findings

    def list_findings(self, task_id: str | None = None) -> list[FindingDraft]:
        columns = ", ".join(_FINDING_COLUMNS)
        connection = self._connect()
        try:
            if task_id is None:
                query = f"SELECT f.{', f.'.join(_FINDING_COLUMNS)} FROM findings f JOIN analysis_tasks t ON t.task_id = f.task_id ORDER BY t.created_at, t.task_id, f.finding_id"
                rows = connection.execute(query).fetchall()
            else:
                rows = connection.execute(f"SELECT {columns} FROM findings WHERE task_id = ? ORDER BY finding_id", (task_id,)).fetchall()
            return [self._row_finding(row) for row in rows]
        finally:
            connection.close()

    def update_finding(self, finding: FindingDraft) -> FindingDraft:
        checked = FindingDraft(**asdict(finding))
        assignments = ", ".join(f"{column} = ?" for column in _FINDING_COLUMNS if column not in {"task_id", "finding_id"})
        values = self._finding_values(checked)
        update_values = tuple(value for column, value in zip(_FINDING_COLUMNS, values) if column not in {"task_id", "finding_id"})
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(f"UPDATE findings SET {assignments} WHERE task_id = ? AND finding_id = ?", (*update_values, checked.task_id, checked.finding_id))
                if cursor.rowcount != 1:
                    raise KeyError("finding not found")
        finally:
            connection.close()
        return checked

    def apply_finding_review_transaction(self, task_id: str, updates: Iterable[FindingDraft], additions: Iterable[FindingDraft]) -> list[FindingDraft]:
        """Atomically apply reviewed existing findings and newly split drafts."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValidationError("task_id不能为空")
        checked_updates = [FindingDraft(**asdict(item)) for item in updates]
        checked_additions = [FindingDraft(**asdict(item)) for item in additions]
        all_items = checked_updates + checked_additions
        if any(item.task_id != task_id for item in all_items):
            raise ValidationError("finding task_id必须与任务一致")
        ids = [item.finding_id for item in all_items]
        if len(ids) != len(set(ids)):
            raise ValidationError("finding_id不得重复")
        existing = {item.finding_id for item in self.list_findings(task_id)}
        if any(item.finding_id not in existing for item in checked_updates):
            raise KeyError("finding not found")
        if any(item.finding_id in existing for item in checked_additions):
            raise ValidationError("拆分finding_id已存在")
        columns = ", ".join(_FINDING_COLUMNS)
        placeholders = ", ".join("?" for _ in _FINDING_COLUMNS)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in _FINDING_COLUMNS if column not in {"task_id", "finding_id"})
        connection = self._connect()
        try:
            with connection:
                for item in all_items:
                    connection.execute(f"INSERT INTO findings ({columns}) VALUES ({placeholders}) ON CONFLICT(task_id, finding_id) DO UPDATE SET {assignments}", self._finding_values(item))
        finally:
            connection.close()
        return all_items

    def set_review_status(self, task_id: str, finding_id: str, review_status: str) -> FindingDraft:
        if review_status not in ("待确认", "已接受", "已排除"):
            raise ValidationError("无效复核状态")
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute("UPDATE findings SET review_status = ? WHERE task_id = ? AND finding_id = ?", (review_status, task_id, finding_id))
                if cursor.rowcount != 1:
                    raise KeyError("finding not found")
                row = connection.execute(f"SELECT {', '.join(_FINDING_COLUMNS)} FROM findings WHERE task_id = ? AND finding_id = ?", (task_id, finding_id)).fetchone()
                return self._row_finding(row)
        finally:
            connection.close()

    def save_model_profile(self, profile: ModelProfile) -> ModelProfile:
        checked = ModelProfile(**asdict(profile))
        columns = ", ".join(_PROFILE_COLUMNS)
        placeholders = ", ".join("?" for _ in _PROFILE_COLUMNS)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in _PROFILE_COLUMNS if column != "name")
        connection = self._connect()
        try:
            with connection:
                connection.execute(f"INSERT INTO model_profiles ({columns}) VALUES ({placeholders}) ON CONFLICT(name) DO UPDATE SET {assignments}", self._profile_values(checked))
        finally:
            connection.close()
        return checked

    def list_model_profiles(self) -> list[ModelProfile]:
        columns = ", ".join(_PROFILE_COLUMNS)
        connection = self._connect()
        try:
            rows = connection.execute(f"SELECT {columns} FROM model_profiles ORDER BY name").fetchall()
            return [self._row_profile(row) for row in rows]
        finally:
            connection.close()

    def table_columns(self, table_name: str) -> list[str]:
        if table_name not in _TABLE_COLUMNS:
            raise ValueError("unknown table")
        connection = self._connect()
        try:
            rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            return [row["name"] for row in rows]
        finally:
            connection.close()
