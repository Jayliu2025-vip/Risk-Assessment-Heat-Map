"""Privacy-preserving, JSON-only API exposed to the local pywebview page."""

from __future__ import annotations

import base64
from dataclasses import asdict
from io import BytesIO
import hashlib
from pathlib import Path
import re
import secrets
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

from .extraction import ExtractionError, MAX_PDF_PAGES, MAX_RENDER_PIXELS, PDF_RENDER_SCALE
from .model_client import ModelError
from .models import ConfirmedControl, FindingDraft, ModelProfile, RiskDecision, ValidationError


_PAGE = re.compile(r"^第 ([1-9][0-9]*) 页$")


class _BridgeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, _BridgeError):
        return {"ok": False, "code": exc.code, "message": exc.message}
    if isinstance(exc, ValidationError):
        return {"ok": False, "code": "VALIDATION_ERROR", "message": "提交内容不符合要求"}
    if isinstance(exc, ModelError):
        return {"ok": False, "code": "MODEL_ERROR", "message": "模型服务请求失败"}
    if isinstance(exc, ExtractionError):
        return {"ok": False, "code": "EXTRACTION_ERROR", "message": "报告解析失败"}
    if isinstance(exc, KeyError):
        return {"ok": False, "code": "NOT_FOUND", "message": "请求的内容不存在"}
    return {"ok": False, "code": "OPERATION_FAILED", "message": "操作未能完成"}


