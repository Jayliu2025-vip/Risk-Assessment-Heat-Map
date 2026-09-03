"""A deliberately local OpenAI-compatible server used by model-client tests."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tools.common import DIMS


def _finding(finding_id: str, *, matched_risk_id: str, excerpt: str) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "title": f"虚构发现 {finding_id}",
        "fact_summary": "这是仅用于本地测试的虚构审计事实。",
        "source_page": "1",
        "source_excerpt": excerpt,
        "matched_risk_id": matched_risk_id,
        "domain": "资金活动",
        "likelihood": 3,
        "impact_scores": {dim: 2 for dim in DIMS},
        "rationale": "虚构证据表明需要人工复核。",
        "needs_review": True,
    }


class FakeOpenAIServer:
    """Context manager that never binds beyond loopback and never retains secrets."""

    def __init__(self, mode: str = "success", content: str | None = None) -> None:
        self.mode = mode
        self.content = content
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("server is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    def __enter__(self) -> "FakeOpenAIServer":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {"_invalid_request": True}
                # Request observability is intentionally body-only: authorization is never retained.
                owner.requests.append(payload)
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                if owner.mode == "auth_failed":
                    self._json(401, {"error": {"message": "denied"}})
                    return
                if owner.mode == "rate_limit":
                    self._json(429, {"error": {"message": "slow down"}})
                    return
                if owner.mode == "timeout":
                    time.sleep(0.2)
                if owner.mode == "oversized_response":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(5 * 1024 * 1024 + 1))
                    self.end_headers()
                    return
                if owner.mode == "invalid_json":
                    self._json(200, "not-json", raw=True)
                    return
                content = owner.content
                if content is None:
                    content = json.dumps({"findings": [
                        _finding("F-001", matched_risk_id="R003", excerpt="虚构付款审批记录"),
                        _finding("F-002", matched_risk_id="", excerpt="虚构新增风险线索"),
                        _finding("F-003", matched_risk_id="R003", excerpt="虚构复核缺失记录"),
                    ]}, ensure_ascii=False)
                self._json(200, {"choices": [{"message": {"content": content}}]})

            def _json(self, status: int, body: Any, raw: bool = False) -> None:
                encoded = body.encode("utf-8") if raw else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # A timeout test deliberately closes the client socket first.
                    return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        assert self._thread is not None
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise RuntimeError("fake server thread did not stop")
