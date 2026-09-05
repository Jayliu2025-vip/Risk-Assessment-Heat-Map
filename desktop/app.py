"""Windows pywebview shell for the local risk-assessment heatmap."""

from __future__ import annotations

import html
from pathlib import Path
import threading
from typing import Any, Callable

if __package__ in {None, ""}:  # PyInstaller executes this entrypoint as a script.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from desktop.bridge import DesktopBridge
    from desktop.credentials import CredentialStore
    from desktop.extraction import extract_report
    from desktop.model_client import ModelClient
    from desktop.ocr import RapidOcrEngine
    from desktop.paths import resource_path, state_db_path, temp_root
    from desktop.pipeline import AnalysisPipeline
    from desktop.storage import DesktopStore
    from desktop.tempfiles import TaskTempFiles
    from desktop import workbook_writer
else:
    from .bridge import DesktopBridge
    from .credentials import CredentialStore
    from .extraction import extract_report
    from .model_client import ModelClient
    from .ocr import RapidOcrEngine
    from .paths import resource_path, state_db_path, temp_root
    from .pipeline import AnalysisPipeline
    from .storage import DesktopStore
    from .tempfiles import TaskTempFiles
    from . import workbook_writer
def build_bridge(*, state_path: Path | None = None, temp_path: Path | None = None,
                 resource_provider: Callable[[str | Path], Path] = resource_path,
                 credential_store: CredentialStore | None = None) -> DesktopBridge:
    """Wire production dependencies; all report data stays in the local pipeline."""
    store = DesktopStore(state_path or state_db_path())
    credentials = credential_store or CredentialStore()
    credentials.assert_windows_backend()
    profile_lock = threading.RLock()

    def profile_and_key(name: str):
        with profile_lock:
            profile = next((item for item in store.list_model_profiles() if item.name == name), None)
            return profile, credentials.get_api_key(name)

    pipeline = AnalysisPipeline(
        store, TaskTempFiles(temp_path or temp_root()),
        lambda source, task_dir: extract_report(source, task_dir, RapidOcrEngine()),
        ModelClient,
        lambda name: next((item for item in store.list_model_profiles() if item.name == name), None),
        credentials.get_api_key,
        (),
        profile_credential_resolver=profile_and_key,
    )
    return DesktopBridge(store=store, pipeline=pipeline, credential_store=credentials,
                         model_client_factory=ModelClient, workbook_writer=workbook_writer,
                         risk_catalog=(), profile_lock=profile_lock)


def _startup_error_page() -> str:
    message = html.escape("桌面环境未就绪，无法启用模型操作。请检查 Windows Credential Locker 与本地依赖后重试。")
    return "data:text/html," + message


def _close_pipeline(bridge: Any) -> None:
    if getattr(bridge, "_desktop_pipeline_closed", False):
        return
    setattr(bridge, "_desktop_pipeline_closed", True)
    pipeline = getattr(bridge, "_pipeline", None)
    if pipeline is None:
        pipeline = getattr(bridge, "pipeline", None)
    close = getattr(pipeline, "close", None)
    if callable(close):
        close()


def main(*, webview_module: Any | None = None, bridge_factory: Callable[[], Any] = build_bridge,
         resource_provider: Callable[[str | Path], Path] = resource_path) -> None:
    if webview_module is None:
        import webview as webview_module
    bridge = None
    try:
        try:
            bridge = bridge_factory()
            url = resource_provider("web/risk_heatmap.html").as_uri()
        except Exception:
            url = _startup_error_page()
        window = webview_module.create_window(title="审计风险评估热力图谱", url=url, js_api=bridge,
                                              width=1440, height=920, min_size=(1120, 720))
        if bridge is not None:
            bridge.attach_window(window, webview_module)
            window.events.closed += lambda: _close_pipeline(bridge)
        webview_module.start(gui="edgechromium", private_mode=True, debug=False)
    finally:
        if bridge is not None:
            _close_pipeline(bridge)


if __name__ == "__main__":
    import sys
    if "--synthetic-smoke" in sys.argv[1:]:
        import os
        from desktop.smoke import run_synthetic_smoke
        try:
            run_synthetic_smoke()
        except BaseException as exc:
            # Never let a windowed PyInstaller bootloader surface a GUI error
            # dialog for the non-interactive smoke mode.
            code = str(getattr(exc, "args", ("UNEXPECTED",))[0]).encode("ascii", "ignore")[:64]
            try:
                os.write(2, b"PACKAGED_DESKTOP_SMOKE_FAILED code=" + (code or b"UNEXPECTED") + b"\n")
            except OSError:
                pass
            os._exit(1)
        # A windowed PyInstaller executable has no ``sys.stdout``. File
        # descriptor 1 is nevertheless valid when the verifier redirects it.
        try:
            os.write(1, b"PACKAGED_DESKTOP_SMOKE_OK\n")
        except OSError:
            pass
        os._exit(0)
    else:
        main()
