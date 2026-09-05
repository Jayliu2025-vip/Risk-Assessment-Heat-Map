"""Bounded, privacy-preserving OpenAI-compatible model client."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import secrets
from io import BytesIO
from collections.abc import Iterable, Mapping
from itertools import islice
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from .models import FindingDraft, ModelProfile, ValidationError
from .prompts import MODEL_FINDING_FIELDS, build_analysis_messages


MAX_INPUT_CHARS = 1_000_000
MAX_RISKS = 200
MAX_VISION_IMAGES = 10
MAX_VISION_BYTES = 20 * 1024 * 1024
MAX_EVIDENCE_BLOCKS = 200
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class ModelError(RuntimeError):
    """A stable, deliberately non-diagnostic model integration error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"ModelError(code={self.code!r})"


_SAFE_MESSAGES = {
    "MODEL_AUTH_FAILED": "密钥无效或没有调用权限，请重新粘贴密钥并检查模型权限。",
    "MODEL_RATE_LIMIT": "请求受限，请稍后重试；若持续出现，请检查服务商的额度与调用限制。",
    "MODEL_TIMEOUT": "连接超时，请检查网络后重试，或换一个响应更快的模型。",
    "MODEL_CONNECTION_FAILED": "无法连接模型服务，请检查模型地址和网络。",
    "MODEL_NOT_FOUND": "接口或模型不存在，请检查服务地址及模型名称。",
    "MODEL_REQUEST_REJECTED": "服务商不接受当前请求，请检查模型是否支持聊天接口及当前调用参数。",
    "MODEL_BALANCE_REQUIRED": "服务商要求检查账户余额或计费状态，请前往服务商控制台处理。",
    "MODEL_SERVICE_UNAVAILABLE": "模型服务暂时不可用，请稍后重试。",
    "MODEL_URL_INSECURE": "模型服务地址不安全，请使用 HTTPS。",
    "MODEL_RESPONSE_ENCODING_UNSUPPORTED": "模型服务返回了不支持的响应编码。",
    "MODEL_JSON_INVALID": "模型服务返回的 JSON 无法解析。",
    "MODEL_OUTPUT_INVALID": "模型返回内容不符合发现草案格式。",
    "MODEL_INPUT_TOO_LARGE": "分析输入超过安全限制。",
    "MODEL_RESPONSE_TOO_LARGE": "模型响应超过安全限制。",
    "MODEL_INPUT_INVALID": "输入证据格式无效。",
}


def safe_model_error(code: str) -> dict[str, Any]:
    """Expose only locally defined categories and text, never remote diagnostics."""
    if code not in _SAFE_MESSAGES:
        return {"ok": False, "code": "MODEL_ERROR", "message": "模型服务请求失败，请检查配置后重试。"}
    return {"ok": False, "code": code, "message": _SAFE_MESSAGES[code]}


def _error(code: str) -> ModelError:
    return ModelError(code, _SAFE_MESSAGES[code])


def _collect_bounded(values: Iterable[Any], limit: int, error_code: str = "MODEL_INPUT_TOO_LARGE") -> list[Any]:
    """Collect at most one item beyond a cap so unbounded iterables stay bounded."""
    try:
        collected = list(islice(values, limit + 1))
    except (TypeError, ValueError):
        raise _error(error_code) from None
    if len(collected) > limit:
        raise _error(error_code)
    return collected


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ((address.version == 4 and address in ipaddress.IPv4Network("127.0.0.0/8"))
            or address == ipaddress.IPv6Address("::1"))


def serialize_evidence_blocks(blocks: Iterable[Any]) -> str:
    """Serialize extracted evidence into the canonical JSON framing for analysis."""
    serialized: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in _collect_bounded(blocks, MAX_EVIDENCE_BLOCKS, "MODEL_INPUT_INVALID"):
        if isinstance(block, Mapping):
            if set(block) != {"locator", "text"}:
                raise _error("MODEL_INPUT_INVALID")
            locator, text = block["locator"], block["text"]
        else:
            locator, text = getattr(block, "locator", None), getattr(block, "text", None)
        if not isinstance(locator, str) or not locator.strip() or not isinstance(text, str) or not text.strip():
            raise _error("MODEL_INPUT_INVALID")
        locator, text = locator.strip(), text.strip()
        if locator in seen:
            raise _error("MODEL_INPUT_INVALID")
        seen.add(locator)
        serialized.append({"locator": locator, "text": text})
    return json.dumps({"blocks": serialized}, ensure_ascii=False, separators=(",", ":"))


