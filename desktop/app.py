"""Windows pywebview shell for the local risk-assessment heatmap."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Callable

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
from tools.common import load_dataset


def _catalog(provider: Callable[[str | Path], Path]) -> list[dict]:
    export_root = provider("data/export")
    config = export_root / "config.json"
    if not config.is_file():
        raise RuntimeError("风险目录资源不可用")
    catalog: dict[str, dict] = {}
    for period_dir in sorted(item for item in export_root.iterdir() if item.is_dir()):
        _, risks, _ = load_dataset(period_dir, config)
        for risk in risks:
            catalog.setdefault(str(risk["risk_id"]), dict(risk))
    return [catalog[key] for key in sorted(catalog)]


def build_bridge(*, state_path: Path | None = None, temp_path: Path | None = None,
                 resource_provider: Callable[[str | Path], Path] = resource_path,
                 credential_store: CredentialStore | None = None) -> DesktopBridge:
    """Wire production dependencies; all report data stays in the local pipeline."""
    store = DesktopStore(state_path or state_db_path())
    credentials = credential_store or CredentialStore()
    credentials.assert_windows_backend()
    catalog = _catalog(resource_provider)
    pipeline = AnalysisPipeline(
        store, TaskTempFiles(temp_path or temp_root()),
        lambda source, task_dir: extract_report(source, task_dir, RapidOcrEngine()),
        ModelClient,
        lambda name: next((item for item in store.list_model_profiles() if item.name == name), None),
        credentials.get_api_key,
        catalog,
    )
    return DesktopBridge(store=store, pipeline=pipeline, credential_store=credentials,
                         model_client_factory=ModelClient, workbook_writer=workbook_writer,
                         risk_catalog=catalog)


def _startup_error_page() -> str:
    message = html.escape("桌面环境未就绪，无法启用模型操作。请检查 Windows Credential Locker 与本地依赖后重试。")
    return "data:text/html," + message


def _close_pipeline(bridge: Any) -> None:
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
        bridge = bridge_factory()
        url = resource_provider("web/risk_heatmap.html").as_uri()
    except Exception:
        url = _startup_error_page()
    window = webview_module.create_window(title="审计风险评估热力图谱", url=url, js_api=bridge,
                                          width=1440, height=920, min_size=(1120, 720))
    if bridge is not None:
        bridge.attach_window(window)
        window.events.closed += lambda: _close_pipeline(bridge)
    webview_module.start(gui="edgechromium", private_mode=True, debug=False)


if __name__ == "__main__":
    main()
