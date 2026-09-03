"""Privacy-preserving, JSON-only API exposed to the local pywebview page."""

from __future__ import annotations

import base64
from dataclasses import asdict
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import secrets
import tempfile
import threading
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

from .extraction import (ExtractionError, MAX_PDF_PAGES, MAX_RENDER_PIXELS, MAX_SOURCE_BYTES,
                         PDF_RENDER_SCALE, extract_docx_source_text)
from .model_client import ModelError
from .models import ConfirmedControl, FindingDraft, ModelProfile, RiskDecision, ValidationError
from tools.common import DIMS, load_dataset
from .workbook_writer import load_current_controls, load_risk_catalog


_PAGE = re.compile(r"^第 ([1-9][0-9]*) 页$")
MAX_PREVIEW_PIXELS = 8_000_000
MAX_PREVIEW_PNG_BYTES = 5 * 1024 * 1024


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


def _snapshot_preview_source(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as input_file, destination.open("xb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            copied += len(chunk)
            if copied > MAX_SOURCE_BYTES:
                raise ExtractionError("SOURCE_TOO_LARGE", "输入文件超过安全大小限制")
            digest.update(chunk)
            output_file.write(chunk)
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
                 docx_preview_extractor: Callable[[Path, str], str] | None = None,
                 risk_catalog_loader: Callable[[Path], list[dict[str, Any]]] | None = None,
                 webview_module: Any | None = None, profile_lock: threading.RLock | None = None) -> None:
        self._store = store
        self._pipeline = pipeline
        self._credential_store = credential_store
        self._model_client_factory = model_client_factory
        self._workbook_writer = workbook_writer
        self._risk_catalog = [dict(item) for item in risk_catalog]
        self._pdf_preview_renderer = pdf_preview_renderer or self._render_pdf_page
        self._docx_preview_extractor = docx_preview_extractor or extract_docx_source_text
        self._risk_catalog_loader = risk_catalog_loader or load_risk_catalog
        self._webview = webview_module
        self._window: Any | None = None
        self._selections: dict[str, tuple[Path, str]] = {}
        self._task_sources: dict[str, tuple[Path, str]] = {}
        self._task_workbooks: dict[str, tuple[Path, str, str, str, list[dict[str, Any]]]] = {}
        self._commit_previews: dict[str, tuple[str, str, str, tuple[RiskDecision, ...]]] = {}
        self._tested_profiles: dict[str, str] = {}
        self._profile_lock = profile_lock or threading.RLock()
        self._task_locks: dict[str, threading.RLock] = {}
        self._task_locks_guard = threading.Lock()
        self._preview_slots = threading.BoundedSemaphore(1)
        self._preview_before_attach: Callable[[], Any] | None = None

    def __getattr__(self, name: str) -> Any:
        # Window attachment is an application bootstrap hook, not a JS API.
        if name == "attach_window":
            return self._attach_window
        raise AttributeError(name)

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _task_lock(self, task_id: Any) -> threading.RLock:
        if not isinstance(task_id, str) or not task_id:
            raise ValidationError("task_id不能为空")
        with self._task_locks_guard:
            return self._task_locks.setdefault(task_id, threading.RLock())

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

    @staticmethod
    def _profile_fingerprint(profile: ModelProfile, credential: str) -> str:
        payload = {"profile": asdict(profile), "credential_sha256": hashlib.sha256(credential.encode("utf-8")).hexdigest()}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _verified_profile(self, name: Any) -> ModelProfile:
        with self._profile_lock:
            profile = self._get_profile(name)
            credential = self._credential_store.get_api_key(profile.name)
            if not isinstance(credential, str) or not credential.strip():
                raise _BridgeError("MODEL_CREDENTIAL_NOT_FOUND", "未找到模型密钥")
            if self._tested_profiles.get(profile.name) != self._profile_fingerprint(profile, credential):
                raise _BridgeError("MODEL_PROFILE_TEST_REQUIRED", "当前模型配置尚未通过连接测试")
            return profile

    def _bound_workbook(self, task_id: str, token: Any, period: Any) -> Path:
        binding = self._task_workbooks.get(task_id)
        if binding is None:
            raise _BridgeError("WORKBOOK_RESELECT_REQUIRED", "分析所用工作簿已失效，请重新开始分析")
        path, expected_token, expected_hash, expected_period, _ = binding
        if token != expected_token or period != expected_period:
            raise _BridgeError("WORKBOOK_SELECTION_MISMATCH", "必须使用开始分析时选择的工作簿和期间")
        selected = self._selection(token, "workbook")
        if selected != path or _file_hash(selected) != expected_hash:
            raise _BridgeError("WORKBOOK_HASH_CHANGED", "工作簿已变更，请重新开始分析")
        return selected

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

    @staticmethod
    def _decision_period(period: Any, decisions: tuple[RiskDecision, ...]) -> str:
        if not isinstance(period, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", period) is None:
            raise ValidationError("评估期间格式无效")
        decision_periods = {item.period for item in decisions if item.action != "exclude"}
        if decision_periods != {period}:
            raise ValidationError("提交决策必须且只能对应当前评估期间")
        return period

    @staticmethod
    def _control_identities(period: Any, identities: Any) -> list[dict[str, Any]]:
        if not isinstance(period, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", period) is None:
            raise ValidationError("评估期间格式无效")
        if not isinstance(identities, (list, tuple)):
            raise ValidationError("控制点载入请求必须是列表")
        result = []
        for item in identities:
            if not isinstance(item, Mapping):
                raise ValidationError("控制点载入标识必须是对象")
            action, risk_id, item_period, finding_ids = item.get("action"), item.get("risk_id"), item.get("period"), item.get("finding_ids")
            if action not in ("create", "merge") or item_period != period:
                raise ValidationError("控制点载入标识期间无效")
            if not isinstance(finding_ids, (list, tuple)) or not finding_ids or any(not isinstance(value, str) or not value.strip() for value in finding_ids):
                raise ValidationError("finding_ids无效")
            if action == "merge" and (not isinstance(risk_id, str) or not re.fullmatch(r"R\d{3}", risk_id)):
                raise ValidationError("合并风险编号无效")
            result.append({"finding_ids": [value.strip() for value in finding_ids], "action": action,
                           "risk_id": risk_id if action == "merge" else "", "period": period})
        return result

    @staticmethod
    def _finding_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValidationError("finding必须是对象")
        allowed = {"task_id", "finding_id", "title", "fact_summary", "source_page", "source_excerpt",
                   "matched_risk_id", "domain", "likelihood", "impact_scores", "rationale",
                   "needs_review", "review_status", "merged_finding_ids", "merged_into"}
        if set(payload) - allowed or any(dimension in payload for dimension in DIMS):
            raise ValidationError("finding字段无效")
        scores = payload.get("impact_scores")
        if not isinstance(scores, Mapping) or set(scores) != set(DIMS):
            raise ValidationError("impact_scores必须包含全部影响维度")
        return dict(payload)

    def _render_pdf_page(self, path: Path, page_number: int) -> bytes:
        import pypdfium2
        document = page = bitmap = image = None
        try:
            document = pypdfium2.PdfDocument(path)
            if len(document) > MAX_PDF_PAGES or page_number < 1 or page_number > len(document):
                raise _BridgeError("SOURCE_PAGE_INVALID", "来源页码不可用")
            page = document[page_number - 1]
            width, height = page.get_size()
            pixels = int(width * PDF_RENDER_SCALE + .999) * int(height * PDF_RENDER_SCALE + .999)
            if pixels > min(MAX_RENDER_PIXELS, MAX_PREVIEW_PIXELS):
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
                "risk_catalog": [], "capabilities": {"desktop": True, "source_preview": True}}

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
        with self._profile_lock:
            previous = next((item for item in self._store.list_model_profiles() if item.name == checked.name), None)
            old_key = self._credential_store.get_api_key(checked.name)
            self._credential_store.set_api_key(checked.name, key)
            try:
                self._store.save_model_profile(checked)
            except Exception:
                if old_key:
                    self._credential_store.set_api_key(checked.name, old_key)
                else:
                    self._credential_store.delete_api_key(checked.name)
                raise
            self._tested_profiles.pop(checked.name, None)
        return {"profile": asdict(checked)}

    @_public
    def test_model_profile(self, profile_name: Any) -> dict[str, Any]:
        with self._profile_lock:
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
            self._tested_profiles[profile.name] = self._profile_fingerprint(profile, key)
        return {"hostname": urlparse(profile.base_url).hostname or ""}

    @_public
    def start_analysis(self, selection_token: Any, workbook_selection_token: Any, period: Any, profile_name: Any) -> dict[str, Any]:
        source = self._selection(selection_token, "report")
        workbook = self._selection(workbook_selection_token, "workbook")
        if not isinstance(period, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", period) is None:
            raise ValidationError("评估期间格式无效")
        profile = self._verified_profile(profile_name)
        before = _file_hash(workbook)
        catalog = self._risk_catalog_loader(workbook)
        if _file_hash(workbook) != before:
            raise _BridgeError("WORKBOOK_HASH_CHANGED", "工作簿读取期间发生变更，请重新选择")
        task = self._pipeline.start(source, profile.name, catalog)
        self._task_sources[task.task_id] = (source, str(selection_token))
        self._task_workbooks[task.task_id] = (workbook, str(workbook_selection_token), before, period, [dict(item) for item in catalog])
        return {"task": asdict(task), "risk_catalog": catalog, "period": period}

    @_public
    def get_task(self, task_id: Any) -> dict[str, Any]:
        task = self._store.get_task(task_id)
        if task is None: raise _BridgeError("NOT_FOUND", "任务不存在")
        return {"task": asdict(task), "events": self._pipeline.events(task_id) if hasattr(self._pipeline, "events") else []}

    @_public
    def get_findings(self, task_id: Any) -> dict[str, Any]:
        return {"findings": [asdict(item) for item in self._store.list_findings(task_id)]}

    @_public
    def get_source_preview(self, task_id: Any, finding_id: Any, selection_token: Any = None) -> dict[str, Any]:
        with self._task_lock(task_id):
            if not self._preview_slots.acquire(blocking=False):
                raise _BridgeError("PREVIEW_BUSY", "来源预览正在生成，请稍后重试")
            try:
                return self._get_source_preview(task_id, finding_id, selection_token)
            finally:
                self._preview_slots.release()

    def _get_source_preview(self, task_id: Any, finding_id: Any, selection_token: Any = None) -> dict[str, Any]:
        task = self._store.get_task(task_id)
        source_info = self._task_sources.get(task_id)
        if task is None:
            raise _BridgeError("SOURCE_RESELECT_REQUIRED", "请重新选择原始报告以查看来源")
        pending_attachment: tuple[Path, str] | None = None
        if source_info is None:
            if selection_token is None:
                raise _BridgeError("SOURCE_RESELECT_REQUIRED", "请重新选择原始报告以查看来源")
            source = self._selection(selection_token, "report")
            source_info = (source, str(selection_token))
            pending_attachment = source_info
        finding = self._get_finding(task_id, finding_id)
        source, _ = source_info
        if not source.is_file():
            raise _BridgeError("SOURCE_RESELECT_REQUIRED", "请重新选择原始报告以查看来源")
        try:
            with tempfile.TemporaryDirectory(prefix="rahm-preview-") as directory:
                snapshot = Path(directory) / f"source{source.suffix.lower()}"
                if _snapshot_preview_source(source, snapshot) != task.file_hash:
                    raise _BridgeError("SOURCE_HASH_CHANGED", "原始报告已变更，请重新选择")
                if pending_attachment is not None and self._preview_before_attach is not None:
                    self._preview_before_attach()
                if source.suffix.lower() == ".docx":
                    text = self._docx_preview_extractor(snapshot, finding.source_page)
                    if pending_attachment is not None:
                        self._task_sources[task_id] = pending_attachment
                    return {"kind": "text", "source_page": finding.source_page, "source_excerpt": text}
                page = _PAGE.fullmatch(finding.source_page)
                if page is None:
                    raise _BridgeError("SOURCE_PAGE_INVALID", "来源页码格式无效")
                data = self._pdf_preview_renderer(snapshot, int(page.group(1)))
                if not isinstance(data, bytes) or not data:
                    raise ExtractionError("PDF_RENDER_FAILED", "PDF页面渲染失败")
                if len(data) > MAX_PREVIEW_PNG_BYTES:
                    raise _BridgeError("PREVIEW_TOO_LARGE", "来源预览超过安全大小限制")
                if pending_attachment is not None:
                    self._task_sources[task_id] = pending_attachment
                return {"kind": "pdf", "source_page": finding.source_page,
                        "image_data_url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}
        except _BridgeError:
            raise
        except ExtractionError:
            raise
        except Exception:
            raise _BridgeError("SOURCE_RESELECT_REQUIRED", "原始报告不可用，请重新选择") from None

    @_public
    def save_finding(self, task_id: Any, finding_id: Any, payload: Any) -> dict[str, Any]:
        with self._task_lock(task_id):
            current = self._get_finding(task_id, finding_id)
            edited = self._finding_payload(payload); edited["task_id"], edited["finding_id"] = task_id, finding_id
            # Merge lineage is server-managed. Editing the human-facing fields
            # must never detach the preserved secondary evidence.
            edited["merged_finding_ids"] = current.merged_finding_ids
            edited["merged_into"] = current.merged_into
            saved = self._pipeline.review_findings(task_id, [FindingDraft(**edited)])[0]
        return {"finding": asdict(saved)}

    @_public
    def merge_findings(self, task_id: Any, finding_ids: Any, payload: Any) -> dict[str, Any]:
        with self._task_lock(task_id):
            return self._merge_findings(task_id, finding_ids, payload)

    def _merge_findings(self, task_id: Any, finding_ids: Any, payload: Any) -> dict[str, Any]:
        if not isinstance(finding_ids, (list, tuple)) or len(finding_ids) < 2 or len(set(finding_ids)) != len(finding_ids):
            raise ValidationError("至少选择两个不重复发现")
        existing = {item.finding_id: item for item in self._store.list_findings(task_id)}
        if any(item not in existing for item in finding_ids): raise _BridgeError("NOT_FOUND", "请求的发现不存在")
        primary_id = str(finding_ids[0])
        if any(existing[finding_id].merged_into for finding_id in finding_ids):
            raise ValidationError("已并入其他发现的条目不能再次合并")
        linked = []
        for finding_id in finding_ids:
            if finding_id != primary_id:
                linked.append(str(finding_id))
            linked.extend(existing[finding_id].merged_finding_ids)
        linked = list(dict.fromkeys(item for item in linked if item != primary_id))
        merged = self._finding_payload(payload); merged["task_id"], merged["finding_id"] = task_id, primary_id
        merged["merged_finding_ids"], merged["merged_into"] = linked, ""
        checked = [FindingDraft(**merged)]
        for finding_id in finding_ids[1:]:
            secondary = asdict(existing[finding_id])
            secondary.update({"review_status": "已接受", "merged_finding_ids": (), "merged_into": primary_id})
            checked.append(FindingDraft(**secondary))
        saved = self._pipeline.review_findings(task_id, checked)
        return {"findings": [asdict(item) for item in saved]}

    @_public
    def split_finding(self, task_id: Any, finding_id: Any, payloads: Any) -> dict[str, Any]:
        with self._task_lock(task_id):
            return self._split_finding(task_id, finding_id, payloads)

    def _split_finding(self, task_id: Any, finding_id: Any, payloads: Any) -> dict[str, Any]:
        original = self._get_finding(task_id, finding_id)
        if not isinstance(payloads, (list, tuple)) or len(payloads) < 2:
            raise ValidationError("至少需要两个拆分发现")
        additions = []
        for payload in payloads:
            item = self._finding_payload(payload); item["task_id"] = task_id; item["review_status"] = "待确认"
            additions.append(FindingDraft(**item))
        ids = [item.finding_id for item in additions]
        if len(ids) != len(set(ids)) or finding_id in ids:
            raise ValidationError("拆分发现ID不得重复")
        excluded = FindingDraft(**{**asdict(original), "review_status": "已排除"})
        saved = self._store.apply_finding_review_transaction(task_id, [excluded], additions)
        return {"findings": [asdict(item) for item in saved]}

    @_public
    def preview_commit(self, task_id: Any, workbook_selection_token: Any, period: Any, decisions: Any,
                       stage: Any = "preview", controls_confirmed: Any = False) -> dict[str, Any]:
        with self._task_lock(task_id):
            source = self._bound_workbook(str(task_id), workbook_selection_token, period)
            if stage == "load_controls":
                identities = self._control_identities(period, decisions)
                return {"controls_by_decision": load_current_controls(source, identities)}
            if stage != "preview" or controls_confirmed is not True:
                raise ValidationError("必须确认已显示的当前控制点后才能生成预览")
            checked = self._decisions(decisions)
            checked_period = self._decision_period(period, checked)
            if any(item.action != "exclude" and item.remediation_status == "未确认" for item in checked):
                raise ValidationError("必须确认整改状态")
            findings = tuple(self._store.list_findings(task_id))
            preview = dict(self._workbook_writer.preview_changes(source, checked, findings))
            token = preview.get("commit_token")
            if not isinstance(token, str) or not token: raise _BridgeError("PREVIEW_INVALID", "提交预览无效")
            self._commit_previews[str(workbook_selection_token)] = (str(task_id), checked_period, token, checked)
        return preview

    @_public
    def commit_to_workbook(self, task_id: Any, workbook_selection_token: Any, period: Any, decisions: Any, expected_commit_token: Any) -> dict[str, Any]:
        with self._task_lock(task_id):
            source = self._bound_workbook(str(task_id), workbook_selection_token, period)
            checked = self._decisions(decisions)
            checked_period = self._decision_period(period, checked)
            if any(item.action != "exclude" and item.remediation_status == "未确认" for item in checked):
                raise ValidationError("必须确认整改状态")
            remembered = self._commit_previews.get(str(workbook_selection_token))
            if remembered is None or remembered != (str(task_id), checked_period, expected_commit_token, checked):
                raise _BridgeError("PREVIEW_REQUIRED", "请重新生成提交预览")
            self._commit_previews.pop(str(workbook_selection_token), None)
            result = self._workbook_writer.write_versioned_workbook(source, checked, tuple(self._store.list_findings(task_id)), expected_commit_token=expected_commit_token)
            _, risks, controls = load_dataset(result.export_dir / checked_period, result.export_dir / "config.json")
        return {"workbook_path": str(result.workbook_path), "export_dir": str(result.export_dir),
                "period_data": {"period": checked_period, "risks": risks, "controls": controls}}

    @_public
    def cleanup_task(self, task_id: Any) -> dict[str, Any]:
        with self._task_lock(task_id):
            if not isinstance(task_id, str) or not task_id: raise ValidationError("task_id不能为空")
            cleanup = getattr(self._pipeline, "cleanup_task", None)
            if callable(cleanup): cleanup(task_id)
            source_info = self._task_sources.pop(task_id, None)
            if source_info is not None:
                self._selections.pop(source_info[1], None)
            workbook_info = self._task_workbooks.pop(task_id, None)
            if workbook_info is not None:
                self._selections.pop(workbook_info[1], None)
            for token, preview in list(self._commit_previews.items()):
                if preview[0] == task_id:
                    self._commit_previews.pop(token, None)
                    self._selections.pop(token, None)
        return {"task_id": task_id}