def normalize_endpoint(base_url: str) -> str:
    """Normalize versioned compatible bases and pasted completion endpoints."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise _error("MODEL_CONNECTION_FAILED")
    try:
        parsed = urlparse(base_url.strip())
        hostname = parsed.hostname
        # Accessing port catches malformed port strings without revealing them.
        _ = parsed.port
    except ValueError:
        raise _error("MODEL_CONNECTION_FAILED") from None
    if (parsed.scheme not in ("http", "https") or not hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.params
            or re.search(r"[\s\\\\%]", base_url.strip())):
        raise _error("MODEL_CONNECTION_FAILED")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    if path and (not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*/v[1-9][0-9]*", path)):
        raise _error("MODEL_CONNECTION_FAILED")
    if parsed.scheme == "http":
        if not _is_loopback_hostname(hostname):
            raise _error("MODEL_URL_INSECURE")
    return urlunparse((parsed.scheme, parsed.netloc, (path or "/v1") + "/chat/completions", "", "", ""))


def _content_json(content: Any) -> dict[str, Any]:
    if not isinstance(content, str):
        raise _error("MODEL_OUTPUT_INVALID")
    value = content.strip()
    fence = re.fullmatch(r"```json\r?\n(.*)\r?\n```", value, flags=re.DOTALL)
    if "```" in value and fence is None:
        raise _error("MODEL_OUTPUT_INVALID")
    raw = fence.group(1) if fence else value
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise _error("MODEL_OUTPUT_INVALID") from None
    if not isinstance(parsed, dict) or set(parsed) != {"findings"} or not isinstance(parsed["findings"], list):
        raise _error("MODEL_OUTPUT_INVALID")
    return parsed


def _parse_evidence_blocks(normalized_text: str) -> dict[str, str]:
    """Validate and index canonical structured evidence JSON."""
    if not isinstance(normalized_text, str) or not normalized_text.strip():
        raise _error("MODEL_INPUT_INVALID")
    try:
        payload = json.loads(normalized_text)
    except (TypeError, json.JSONDecodeError):
        raise _error("MODEL_INPUT_INVALID") from None
    if not isinstance(payload, dict) or set(payload) != {"blocks"} or not isinstance(payload["blocks"], list):
        raise _error("MODEL_INPUT_INVALID")
    if len(payload["blocks"]) > MAX_EVIDENCE_BLOCKS:
        raise _error("MODEL_INPUT_INVALID")
    result: dict[str, str] = {}
    for block in payload["blocks"]:
        if not isinstance(block, Mapping) or set(block) != {"locator", "text"}:
            raise _error("MODEL_INPUT_INVALID")
        locator, text = block["locator"], block["text"]
        if not isinstance(locator, str) or not locator.strip() or not isinstance(text, str) or not text.strip():
            raise _error("MODEL_INPUT_INVALID")
        locator, text = locator.strip(), text.strip()
        if locator in result:
            raise _error("MODEL_INPUT_INVALID")
        result[locator] = text
    return result


def _known_risk_ids(risk_catalog: list[Any]) -> set[str]:
    ids: set[str] = set()
    for risk in risk_catalog:
        if isinstance(risk, Mapping):
            risk_id = risk.get("risk_id")
        else:
            risk_id = getattr(risk, "risk_id", None)
        if isinstance(risk_id, str) and risk_id.strip():
            ids.add(risk_id.strip())
    return ids


def _as_prompt_catalog(risk_catalog: list[Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for risk in risk_catalog:
        if not isinstance(risk, Mapping):
            raise _error("MODEL_INPUT_TOO_LARGE")
        result.append(risk)
    return result


class ModelClient:
    """A narrow client that sends report evidence only to its configured endpoint."""

    def __init__(self, profile: ModelProfile, api_key: str) -> None:
        if not isinstance(profile, ModelProfile) or not isinstance(api_key, str) or not api_key.strip():
            raise _error("MODEL_INPUT_TOO_LARGE")
        self.profile = profile
        self._api_key = api_key.strip()
        self.endpoint = normalize_endpoint(profile.base_url)
        # Keep standard TLS verification enabled by using httpx's secure default.
        parsed = urlparse(profile.base_url)
        client_options: dict[str, Any] = {"timeout": httpx.Timeout(120, connect=10)}
        if parsed.scheme == "http" and parsed.hostname and _is_loopback_hostname(parsed.hostname):
            client_options["trust_env"] = False
        self._client = httpx.Client(**client_options)

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _validate_images(self, vision_images: Iterable[str | Path]) -> list[Path]:
        raw_paths = _collect_bounded(vision_images, MAX_VISION_IMAGES)
        try:
            paths = [Path(item) for item in raw_paths]
        except (TypeError, ValueError):
            raise _error("MODEL_INPUT_TOO_LARGE") from None
        if len(paths) > MAX_VISION_IMAGES:
            raise _error("MODEL_INPUT_TOO_LARGE")
        total = 0
        for path in paths:
            if path.suffix.lower() not in (".png", ".jpg", ".jpeg") or not path.is_file():
                raise _error("MODEL_INPUT_TOO_LARGE")
            try:
                total += path.stat().st_size
            except OSError:
                raise _error("MODEL_INPUT_TOO_LARGE") from None
            if total > MAX_VISION_BYTES:
                raise _error("MODEL_INPUT_TOO_LARGE")
        return paths

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Kimi's current models constrain sampling; GLM also defines its own
        # defaults. Do not force the generic temperature=0 onto these APIs.
        if urlparse(self.endpoint).hostname in {"api.moonshot.cn", "api.moonshot.ai", "open.bigmodel.cn", "api.z.ai"}:
            payload = {key: value for key, value in payload.items() if key != "temperature"}
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept-Encoding": "identity"}
        try:
            with self._client.stream("POST", self.endpoint, headers=headers, json=payload) as response:
                if response.status_code in (401, 403):
                    raise _error("MODEL_AUTH_FAILED")
                if response.status_code == 429:
                    raise _error("MODEL_RATE_LIMIT")
                if response.status_code == 402:
                    raise _error("MODEL_BALANCE_REQUIRED")
                if response.status_code == 404:
                    raise _error("MODEL_NOT_FOUND")
                if response.status_code in (400, 422):
                    raise _error("MODEL_REQUEST_REJECTED")
                if response.status_code >= 500:
                    raise _error("MODEL_SERVICE_UNAVAILABLE")
                if response.status_code < 200 or response.status_code >= 300:
                    raise _error("MODEL_CONNECTION_FAILED")
                encoding = response.headers.get("Content-Encoding")
                if encoding is not None and encoding.strip().lower() != "identity":
                    raise _error("MODEL_RESPONSE_ENCODING_UNSUPPORTED")
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        if int(length) > MAX_RESPONSE_BYTES:
                            raise _error("MODEL_RESPONSE_TOO_LARGE")
                    except ValueError:
                        raise _error("MODEL_JSON_INVALID") from None
                body = bytearray()
                for chunk in response.iter_raw(chunk_size=65536):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise _error("MODEL_RESPONSE_TOO_LARGE")
                    body.extend(chunk)
        except ModelError:
            raise
        except httpx.TimeoutException:
            raise _error("MODEL_TIMEOUT") from None
        except httpx.HTTPError:
            raise _error("MODEL_CONNECTION_FAILED") from None
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _error("MODEL_JSON_INVALID") from None
        if not isinstance(parsed, Mapping):
            raise _error("MODEL_JSON_INVALID")
        return dict(parsed)

    @staticmethod
    def _response_content(response: Mapping[str, Any]) -> Any:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _error("MODEL_OUTPUT_INVALID") from None

    def analyze(self, task_id: str, normalized_text: str, risk_catalog: Iterable[Mapping[str, Any]], vision_images: Iterable[str | Path]) -> list[FindingDraft]:
        if not isinstance(normalized_text, str) or len(normalized_text) > MAX_INPUT_CHARS:
            raise _error("MODEL_INPUT_TOO_LARGE")
        locator_blocks = _parse_evidence_blocks(normalized_text)
        risks = _collect_bounded(risk_catalog, MAX_RISKS)
        prompt_risks = _as_prompt_catalog(risks)
        images = self._validate_images(vision_images)
        try:
            messages = build_analysis_messages(
                normalized_text, prompt_risks,
                vision_unavailable=bool(images) and not self.profile.supports_vision,
            )
        except (TypeError, ValueError):
            raise _error("MODEL_INPUT_TOO_LARGE") from None
        sent_vision = bool(images) and self.profile.supports_vision
        if sent_vision:
            content: list[dict[str, Any]] = [{"type": "text", "text": messages[-1]["content"]}]
            image_total = 0
            for path in images:
                try:
                    with path.open("rb") as image_file:
                        raw = image_file.read(MAX_VISION_BYTES - image_total + 1)
                except OSError:
                    raise _error("MODEL_INPUT_TOO_LARGE") from None
                image_total += len(raw)
                if image_total > MAX_VISION_BYTES:
                    raise _error("MODEL_INPUT_TOO_LARGE")
                encoded = base64.b64encode(raw).decode("ascii")
                mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
            messages[-1] = {"role": "user", "content": content}
        response = self._request({"model": self.profile.model, "messages": messages, "temperature": 0})
        parsed = _content_json(self._response_content(response))
        if len(parsed["findings"]) > 200:
            raise _error("MODEL_OUTPUT_INVALID")
        known_ids = _known_risk_ids(risks)
        seen: set[str] = set()
        findings: list[FindingDraft] = []
        try:
            for item in parsed["findings"]:
                if not isinstance(item, Mapping) or set(item) != set(MODEL_FINDING_FIELDS):
                    raise ValidationError("发现字段不符合精确输出结构")
                finding = FindingDraft.from_model(task_id, item, known_ids)
                if finding.finding_id in seen:
                    raise ValidationError("finding_id重复")
                seen.add(finding.finding_id)
                block = locator_blocks.get(finding.source_page)
                if block is None or "".join(finding.source_excerpt.split()) not in "".join(block.split()):
                    finding.needs_review = True
                if images and not sent_vision:
                    finding.needs_review = True
                findings.append(finding)
        except (ValidationError, TypeError, AttributeError):
            raise _error("MODEL_OUTPUT_INVALID") from None
        return findings

    def test_connection(self) -> bool:
        response = self._request({
            "model": self.profile.model,
            "messages": [{"role": "user", "content": "只返回 OK"}],
            "temperature": 0,
        })
        content = self._response_content(response)
        if not isinstance(content, str) or content.strip() != "OK":
            raise _error("MODEL_OUTPUT_INVALID")
        return True

    def detect_vision_support(self) -> bool | None:
        """Probe this exact model with an in-memory image, never a user report.

        True requires reading a random code that appears only in the pixels.
        False means the image request was rejected; transient or ambiguous
        responses remain unknown so text-only use can still proceed.
        """
        from PIL import Image, ImageDraw, ImageFont

        challenge = "".join(secrets.choice("23456789") for _ in range(6))
        with Image.new("RGB", (240, 80), "white") as picture, BytesIO() as buffer:
            ImageDraw.Draw(picture).text((15, 15), challenge, font=ImageFont.load_default(size=40), fill="black")
            picture.save(buffer, format="PNG")
            data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        payload = {"model": self.profile.model, "temperature": 0, "messages": [{"role": "user", "content": [
            {"type": "text", "text": "请读出图片中的6位数字，只返回数字。"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}]}
        previous_timeout = self._client.timeout
        try:
            self._client.timeout = httpx.Timeout(20, connect=10)
            content = self._response_content(self._request(payload))
            return True if isinstance(content, str) and content.strip() == challenge else None
        except ModelError as exc:
            return False if exc.code == "MODEL_REQUEST_REJECTED" else None
        finally:
            self._client.timeout = previous_timeout
