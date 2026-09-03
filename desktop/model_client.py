"""Bounded, privacy-preserving OpenAI-compatible model client."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
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
    "MODEL_AUTH_FAILED": "模型鉴权失败，请检查已保存的密钥。",
    "MODEL_RATE_LIMIT": "模型服务请求过于频繁，请稍后重试。",
    "MODEL_TIMEOUT": "模型服务响应超时，请稍后重试。",
    "MODEL_CONNECTION_FAILED": "无法连接模型服务，请检查模型地址和网络。",
    "MODEL_URL_INSECURE": "模型服务地址不安全，请使用 HTTPS。",
    "MODEL_RESPONSE_ENCODING_UNSUPPORTED": "模型服务返回了不支持的响应编码。",
    "MODEL_JSON_INVALID": "模型服务返回的 JSON 无法解析。",
    "MODEL_OUTPUT_INVALID": "模型返回内容不符合发现草案格式。",
    "MODEL_INPUT_TOO_LARGE": "分析输入超过安全限制。",
    "MODEL_RESPONSE_TOO_LARGE": "模型响应超过安全限制。",
}


def _error(code: str) -> ModelError:
    return ModelError(code, _SAFE_MESSAGES[code])


def _collect_bounded(values: Iterable[Any], limit: int) -> list[Any]:
    """Collect at most one item beyond a cap so unbounded iterables stay bounded."""
    try:
        collected = list(islice(values, limit + 1))
    except (TypeError, ValueError):
        raise _error("MODEL_INPUT_TOO_LARGE") from None
    if len(collected) > limit:
        raise _error("MODEL_INPUT_TOO_LARGE")
    return collected


def normalize_endpoint(base_url: str) -> str:
    """Allow only an origin or exact /v1 base, without retaining credentials."""
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
            or parsed.path not in ("", "/v1")):
        raise _error("MODEL_CONNECTION_FAILED")
    if parsed.scheme == "http":
        loopback = hostname.lower() == "localhost"
        if not loopback:
            try:
                address = ipaddress.ip_address(hostname)
                loopback = ((address.version == 4 and address in ipaddress.IPv4Network("127.0.0.0/8"))
                            or address == ipaddress.IPv6Address("::1"))
            except ValueError:
                loopback = False
        if not loopback:
            raise _error("MODEL_URL_INSECURE")
    return urlunparse((parsed.scheme, parsed.netloc, "/v1/chat/completions", "", "", ""))


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


def _locator_blocks(normalized_text: str) -> dict[str, str]:
    """Index exact ``[locator]\ntext`` blocks for locator-scoped evidence checks."""
    marker = re.compile(r"(?m)^\[([^\]\r\n]+)\]\r?\n")
    matches = list(marker.finditer(normalized_text))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_text)
        locator = match.group(1)
        block = normalized_text[match.end():end]
        blocks[locator] = f"{blocks[locator]}\n{block}" if locator in blocks else block
    return blocks


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
        self._client = httpx.Client(timeout=httpx.Timeout(120, connect=10))

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
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept-Encoding": "identity"}
        try:
            with self._client.stream("POST", self.endpoint, headers=headers, json=payload) as response:
                if response.status_code in (401, 403):
                    raise _error("MODEL_AUTH_FAILED")
                if response.status_code == 429:
                    raise _error("MODEL_RATE_LIMIT")
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
        if not isinstance(normalized_text, str) or not normalized_text.strip() or len(normalized_text) > MAX_INPUT_CHARS:
            raise _error("MODEL_INPUT_TOO_LARGE")
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
        locator_blocks = _locator_blocks(normalized_text)
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
