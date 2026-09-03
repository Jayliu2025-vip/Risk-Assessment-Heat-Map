import unittest
from dataclasses import fields

from desktop.models import (
    AnalysisTask,
    ConfirmedControl,
    ExtractedBlock,
    FindingDraft,
    ModelProfile,
    RiskDecision,
    ValidationError,
    score_or_none,
)
from tools.common import DIMS


class DesktopModelsTests(unittest.TestCase):
    def valid_payload(self):
        return {
            "finding_id": "F-001",
            "title": "采购审批缺少复核",
            "fact_summary": "抽样发现一笔采购缺少复核记录",
            "source_page": "12",
            "source_excerpt": "审批记录未见复核人签字",
            "matched_risk_id": "R001",
            "domain": "采购与外包",
            "likelihood": 3,
            "impact_scores": {dim: 2 for dim in DIMS},
            "rationale": "证据显示控制执行不充分",
            "needs_review": True,
        }

    def test_finding_draft_normalizes_dimensions_and_default_review(self):
        finding = FindingDraft.from_model("T001", self.valid_payload(), {"R001"})
        self.assertEqual(tuple(finding.impact_scores), tuple(DIMS))
        self.assertEqual(set(finding.impact_scores), set(DIMS))
        self.assertEqual(finding.review_status, "待确认")
        self.assertEqual(finding.task_id, "T001")
        self.assertEqual(finding.to_dict()["impact_scores"].keys(), finding.impact_scores.keys())

    def test_finding_rejects_unknown_domain_score_and_risk(self):
        for key, value in (("domain", "不存在"), ("likelihood", 8), ("matched_risk_id", "R999")):
            payload = self.valid_payload()
            payload[key] = value
            with self.assertRaises(ValidationError):
                FindingDraft.from_model("T001", payload, {"R001"})

    def test_score_strictness(self):
        for value in (True, False, 1.0, "3", 0, 6, "abc"):
            with self.assertRaises(ValidationError):
                score_or_none(value)
        self.assertIsNone(score_or_none(None))
        self.assertIsNone(score_or_none(""))
        self.assertIsNone(score_or_none("  "))
        self.assertEqual(score_or_none(3), 3)

    def test_finding_rejects_blank_text_and_unknown_impact_keys(self):
        for key in ("finding_id", "title", "fact_summary", "source_page", "source_excerpt", "rationale"):
            payload = self.valid_payload()
            payload[key] = "  "
            with self.assertRaises(ValidationError):
                FindingDraft.from_model("T001", payload, {"R001"})
        payload = self.valid_payload()
        payload["impact_scores"] = {**payload["impact_scores"], "imp_unknown": 3}
        with self.assertRaises(ValidationError):
            FindingDraft.from_model("T001", payload, {"R001"})

    def test_model_profile_url_and_bool_validation(self):
        ModelProfile("本地模型", "https://example.test", "model-a", True)
        for args in (("", "https://x", "m", True), ("n", "ftp://x", "m", True), ("n", "https://x", "", True), ("n", "https://x", "m", 1)):
            with self.assertRaises(ValidationError):
                ModelProfile(*args)

    def test_confirmed_control_validation(self):
        ConfirmedControl("双人复核", 4, True)
        for args in (("", 4, True), ("复核", 0, True), ("复核", 4.0, True), ("复核", 4, "是")):
            with self.assertRaises(ValidationError):
                ConfirmedControl(*args)

    def test_risk_decision_action_and_required_fields(self):
        base = dict(action="create", finding_ids=("F-001",), risk_id="R001", name="采购风险", domain="采购与外包", description="描述", owner_dept="采购部", period="2026", likelihood=3, impact_scores={dim: 2 for dim in DIMS}, rationale="理由", controls=(ConfirmedControl("复核", 4, True),))
        RiskDecision(**base)
        RiskDecision(action="exclude", finding_ids=())
        for action in ("bad", "create"):
            data = dict(base, action=action)
            if action == "create":
                data["finding_ids"] = ()
            with self.assertRaises(ValidationError):
                RiskDecision(**data)
        data = dict(base, action="merge", domain="不存在")
        with self.assertRaises(ValidationError):
            RiskDecision(**data)

    def test_exact_dataclass_fields(self):
        self.assertEqual([f.name for f in fields(AnalysisTask)], ["task_id", "file_name", "file_hash", "created_at", "status", "model_profile", "extraction_method"])
        self.assertEqual([f.name for f in fields(ExtractedBlock)], ["locator", "text", "method", "needs_review", "image_path"])


if __name__ == "__main__":
    unittest.main()
