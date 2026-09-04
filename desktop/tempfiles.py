"""Contained lifecycle management for per-task temporary workspaces."""

from pathlib import Path
import re
import shutil


_TASK_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class TaskTempFiles:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task ID must match [A-Za-z0-9_-]+")
        return task_id

    def task_dir(self, task_id: str) -> Path:
        safe_id = self._validate_task_id(task_id)
        target = (self.root / safe_id).resolve()
        if target == self.root or self.root not in target.parents:
            raise ValueError("task directory escapes temp root")
        return target

    def create(self, task_id: str) -> Path:
        target = self.task_dir(task_id)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def cleanup(self, task_id: str) -> list[Path]:
        target = self.task_dir(task_id)
        if not target.exists():
            return []
        try:
            shutil.rmtree(target)
        except OSError:
            return [target] if target.exists() else []
        return []
