"""Fully local, process-safe vertical smoke for a frozen desktop package."""

from __future__ import annotations

from dataclasses import asdict
import ipaddress
import json
import logging
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .extraction import extract_report
from .model_client import ModelClient
from .models import ConfirmedControl, FindingDraft, ModelProfile, RiskDecision
from .ocr import RapidOcrEngine
from .paths import resource_path
from .pipeline import AnalysisPipeline
from .storage import DesktopStore
from .tempfiles import TaskTempFiles
from .workbook_writer import preview_changes, write_versioned_workbook
from tools.common import DIMS, load_dataset


class SmokeError(RuntimeError):
    pass


def _fixture_path() -> Path:
    """Use the packaged fixture in frozen builds and the same synthetic source in tests."""
    packaged = resource_path("fixtures/vertical_slice_report.pdf")
    if packaged.is_file():
        return packaged
    if not getattr(sys, "frozen", False):
        source_fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "generated" / "vertical_slice_report.pdf"
        if source_fixture.is_file():
            return source_fixture
    raise SmokeError("SYNTHETIC_FIXTURE")


class OfflineSocketGuard:
    """Allow only a loopback fake server without changing machine networking."""

    def __init__(self) -> None:
        self._connection, self._getaddrinfo, self._socket = socket.create_connection, socket.getaddrinfo, socket.socket

    @staticmethod
    def _allow(address: object) -> None:
        if not isinstance(address, tuple) or not address or not isinstance(address[0], (str, bytes)):
            raise SmokeError("OFFLINE_GUARD")
        host = address[0].decode() if isinstance(address[0], bytes) else address[0]
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = host.lower() == "localhost"
        if not allowed:
            raise SmokeError("OFFLINE_GUARD")

    def install(self) -> None:
        owner = self
        def guarded_connection(address: object, *args: object, **kwargs: object):
            owner._allow(address)
            return owner._connection(address, *args, **kwargs)
        def guarded_lookup(host: str | bytes | None, *args: object, **kwargs: object):
            if host is not None:
                owner._allow((host, 0))
            return owner._getaddrinfo(host, *args, **kwargs)
        class GuardedSocket(self._socket):
            def connect(self, address: object) -> None:
                owner._allow(address)
                return super().connect(address)
        socket.create_connection, socket.getaddrinfo, socket.socket = guarded_connection, guarded_lookup, GuardedSocket

    def restore(self) -> None:
        socket.create_connection, socket.getaddrinfo, socket.socket = self._connection, self._getaddrinfo, self._socket


class LocalFakeServer:
    """A minimal loopback-only OpenAI-compatible endpoint for the smoke path."""

    def __init__(self) -> None:
        self.requests = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def __enter__(self) -> "LocalFakeServer":
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return
            def do_POST(self) -> None:  # noqa: N802
                owner.requests += 1
                body = {"choices": [{"message": {"content": json.dumps({"findings": [
                    {"finding_id": "F-001", "title": "Synthetic one", "fact_summary": "Synthetic only.", "source_page": "1", "source_excerpt": "SYNTHETIC TEST DATA", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "Synthetic local evidence.", "needs_review": True},
                    {"finding_id": "F-002", "title": "Synthetic two", "fact_summary": "Synthetic only.", "source_page": "2", "source_excerpt": "SYNTHETIC TEST DATA", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "Synthetic local evidence.", "needs_review": True},
                    {"finding_id": "F-003", "title": "Synthetic three", "fact_summary": "Synthetic only.", "source_page": "3", "source_excerpt": "SYNTHETIC TEST DATA", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "Synthetic local evidence.", "needs_review": True},
                ]}, ensure_ascii=False)}}]}
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *unused: object) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown(); self._server.server_close(); self._thread.join(timeout=2)


def run_synthetic_smoke() -> None:
    """Exercise OCR, ModelClient, pipeline and workbook writer without user state."""
    guard = OfflineSocketGuard()
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    guard.install()
    try:
        try:
            socket.create_connection(("synthetic-external.invalid", 443), timeout=0.01)
        except SmokeError:
            pass
        else:
            raise SmokeError("OFFLINE_GUARD")
        with tempfile.TemporaryDirectory(prefix="rahm-packaged-smoke-") as temporary:
            root = Path(temporary)
            report = _fixture_path()
            workbook = root / "audit_risk_register.xlsx"
            shutil.copy2(resource_path("audit_risk_register.xlsx"), workbook)
            _, catalog, _ = load_dataset(resource_path("data/export/2026H1"), resource_path("data/export/config.json"))
            with LocalFakeServer() as server:
                profile = ModelProfile("synthetic-local", server.base_url, "synthetic-model", False)
                extracted: list[Any] = []
                def extractor(source: Path, task_dir: Path):
                    result = extract_report(source, task_dir, RapidOcrEngine())
                    extracted.append(result)
                    return result
                pipeline = AnalysisPipeline(DesktopStore(root / "state.db"), TaskTempFiles(root / "temp"), extractor,
                    ModelClient, lambda _: profile, lambda _: "synthetic-key", catalog)
                try:
                    task = pipeline.start(report, profile.name)
                    if pipeline.wait(task.task_id, timeout=120).status != "待复核":
                        raise SmokeError("PIPELINE")
                    if not any(block.method == "ocr" and "SYNTHETIC TEST DATA" in block.text.upper() for result in extracted for block in result.blocks):
                        raise SmokeError("OCR")
                    findings = pipeline.store.list_findings(task.task_id)
                    if len(findings) != 3 or not server.requests:
                        raise SmokeError("MODEL")
                    pipeline.review_findings(task.task_id, (FindingDraft(**{**asdict(findings[0]), "title": "Synthetic reviewed"}),))
                    pipeline.store.set_review_status(task.task_id, "F-001", "已接受")
                    pipeline.store.set_review_status(task.task_id, "F-002", "已接受")
                    pipeline.store.set_review_status(task.task_id, "F-003", "已排除")
                    reviewed = tuple(pipeline.store.list_findings(task.task_id))
                    decision = RiskDecision("create", ("F-001", "F-002"), "", "Synthetic risk", "资金活动", "Synthetic local smoke.", "Synthetic", "2026H2", 3, {dim: 2 for dim in DIMS}, "Synthetic review.", (ConfirmedControl("Synthetic control", 4, True),))
                    excluded = RiskDecision("exclude", ("F-003",))
                    preview = preview_changes(workbook, (decision, excluded), reviewed)
                    result = write_versioned_workbook(workbook, (decision, excluded), reviewed, expected_commit_token=preview["commit_token"], timestamp="20260903_1200", output_dir=root / "versions")
                    if not result.workbook_path.is_file():
                        raise SmokeError("WRITER")
                finally:
                    pipeline.close()
    finally:
        guard.restore()
        logging.disable(previous_disable)