def _public(method):
    def wrapped(self: "DesktopBridge", *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            value = method(self, *args, **kwargs)
            if not isinstance(value, Mapping):
                raise RuntimeError("bridge result must be a mapping")
            result = dict(value)
            result["ok"] = True
            return result
        except Exception as exc:
            return _safe_error(exc)
    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped


class DesktopBridge:
    """The only methods intentionally made visible to JavaScript are below."""

    def __init__(self, *, store: Any, pipeline: Any, credential_store: Any,
                 model_client_factory: Callable[[ModelProfile, str], Any], workbook_writer: Any,
                 risk_catalog: Iterable[Mapping[str, Any]], pdf_preview_renderer: Callable[[Path, int], bytes] | None = None,
                 webview_module: Any | None = None) -> None:
        self._store = store
        self._pipeline = pipeline
        self._credential_store = credential_store
        self._model_client_factory = model_client_factory
        self._workbook_writer = workbook_writer
        self._risk_catalog = [dict(item) for item in risk_catalog]
        self._pdf_preview_renderer = pdf_preview_renderer or self._render_pdf_page
        self._webview = webview_module
        self._window: Any | None = None
        self._selections: dict[str, tuple[Path, str]] = {}
        self._task_sources: dict[str, tuple[Path, str]] = {}
        self._commit_previews: dict[str, tuple[str, str, tuple[RiskDecision, ...]]] = {}

    def __getattr__(self, name: str) -> Any:
        # Window attachment is an application bootstrap hook, not a JS API.
        if name == "attach_window":
            return self._attach_window
        raise AttributeError(name)

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _selection(self, token: Any, purpose: str) -> Path:
        if not isinstance(token, str) or token not in self._selections:
            raise _BridgeError("SELECTION_NOT_FOUND", "所选文件已失效，请重新选择")
        path, actual = self._selections[token]
        if actual != purpose:
            raise _BridgeError("SELECTION_PURPOSE_INVALID", "所选文件用途不匹配")
        if not path.is_file():
            raise _BridgeError("SELECTION_NOT_FOUND", "所选文件不可用，请重新选择")
        return path

    @staticmethod
    def _profile_payload(value: Any) -> tuple[ModelProfile, str]:
        if not isinstance(value, Mapping):
            raise ValidationError("模型配置必须是对象")
        profile = ModelProfile(
            name=value.get("name"), base_url=value.get("base_url"), model=value.get("model"),
            supports_vision=value.get("supports_vision"),
        )
        key = value.get("api_key")
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("api_key不能为空")
        return profile, key

    def _get_profile(self, name: Any) -> ModelProfile:
        if not isinstance(name, str) or not name.strip():
            raise _BridgeError("MODEL_PROFILE_NOT_FOUND", "模型配置不存在")
        for profile in self._store.list_model_profiles():
            if profile.name == name.strip():
                return profile
        raise _BridgeError("MODEL_PROFILE_NOT_FOUND", "模型配置不存在")

    def _get_finding(self, task_id: Any, finding_id: Any) -> FindingDraft:
        if not isinstance(task_id, str) or not isinstance(finding_id, str):
            raise _BridgeError("NOT_FOUND", "请求的发现不存在")
        for item in self._store.list_findings(task_id):
            if item.finding_id == finding_id:
                return item
        raise _BridgeError("NOT_FOUND", "请求的发现不存在")

    @staticmethod
    def _decisions(value: Any) -> tuple[RiskDecision, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValidationError("decisions必须是列表")
        result = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValidationError("decision必须是对象")
            payload = dict(item)
            controls = payload.get("controls", ())
            if not isinstance(controls, (list, tuple)):
                raise ValidationError("controls必须是列表")
            payload["controls"] = tuple(control if isinstance(control, ConfirmedControl) else ConfirmedControl(**control) for control in controls)
            result.append(RiskDecision(**payload))
        return tuple(result)

    def _render_pdf_page(self, path: Path, page_number: int) -> bytes:
        import pypdfium2
        document = page = bitmap = image = None
        try:
            document = pypdfium2.PdfDocument(path)
            if len(document) > MAX_PDF_PAGES or page_number < 1 or page_number > len(document):
                raise _BridgeError("SOURCE_PAGE_INVALID", "来源页码不可用")
            page = document[page_number - 1]
            width, height = page.get_size()
            if int(width * PDF_RENDER_SCALE + .999) * int(height * PDF_RENDER_SCALE + .999) > MAX_RENDER_PIXELS:
                raise ExtractionError("PDF_RENDER_LIMIT", "PDF页面超出安全限制")
            bitmap = page.render(scale=PDF_RENDER_SCALE)
            image = bitmap.to_pil()
            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
        finally:
            for resource in (image, bitmap, page, document):
                close = getattr(resource, "close", None)
                if callable(close):
                    close()

    @_public
    def get_bootstrap(self) -> dict[str, Any]:
        from tools.common import DIMS, DIM_LABELS, DOMAINS
        tasks = [asdict(item) for item in getattr(self._store, "list_tasks", lambda: [])()]
        return {"profiles": [asdict(item) for item in self._store.list_model_profiles()], "tasks": tasks,
                "domains": list(DOMAINS), "dimensions": list(DIMS), "dimension_labels": dict(DIM_LABELS),
                "risk_catalog": self._risk_catalog, "capabilities": {"desktop": True, "source_preview": True}}

    @_public
    def choose_report(self, purpose: str = "report") -> dict[str, Any]:
        if purpose not in ("report", "workbook"):
            raise _BridgeError("SELECTION_PURPOSE_INVALID", "不支持的文件用途")
        if self._window is None:
            raise _BridgeError("WINDOW_UNAVAILABLE", "文件选择窗口不可用")
        extensions = ("PDF (*.pdf);;Word (*.docx)",) if purpose == "report" else ("Excel (*.xlsx)",)
        dialog_type = getattr(self._webview, "OPEN_DIALOG", "open")
        selected = self._window.create_file_dialog(dialog_type=dialog_type, allow_multiple=False, file_types=extensions)
        if not selected:
            raise _BridgeError("SELECTION_CANCELLED", "未选择文件")
        candidate = Path(selected[0]).resolve()
        allowed = {".pdf", ".docx"} if purpose == "report" else {".xlsx"}
        if candidate.suffix.lower() not in allowed or not candidate.is_file():
            raise _BridgeError("SELECTION_INVALID", "所选文件类型不支持")
        token = secrets.token_urlsafe(32)
        self._selections[token] = (candidate, purpose)
        return {"selection_token": token, "basename": candidate.name, "purpose": purpose}

    @_public
    def save_model_profile(self, profile: Any) -> dict[str, Any]:
        checked, key = self._profile_payload(profile)
        self._store.save_model_profile(checked)
        self._credential_store.set_api_key(checked.name, key)
        return {"profile": asdict(checked)}

    @_public
    def test_model_profile(self, profile_name: Any) -> dict[str, Any]:
        profile = self._get_profile(profile_name)
        key = self._credential_store.get_api_key(profile.name)
        if not key:
            raise _BridgeError("MODEL_CREDENTIAL_NOT_FOUND", "未找到模型密钥")
        client = self._model_client_factory(profile, key)
        try:
            client.test_connection()
        finally:
            close = getattr(client, "close", None)
            if callable(close): close()
        return {"hostname": urlparse(profile.base_url).hostname or ""}

    @_public
    def start_analysis(self, selection_token: Any, profile_name: Any) -> dict[str, Any]:
        source = self._selection(selection_token, "report")
        profile = self._get_profile(profile_name)
        task = self._pipeline.start(source, profile.name, self._risk_catalog)
        self._task_sources[task.task_id] = (source, str(selection_token))
        return {"task": asdict(task)}

    @_public
    def get_task(self, task_id: Any) -> dict[str, Any]:
        task = self._store.get_task(task_id)
        if task is None: raise _BridgeError("NOT_FOUND", "任务不存在")
        return {"task": asdict(task), "events": self._pipeline.events(task_id) if hasattr(self._pipeline, "events") else []}

    @_public
    def get_findings(self, task_id: Any) -> dict[str, Any]:
        return {"findings": [asdict(item) for item in self._store.list_findings(task_id)]}

    @_public
    def get_source_preview(self, task_id: Any, finding_id: Any) -> dict[str, Any]:
        task = self._store.get_task(task_id)
        source_info = self._task_sources.get(task_id)
        if task is None or source_info is None:
            raise _BridgeError("SOURCE_RESELECT_REQUIRED", "请重新选择原始报告以查看来源")
        finding = self._get_finding(task_id, finding_id)
        source, _ = source_info
        if not source.is_file():
            raise _BridgeError("SOURCE_RESELECT_REQUIRED", "请重新选择原始报告以查看来源")
        if _file_hash(source) != task.file_hash:
            raise _BridgeError("SOURCE_HASH_CHANGED", "原始报告已变更，请重新选择")
        if source.suffix.lower() == ".docx":
            return {"kind": "text", "source_page": finding.source_page, "source_excerpt": finding.source_excerpt}
        page = _PAGE.fullmatch(finding.source_page)
        if page is None:
            raise _BridgeError("SOURCE_PAGE_INVALID", "来源页码格式无效")
        data = self._pdf_preview_renderer(source, int(page.group(1)))
        if not isinstance(data, bytes) or not data:
            raise ExtractionError("PDF_RENDER_FAILED", "PDF页面渲染失败")
        return {"kind": "pdf", "source_page": finding.source_page,
                "image_data_url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}

    @_public
    def save_finding(self, task_id: Any, finding_id: Any, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping): raise ValidationError("finding必须是对象")
        self._get_finding(task_id, finding_id)
        edited = dict(payload); edited["task_id"], edited["finding_id"] = task_id, finding_id
        saved = self._pipeline.review_findings(task_id, [FindingDraft(**edited)])[0]
        return {"finding": asdict(saved)}

    @_public
    def merge_findings(self, task_id: Any, finding_ids: Any, payload: Any) -> dict[str, Any]:
        if not isinstance(finding_ids, (list, tuple)) or len(finding_ids) < 2 or len(set(finding_ids)) != len(finding_ids):
            raise ValidationError("至少选择两个不重复发现")
        if not isinstance(payload, Mapping): raise ValidationError("finding必须是对象")
        existing = {item.finding_id: item for item in self._store.list_findings(task_id)}
        if any(item not in existing for item in finding_ids): raise _BridgeError("NOT_FOUND", "请求的发现不存在")
        merged = dict(payload); merged["task_id"], merged["finding_id"] = task_id, finding_ids[0]
        checked = [FindingDraft(**merged)]
        for finding_id in finding_ids[1:]:
            excluded = asdict(existing[finding_id]); excluded["review_status"] = "已排除"; checked.append(FindingDraft(**excluded))
        saved = self._pipeline.review_findings(task_id, checked)
        return {"findings": [asdict(item) for item in saved]}

    @_public
    def split_finding(self, task_id: Any, finding_id: Any, payloads: Any) -> dict[str, Any]:
        original = self._get_finding(task_id, finding_id)
        if not isinstance(payloads, (list, tuple)) or len(payloads) < 2:
            raise ValidationError("至少需要两个拆分发现")
        additions = []
        for payload in payloads:
            if not isinstance(payload, Mapping): raise ValidationError("finding必须是对象")
            item = dict(payload); item["task_id"] = task_id; item["review_status"] = "待确认"
            additions.append(FindingDraft(**item))
        ids = [item.finding_id for item in additions]
        if len(ids) != len(set(ids)) or finding_id in ids:
            raise ValidationError("拆分发现ID不得重复")
        excluded = FindingDraft(**{**asdict(original), "review_status": "已排除"})
        saved = self._store.apply_finding_review_transaction(task_id, [excluded], additions)
        return {"findings": [asdict(item) for item in saved]}

    @_public
    def preview_commit(self, task_id: Any, workbook_selection_token: Any, decisions: Any) -> dict[str, Any]:
        source = self._selection(workbook_selection_token, "workbook")
        checked = self._decisions(decisions)
        findings = tuple(self._store.list_findings(task_id))
        preview = dict(self._workbook_writer.preview_changes(source, checked, findings))
        token = preview.get("commit_token")
        if not isinstance(token, str) or not token: raise _BridgeError("PREVIEW_INVALID", "提交预览无效")
        self._commit_previews[str(workbook_selection_token)] = (str(task_id), token, checked)
        return preview

    @_public
    def commit_to_workbook(self, task_id: Any, workbook_selection_token: Any, decisions: Any, expected_commit_token: Any) -> dict[str, Any]:
        source = self._selection(workbook_selection_token, "workbook")
        checked = self._decisions(decisions)
        remembered = self._commit_previews.get(str(workbook_selection_token))
        if remembered is None or remembered != (str(task_id), expected_commit_token, checked):
            raise _BridgeError("PREVIEW_STALE", "预览已失效，请重新生成")
        result = self._workbook_writer.write_versioned_workbook(source, checked, tuple(self._store.list_findings(task_id)), expected_commit_token=expected_commit_token)
        return {"workbook_path": str(result.workbook_path), "export_dir": str(result.export_dir),
                "periods": list(result.periods), "assessed_risks": list(result.assessed_risks)}

    @_public
    def cleanup_task(self, task_id: Any) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id: raise ValidationError("task_id不能为空")
        cleanup = getattr(self._pipeline, "cleanup_task", None)
        if callable(cleanup): cleanup(task_id)
        self._task_sources.pop(task_id, None)
        for token, (path, purpose) in list(self._selections.items()):
            if purpose == "report": self._selections.pop(token, None)
        return {"task_id": task_id}
