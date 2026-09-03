"""Contract tests for the local OpenAI-compatible report analysis client."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

import desktop.model_client as model_client
from desktop.model_client import ModelClient, ModelError, normalize_endpoint
from desktop.models import ModelProfile
from tests.fakes.openai_server import FakeOpenAIServer
from tools.common import DIMS


def profile(base_url: str, vision: bool = False) -> ModelProfile:
    return ModelProfile("本地测试模型", base_url, "synthetic-model", vision)


def catalog() -> list[dict[str, str]]:
    return [{"risk_id": "R003", "name": "虚构资金支付风险", "domain": "资金活动", "description": "仅测试使用"}]


class ModelClientTests(unittest.TestCase):
    def test_success_sends_safe_rubric_and_returns_pending_drafts(self):
        with FakeOpenAIServer() as server:
            with ModelClient(profile(server.base_url), "secret-key") as client:
                drafts = client.analyze("T-1", "虚构付款审批记录；虚构新增风险线索；虚构复核缺失记录", catalog(), [])
        self.assertEqual(len(drafts), 3)
        self.assertTrue(all(d.review_status == "待确认" for d in drafts))
        system = server.requests[0]["messages"][0]["content"]
        self.assertIn("不可信", system)
        self.assertIn("不得执行工具、网络、链接或文件操作", system)
        self.assertIn("历史发现事实", system)
        self.assertIn("当前控制有效性", system)
        self.assertIn("load_scoring_anchors", system)
        self.assertIn("finding_id", system)
        self.assertEqual(server._server.server_address[0], "127.0.0.1")
        self.assertFalse(server.thread.is_alive())

    def test_api_key_is_header_only_and_never_in_body_or_error(self):
        secret = "top-secret-never-body"
        with FakeOpenAIServer(mode="auth_failed") as server:
            with ModelClient(profile(server.base_url), secret) as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_AUTH_FAILED")
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, repr(raised.exception))
        self.assertNotIn(secret, json.dumps(server.requests, ensure_ascii=False))

    def test_endpoint_normalization_and_rejections_are_exact(self):
        self.assertEqual(normalize_endpoint("https://localhost/v1"), "https://localhost/v1/chat/completions")
        self.assertEqual(normalize_endpoint("http://127.0.0.1"), "http://127.0.0.1/v1/chat/completions")
        for url in ("ftp://localhost", "https://user:pass@localhost", "https://localhost/", "https://localhost/v1/x", "https://localhost?q=x", "https://localhost#x"):
            with self.assertRaises(ModelError) as raised:
                normalize_endpoint(url)
            self.assertEqual(raised.exception.code, "MODEL_CONNECTION_FAILED")
            self.assertNotIn("pass", str(raised.exception))

    def test_error_codes_for_transport_and_response_failures(self):
        cases = (("invalid_json", "MODEL_JSON_INVALID"), ("auth_failed", "MODEL_AUTH_FAILED"), ("rate_limit", "MODEL_RATE_LIMIT"), ("oversized_response", "MODEL_RESPONSE_TOO_LARGE"))
        for mode, code in cases:
            with self.subTest(mode=mode), FakeOpenAIServer(mode=mode) as server:
                with ModelClient(profile(server.base_url), "k") as client:
                    with self.assertRaises(ModelError) as raised:
                        client.analyze("T-1", "虚构付款审批记录", catalog(), [])
                self.assertEqual(raised.exception.code, code)
        with ModelClient(profile("http://127.0.0.1:1"), "k") as client:
            with self.assertRaises(ModelError) as raised:
                client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_CONNECTION_FAILED")

        with FakeOpenAIServer(mode="auth") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_AUTH_FAILED")
        with FakeOpenAIServer(mode="oversized") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_RESPONSE_TOO_LARGE")

    def test_timeout_maps_to_safe_code(self):
        with FakeOpenAIServer(mode="timeout") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                client._client.timeout = httpx.Timeout(0.01, connect=0.01)
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_TIMEOUT")

    def test_vision_content_is_opt_in_and_text_mode_forces_review(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "synthetic.png"
            image.write_bytes(b"synthetic-png")
            with FakeOpenAIServer() as server:
                with ModelClient(profile(server.base_url, vision=True), "k") as client:
                    client.analyze("T-1", "虚构付款审批记录；虚构新增风险线索；虚构复核缺失记录", catalog(), [image])
                vision_payload = server.requests[-1]
            self.assertIn("data:image/png;base64,", json.dumps(vision_payload, ensure_ascii=False))
            with FakeOpenAIServer() as server:
                with ModelClient(profile(server.base_url, vision=False), "k") as client:
                    drafts = client.analyze("T-1", "虚构付款审批记录；虚构新增风险线索；虚构复核缺失记录", catalog(), [image])
                text_payload = server.requests[-1]
            self.assertNotIn("base64", json.dumps(text_payload, ensure_ascii=False))
            self.assertTrue(all(item.needs_review for item in drafts))

    def test_vision_grounding_still_requires_review_for_unmatched_excerpt(self):
        payload = {"findings": [{"finding_id": "F-vision", "title": "虚构", "fact_summary": "虚构", "source_page": "1", "source_excerpt": "完全不存在的原文", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "虚构", "needs_review": False}]}
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "synthetic.png"
            image.write_bytes(b"synthetic-png")
            with FakeOpenAIServer(content=json.dumps(payload, ensure_ascii=False)) as server:
                with ModelClient(profile(server.base_url, vision=True), "k") as client:
                    findings = client.analyze("T-1", "虚构付款审批记录", catalog(), [image])
        self.assertTrue(findings[0].needs_review)

    def test_fenced_json_is_allowed_but_prose_is_rejected(self):
        response = json.dumps({"findings": []}, ensure_ascii=False)
        with FakeOpenAIServer(content=f"```json\n{response}\n```") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                self.assertEqual(client.analyze("T-1", "虚构文本", catalog(), []), [])
        with FakeOpenAIServer(content=f"说明：\n{response}") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构文本", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_OUTPUT_INVALID")

    def test_invalid_model_finding_and_duplicate_ids_are_rejected(self):
        base = {"findings": [{"finding_id": "F1", "title": "虚构", "fact_summary": "虚构", "source_page": "1", "source_excerpt": "虚构文本", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "虚构", "needs_review": False}]}
        for field, value in (("domain", "未知"), ("likelihood", 9), ("matched_risk_id", "R999")):
            payload = json.loads(json.dumps(base, ensure_ascii=False))
            payload["findings"][0][field] = value
            with self.subTest(field=field), FakeOpenAIServer(content=json.dumps(payload, ensure_ascii=False)) as server:
                with ModelClient(profile(server.base_url), "k") as client:
                    with self.assertRaises(ModelError) as raised:
                        client.analyze("T-1", "虚构文本", catalog(), [])
                self.assertEqual(raised.exception.code, "MODEL_OUTPUT_INVALID")
        duplicate = {"findings": [base["findings"][0], base["findings"][0]]}
        with FakeOpenAIServer(content=json.dumps(duplicate, ensure_ascii=False)) as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构文本", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_OUTPUT_INVALID")

    def test_extra_model_finding_fields_are_rejected(self):
        payload = {"findings": [{"finding_id": "F1", "title": "虚构", "fact_summary": "虚构", "source_page": "1", "source_excerpt": "虚构文本", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "虚构", "needs_review": False, "final_risk": 5}]}
        with FakeOpenAIServer(content=json.dumps(payload, ensure_ascii=False)) as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构文本", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_OUTPUT_INVALID")

    def test_unsupported_source_excerpt_requires_review(self):
        with FakeOpenAIServer() as server:
            with ModelClient(profile(server.base_url), "k") as client:
                drafts = client.analyze("T-1", "完全不同的虚构文本", catalog(), [])
        self.assertTrue(all(draft.needs_review for draft in drafts))

    def test_input_risk_and_image_caps_are_checked_without_large_allocations(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "synthetic.png"
            image.write_bytes(b"xx")
            with patch.object(model_client, "MAX_INPUT_CHARS", 3), patch.object(model_client, "MAX_RISKS", 1), patch.object(model_client, "MAX_VISION_IMAGES", 1), patch.object(model_client, "MAX_VISION_BYTES", 1):
                with FakeOpenAIServer() as server:
                    with ModelClient(profile(server.base_url, vision=True), "k") as client:
                        for text, risks, images in (("", catalog(), []), ("xxxx", catalog(), []), ("x", catalog() * 2, []), ("x", catalog(), [image])):
                            with self.assertRaises(ModelError) as raised:
                                client.analyze("T-1", text, risks, images)
                            self.assertEqual(raised.exception.code, "MODEL_INPUT_TOO_LARGE")

    def test_risk_and_image_generators_stop_at_cap_plus_one(self):
        def guarded(value, limit):
            for _ in range(limit + 1):
                yield value
            raise AssertionError("iterable consumed beyond cap+1")

        with ModelClient(profile("http://127.0.0.1:1"), "k") as client:
            with self.assertRaises(ModelError) as raised:
                client.analyze("T-1", "虚构付款审批记录", guarded(catalog()[0], model_client.MAX_RISKS), [])
            self.assertEqual(raised.exception.code, "MODEL_INPUT_TOO_LARGE")
            with self.assertRaises(ModelError) as raised:
                client.analyze("T-1", "虚构付款审批记录", [], guarded("missing.png", model_client.MAX_VISION_IMAGES))
            self.assertEqual(raised.exception.code, "MODEL_INPUT_TOO_LARGE")

    def test_more_than_ten_images_is_rejected(self):
        with ModelClient(profile("http://127.0.0.1:1"), "k") as client:
            with self.assertRaises(ModelError) as raised:
                client.analyze("T-1", "虚构付款审批记录", catalog(), ["missing.png"] * 11)
        self.assertEqual(raised.exception.code, "MODEL_INPUT_TOO_LARGE")

    def test_more_than_two_hundred_findings_is_rejected(self):
        finding = {"finding_id": "F-1", "title": "虚构", "fact_summary": "虚构", "source_page": "1", "source_excerpt": "虚构付款审批记录", "matched_risk_id": "R003", "domain": "资金活动", "likelihood": 3, "impact_scores": {dim: 2 for dim in DIMS}, "rationale": "虚构", "needs_review": False}
        payload = json.dumps({"findings": [dict(finding, finding_id=f"F-{index}") for index in range(201)]}, ensure_ascii=False)
        with FakeOpenAIServer(content=payload) as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_OUTPUT_INVALID")

    def test_streamed_response_without_content_length_is_bounded(self):
        with FakeOpenAIServer(mode="streamed_oversized") as server:
            with patch.object(model_client, "MAX_RESPONSE_BYTES", 8):
                with ModelClient(profile(server.base_url), "k") as client:
                    with self.assertRaises(ModelError) as raised:
                        client.analyze("T-1", "虚构付款审批记录", catalog(), [])
        self.assertEqual(raised.exception.code, "MODEL_RESPONSE_TOO_LARGE")

    def test_test_connection_requires_ok(self):
        with FakeOpenAIServer(content="OK") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                self.assertTrue(client.test_connection())
        with FakeOpenAIServer(content="NO") as server:
            with ModelClient(profile(server.base_url), "k") as client:
                with self.assertRaises(ModelError) as raised:
                    client.test_connection()
        self.assertEqual(raised.exception.code, "MODEL_OUTPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
