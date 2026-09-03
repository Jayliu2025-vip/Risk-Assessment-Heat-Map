import json
import unittest
from dataclasses import MISSING, asdict, fields

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

    def test_finding_allows_blank_matched_risk_for_new_risk(self):
        payload = self.valid_payload()
        payload["matched_risk_id"] = "  "
        finding = FindingDraft.from_model("T001", payload, {"R001"})
        self.assertEqual(finding.matched_risk_id, "")

    def test_finding_needs_review_is_required_but_review_status_defaults(self):
        payload = self.valid_payload()
        del payload["needs_review"]
        with self.assertRaises(ValidationError):
            FindingDraft.from_model("T001", payload, {"R001"})
        finding = FindingDraft.from_model("T001", self.valid_payload(), {"R001"})
        self.assertEqual(finding.review_status, "待确认")

    def test_model_cannot_self_approve_finding(self):
        for status in ("已接受", "已排除"):
            payload = self.valid_payload()
            payload["review_status"] = status
            finding = FindingDraft.from_model("T001", payload, {"R001"})
            self.assertEqual(finding.review_status, "待确认")

    def test_analysis_task_accepts_leaf_filename_only_and_normalizes(self):
        task = AnalysisTask(" T1 ", " report.pdf ", " h ", " now ", "提取中", " profile ", " text ")
        self.assertEqual((task.task_id, task.file_name, task.file_hash, task.created_at, task.model_profile, task.extraction_method), ("T1", "report.pdf", "h", "now", "profile", "text"))
        for name in ("C:\\reports\\report.pdf", "C:/reports/report.pdf", "/tmp/report.pdf", "..", ".", "a/b.pdf", "a\\b.pdf"):
            with self.assertRaises(ValidationError):
                AnalysisTask("T1", name, "h", "now", "提取中", "p", "text")

    def test_json_roundtrip_all_dataclasses_and_decision_actions(self):
        task = AnalysisTask("T1", "r.pdf", "h", "now", "提取中", "p", "text")
        block = ExtractedBlock(" p1 ", " text ", "text", image_path=" image.png ")
        finding = FindingDraft.from_model("T1", self.valid_payload(), {"R001"})
        profile = ModelProfile(" p ", "https://example.test", " m ", True)
        control = ConfirmedControl(" c ", 4, True)
        risk = RiskDecision(action="create", finding_ids=("F1",), risk_id="R1", name="n", domain="采购与外包", description="d", owner_dept="o", period="p", likelihood=3, impact_scores={dim: 2 for dim in DIMS}, rationale="r", controls=(control,))
        for value in (task, block, finding, profile, control, risk, RiskDecision(action="exclude", finding_ids=())):
            json.dumps(asdict(value), ensure_ascii=False)
        self.assertEqual(block.locator, "p1")
        self.assertEqual(block.image_path, "image.png")
        self.assertEqual(profile.model, "m")
        self.assertEqual(control.description, "c")

    def test_extracted_image_path_and_exclude_decision_are_strict(self):
        with self.assertRaises(ValidationError):
            ExtractedBlock("p", "t", "text", image_path=" ")
        with self.assertRaises(ValidationError):
            ExtractedBlock("p", "t", "text", image_path=3)
        control = ConfirmedControl("c", 3, False)
        for kwargs in ({"risk_id": "R1"}, {"domain": "采购与外包"}, {"controls": (control,)}):
            with self.assertRaises(ValidationError):
                RiskDecision(action="exclude", finding_ids=(), **kwargs)

    def test_risk_decision_normalizes_ids_rejects_duplicates_and_types(self):
        with self.assertRaises(ValidationError):
            RiskDecision(action="exclude", finding_ids=(" F1 ", "F1"))
        with self.assertRaises(ValidationError):
            RiskDecision(action="exclude", finding_ids=(1,))
        decision = RiskDecision(action="exclude", finding_ids=(" F1 ",))
        self.assertEqual(decision.finding_ids, ("F1",))
        for kwargs in ({"risk_id": 1}, {"name": 1}, {"description": 1}, {"owner_dept": 1}, {"period": 1}, {"rationale": 1}, {"likelihood": "3"}, {"impact_scores": []}):
            with self.assertRaises(ValidationError):
                RiskDecision(action="exclude", finding_ids=(), **kwargs)

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

    def test_risk_decision_normalizes_remediation_status(self):
        base = dict(action="create", finding_ids=("F-001",), name="采购风险", domain="采购与外包",
                    description="描述", owner_dept="采购部", period="2026", likelihood=3,
                    impact_scores={dim: 2 for dim in DIMS}, rationale="理由")
        self.assertEqual(RiskDecision(**base).remediation_status, "未确认")
        self.assertEqual(RiskDecision(**base, remediation_status=" 整改中 ").remediation_status, "整改中")
        with self.assertRaises(ValidationError):
            RiskDecision(**base, remediation_status="已关闭")
        with self.assertRaises(ValidationError):
            RiskDecision(action="exclude", finding_ids=("F-001",), remediation_status="不适用")

    def test_finding_merge_links_are_strict_and_json_friendly(self):
        payload = self.valid_payload()
        finding = FindingDraft.from_model("T001", payload, {"R001"})
        merged = FindingDraft(**{**asdict(finding), "merged_finding_ids": [" F-002 ", "F-003"]})
        secondary = FindingDraft(**{**asdict(finding), "finding_id": "F-002", "merged_into": " F-001 "})
        self.assertEqual(merged.merged_finding_ids, ("F-002", "F-003"))
        self.assertEqual(secondary.merged_into, "F-001")
        json.dumps(asdict(merged), ensure_ascii=False)
        for changes in ({"merged_finding_ids": ["F-002", "F-002"]},
                        {"merged_finding_ids": ["F-001"]},
                        {"merged_into": "F-001", "merged_finding_ids": ["F-003"]}):
            with self.assertRaises(ValidationError):
                FindingDraft(**{**asdict(finding), **changes})

    def test_exact_dataclass_fields(self):
        self.assertEqual([f.name for f in fields(AnalysisTask)], ["task_id", "file_name", "file_hash", "created_at", "status", "model_profile", "extraction_method"])
        self.assertEqual([f.name for f in fields(ExtractedBlock)], ["locator", "text", "method", "needs_review", "image_path"])
        finding_fields = fields(FindingDraft)
        self.assertEqual(finding_fields[-4].name, "needs_review")
        self.assertIs(finding_fields[-4].default, MISSING)
        self.assertEqual([field.name for field in finding_fields[-3:]], ["review_status", "merged_finding_ids", "merged_into"])
        self.assertEqual(finding_fields[-3].default, "待确认")


if __name__ == "__main__":
    unittest.main()
