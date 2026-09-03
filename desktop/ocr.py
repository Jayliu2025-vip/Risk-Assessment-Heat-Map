"""Small, persistence-free wrapper around the local RapidOCR runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class RapidOcrEngine:
    """Load RapidOCR only when an image actually needs reading."""

    def __init__(self, engine: Callable[[str], Any] | None = None) -> None:
        self._engine = engine

    def read(self, image_path: Path) -> str:
        if self._engine is None:
            from rapidocr import RapidOCR

            self._engine = RapidOCR()
        result = self._engine(str(image_path))
        texts = getattr(result, "txts", None) if result is not None else None
        return "\n".join(str(text) for text in texts) if texts else ""
