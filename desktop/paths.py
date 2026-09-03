"""Filesystem locations for mutable desktop state and packaged resources."""

import os
from pathlib import Path, PureWindowsPath
import sys


APP_NAME = "RiskAssessmentHeatMap"


def app_root() -> Path:
    """Return the mutable per-user application root without unsafe fallbacks."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data or not local_app_data.strip():
        raise RuntimeError("LOCALAPPDATA is required for RiskAssessmentHeatMap state")
    return Path(local_app_data) / APP_NAME


def state_db_path() -> Path:
    return app_root() / "state.db"


def temp_root() -> Path:
    return app_root() / "temp"


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        try:
            return Path(sys._MEIPASS)  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise RuntimeError("frozen application has no packaged resource root") from exc
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str | Path) -> Path:
    """Resolve one packaged resource while prohibiting absolute and escaping paths."""
    if not isinstance(relative_path, (str, Path)):
        raise ValueError("resource path must be relative")
    value = str(relative_path)
    win_path = PureWindowsPath(value)
    path = Path(value)
    if not value or path.is_absolute() or win_path.is_absolute() or ".." in path.parts or ".." in win_path.parts:
        raise ValueError("resource path must be a safe relative path")
    root = _resource_root().resolve()
    target = (root / path).resolve()
    if target == root or root not in target.parents:
        raise ValueError("resource path escapes packaged resources")
    return target
