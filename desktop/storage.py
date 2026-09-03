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
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        with self.connection:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS analysis_tasks ("
                "task_id TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_hash TEXT NOT NULL, "
                "created_at TEXT NOT NULL, status TEXT NOT NULL, model_profile TEXT NOT NULL, extraction_method TEXT NOT NULL)"
            )
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS findings ("
                "task_id TEXT NOT NULL, finding_id TEXT NOT NULL, title TEXT NOT NULL, fact_summary TEXT NOT NULL, "
                "source_page TEXT NOT NULL, source_excerpt TEXT NOT NULL, matched_risk_id TEXT NOT NULL, domain TEXT NOT NULL, "
                "likelihood INTEGER, impact_scores TEXT NOT NULL, rationale TEXT NOT NULL, needs_review INTEGER NOT NULL, "
                "review_status TEXT NOT NULL, PRIMARY KEY (task_id, finding_id), "
                "FOREIGN KEY (task_id) REFERENCES analysis_tasks(task_id) ON DELETE CASCADE)"
            )
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS model_profiles ("
                "name TEXT PRIMARY KEY, base_url TEXT NOT NULL, model TEXT NOT NULL, supports_vision INTEGER NOT NULL)"
            )

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
        with self.connection:
            self.connection.execute(f"INSERT INTO analysis_tasks ({columns}) VALUES ({placeholders}) ON CONFLICT(task_id) DO UPDATE SET {assignments}", self._task_values(checked))
        return checked

    def get_task(self, task_id: str) -> AnalysisTask | None:
        row = self.connection.execute("SELECT task_id, file_name, file_hash, created_at, status, model_profile, extraction_method FROM analysis_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return None if row is None else self._row_task(row)

    def delete_task(self, task_id: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM analysis_tasks WHERE task_id = ?", (task_id,))

    def save_findings(self, findings: Iterable[FindingDraft]) -> list[FindingDraft]:
        checked = [FindingDraft(**asdict(finding)) for finding in findings]
        columns = ", ".join(_FINDING_COLUMNS)
        placeholders = ", ".join("?" for _ in _FINDING_COLUMNS)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in _FINDING_COLUMNS if column not in {"task_id", "finding_id"})
        with self.connection:
            for finding in checked:
                existing = self.connection.execute("SELECT task_id FROM findings WHERE finding_id = ?", (finding.finding_id,)).fetchone()
                if existing is not None and existing["task_id"] != finding.task_id:
                    raise ValueError("finding_id is already assigned to another task")
                self.connection.execute(f"INSERT INTO findings ({columns}) VALUES ({placeholders}) ON CONFLICT(task_id, finding_id) DO UPDATE SET {assignments}", self._finding_values(finding))
        return checked

    def list_findings(self, task_id: str | None = None) -> list[FindingDraft]:
        columns = ", ".join(_FINDING_COLUMNS)
        if task_id is None:
            query = f"SELECT f.{', f.'.join(_FINDING_COLUMNS)} FROM findings f JOIN analysis_tasks t ON t.task_id = f.task_id ORDER BY t.created_at, t.task_id, f.finding_id"
            rows = self.connection.execute(query).fetchall()
        else:
            rows = self.connection.execute(f"SELECT {columns} FROM findings WHERE task_id = ? ORDER BY finding_id", (task_id,)).fetchall()
        return [self._row_finding(row) for row in rows]

    def update_finding(self, finding: FindingDraft) -> FindingDraft:
        checked = FindingDraft(**asdict(finding))
        current = self.connection.execute("SELECT task_id FROM findings WHERE task_id = ? AND finding_id = ?", (checked.task_id, checked.finding_id)).fetchone()
        if current is None:
            raise KeyError("finding not found")
        self.save_findings([checked])
        return checked

    def set_review_status(self, task_id: str, finding_id: str, review_status: str) -> FindingDraft:
        if review_status not in ("待确认", "已接受", "已排除"):
            raise ValidationError("无效复核状态")
        with self.connection:
            cursor = self.connection.execute("UPDATE findings SET review_status = ? WHERE task_id = ? AND finding_id = ?", (review_status, task_id, finding_id))
            if cursor.rowcount != 1:
                raise KeyError("finding not found")
        for candidate in self.list_findings(task_id):
            if candidate.finding_id == finding_id:
                return candidate
        raise KeyError("finding not found")

    def save_model_profile(self, profile: ModelProfile) -> ModelProfile:
        checked = ModelProfile(**asdict(profile))
        columns = ", ".join(_PROFILE_COLUMNS)
        placeholders = ", ".join("?" for _ in _PROFILE_COLUMNS)
        assignments = ", ".join(f"{column}=excluded.{column}" for column in _PROFILE_COLUMNS if column != "name")
        with self.connection:
            self.connection.execute(f"INSERT INTO model_profiles ({columns}) VALUES ({placeholders}) ON CONFLICT(name) DO UPDATE SET {assignments}", self._profile_values(checked))
        return checked

    def list_model_profiles(self) -> list[ModelProfile]:
        columns = ", ".join(_PROFILE_COLUMNS)
        rows = self.connection.execute(f"SELECT {columns} FROM model_profiles ORDER BY name").fetchall()
        return [self._row_profile(row) for row in rows]

    def table_columns(self, table_name: str) -> list[str]:
        if table_name not in _TABLE_COLUMNS:
            raise ValueError("unknown table")
        rows = self.connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] for row in rows]
