"""Small, persistence-free wrapper around the local RapidOCR runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class OcrError(RuntimeError):
    """A sanitized local-OCR failure that contains no source material."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _rapidocr_factory() -> Callable[[str], Any]:
    from rapidocr import RapidOCR

    return RapidOCR()


class RapidOcrEngine:
    """Load RapidOCR only when an image actually needs reading."""

    def __init__(self, engine: Callable[[str], Any] | None = None, factory: Callable[[], Callable[[str], Any]] | None = None) -> None:
        self._engine = engine
        self._factory = factory or _rapidocr_factory

    def read(self, image_path: Path) -> str:
        if self._engine is None:
            try:
                self._engine = self._factory()
            except Exception as exc:
                raise OcrError("OCR_UNAVAILABLE", "本地OCR服务不可用") from exc
        try:
            result = self._engine(str(image_path))
        except Exception as exc:
            raise OcrError("OCR_FAILED", "本地OCR识别失败") from exc
        texts = getattr(result, "txts", None) if result is not None else None
        return "\n".join(str(text) for text in texts) if texts else ""
