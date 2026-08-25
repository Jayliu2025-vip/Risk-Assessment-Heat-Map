# -*- coding: utf-8 -*-
"""v1.2 发布物口径与网页默认配置一致性测试。"""

import json
import re
import subprocess
import unittest
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class ReleaseConsistencyTests(unittest.TestCase):
    def test_current_user_copy_does_not_contain_legacy_wording(self):
        forbidden_by_file = {
            "README.md": [
                "21 项", "6 领域 16 风险", "24 项评分模型一致性测试",
                "Σ(wᵢ×维度ᵢ), floor × 最高维度分",
            ],
            "docs/使用手册.md": [
                "五维", "六项打分", "16 条", "6 个领域", "21 项",
                "24 项评分模型一致性测试", "B3:B7", "B12:B15", "A25:G38",
                "G 列变红", "I2:I8", "登记册 Q 列", "登记册 M~R 列",
                "A~L 列", "G~L 打分", "登记册 M 列", "$A$26:$F$38",
                "五个权重输入框", "参数配置页 B8 合计格", "把五个权重",
                "30%+25%+15%+15%+15%",
            ],
            "tools/build_excel.py": ["五维", "六项打分", "B12:B15"],
            "tools/common.py": ["Σ(wᵢ×维度ᵢ), floor × MAX(各维度)"],
            "tools/generate_report.py": ["五维加权"],
            "tools/sample_data.py": ["6 领域 × 16 项风险"],
            "tests/test_scoring.py": ["22.00 → 18.70", "12.00 → 10.20"],
            "web/risk_heatmap.html": ["五维影响权重", "五维加权"],
        }
        for relative_path, forbidden_terms in forbidden_by_file.items():
            content = read_text(relative_path)
            for term in forbidden_terms:
                with self.subTest(file=relative_path, term=term):
                    self.assertNotIn(term, content)

    def test_release_documentation_uses_current_ranges_and_dimensions(self):
        readme = read_text("README.md")
        manual = read_text("docs/使用手册.md")
        sample_source = read_text("tools/sample_data.py")

        self.assertIn("战略影响/数据安全/健康安全", readme)
        self.assertIn("每期 24 条", readme)
        self.assertIn("4 大类 12 领域", readme)
        self.assertIn("每期 24 条", sample_source)
        self.assertIn("4 大类 12 领域", sample_source)
        for expected in (
            "B3:B10",
            "B14:B17",
            "A25:J38",
            "J 列变红",
            "I1:I8",
            "P~Z",
            "登记册 T 列",
            "登记册 P~U 列",
            "$A$26:$I$38",
            "24 项评分模型测试 + 发布一致性测试",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, manual)
        self.assertIn("24 项评分模型测试 + 发布一致性测试", readme)
        self.assertIn("Σ(wᵢ×维度ᵢ)/Σ(已评分维度的wᵢ)", readme)
        self.assertIn("八个权重输入框", manual)
        self.assertIn("参数配置页 B11 合计格", manual)
        self.assertIn("25%+20%+12%+10%+10%+10%+8%+5%", manual)
        self.assertIn(
            "| 领域 | 经济 | 合规 | 运营 | 声誉 | 舞弊 | 战略 | 数据 | 健康安全 |",
            manual,
        )

    def test_normalize_config_migrates_legacy_rows_and_rejects_bad_fields(self):
        html = read_text("web/risk_heatmap.html")
        config_code = html[html.index("const DIMS ="):html.index("const LS_KEY")]
        script = config_code + r'''
const migrated=normalizeConfig({
  weights:{imp_financial:.30,imp_compliance:.25,imp_operation:.15,imp_reputation:.15,imp_fraud:.15},
  domain_weights:{Legacy:{imp_financial:.40,imp_compliance:.25,imp_operation:.10,imp_reputation:.15,imp_fraud:.10}},
  impact_floor_factor:"not-a-number",
  reduction_map:{"2":Infinity,"3":.5},
  thresholds:{extreme:NaN,high:13},
  ref_reduction:Infinity,
  unknown:"must-not-leak"
});
console.log(JSON.stringify(migrated));
'''
        completed = subprocess.run(
            ["node", "-"], input=script, text=True, capture_output=True, check=True
        )
        config = json.loads(completed.stdout)
        canonical_fields = {
            "version", "weights", "domain_weights", "impact_floor_factor",
            "reduction_map", "thresholds", "ref_reduction",
        }
        dimensions = {
            "imp_financial", "imp_compliance", "imp_operation", "imp_reputation",
            "imp_fraud", "imp_strategy", "imp_data", "imp_hse",
        }
        self.assertEqual(set(config), canonical_fields)
        self.assertEqual(config["version"], "1.1")
        self.assertEqual(config["impact_floor_factor"], 0.75)
        self.assertEqual(config["ref_reduction"], 0.4)
        self.assertEqual(config["reduction_map"]["2"], 0.15)
        self.assertEqual(config["thresholds"]["extreme"], 20)
        for row in [config["weights"], *config["domain_weights"].values()]:
            self.assertEqual(set(row), dimensions)
            self.assertAlmostEqual(sum(row.values()), 1.0)
        self.assertAlmostEqual(config["weights"]["imp_strategy"], 0.10)
        self.assertAlmostEqual(config["weights"]["imp_data"], 0.08)
        self.assertAlmostEqual(config["weights"]["imp_hse"], 0.05)

    def test_import_config_replaces_previous_normalized_config(self):
        html = read_text("web/risk_heatmap.html")
        body = html.split("function importConfig(file){", 1)[1].split(
            "function csvEscape", 1
        )[0]
        self.assertIn("state.config=normalizeConfig(j)", body)
        self.assertNotIn("domainWeights", body)

    def test_edit_risk_restores_likelihood_input(self):
        html = read_text("web/risk_heatmap.html")
        body = html.split("function editRisk(rid){", 1)[1].split(
            "function delRisk", 1
        )[0]
        self.assertIn('$("f-lik").value=r.likelihood', body)

    def test_workbook_layout_and_period_dropdowns_match_current_model(self):
        workbook = load_workbook(ROOT / "audit_risk_register.xlsx", data_only=False)
        config = workbook["参数配置"]
        self.assertEqual(config["I25"].value, "健康安全")
        self.assertEqual(config["J25"].value, "行合计")
        self.assertEqual(
            [config.cell(row=row, column=9).value for row in range(1, 5)],
            ["评估期间清单", "全部", "2025H2", "2026H1"],
        )

        register = workbook["风险登记册"]
        expected_headers = [
            "综合影响",
            "固有风险",
            "关键控制分",
            "折减系数",
            "剩余风险",
            "剩余等级",
            "影响档\n(辅助)",
            "固有点\n(辅助)",
            "建议审计频次",
            "控制挽回率",
            "打分依据",
        ]
        self.assertEqual(
            [register.cell(row=3, column=column).value for column in range(16, 27)],
            expected_headers,
        )

        dropdown_formulas = {
            sheet_name: {
                validation.formula1
                for validation in workbook[sheet_name].data_validations.dataValidation
            }
            for sheet_name in ("风险登记册", "控制措施表", "热力图")
        }
        self.assertIn("=参数配置!$I$3:$I$8", dropdown_formulas["风险登记册"])
        self.assertIn("=参数配置!$I$3:$I$8", dropdown_formulas["控制措施表"])
        self.assertIn("=参数配置!$I$2:$I$8", dropdown_formulas["热力图"])

    def test_workbook_recovery_formula_guards_blank_and_zero_inherent_risk(self):
        workbook = load_workbook(ROOT / "audit_risk_register.xlsx", data_only=False)
        self.assertEqual(
            workbook["风险登记册"]["Y4"].value,
            '=IF($A4="","",IF(OR(Q4="",Q4=0),"",(Q4-T4)/Q4))',
        )

    def test_workbook_priority_ranking_uses_residual_score(self):
        workbook = load_workbook(ROOT / "audit_risk_register.xlsx", data_only=False)
        summary = workbook["汇总与优先级"]
        rank_formula = next(
            cell.value
            for cell in summary["A"]
            if isinstance(cell.value, str) and "COUNTIFS" in cell.value
        )
        self.assertIn("风险登记册!$T$4:$T$203", rank_formula)
        self.assertNotIn("风险登记册!$Q$4:$Q$203", rank_formula)

    def test_web_default_config_has_all_eight_weights_summing_to_one(self):
        html = read_text("web/risk_heatmap.html")
        match = re.search(
            r"const\s+DEFAULT_CFG\s*=\s*\{.*?weights\s*:\s*\{([^}]*)\}",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "未找到 DEFAULT_CFG.weights")
        weights = {
            key: float(value)
            for key, value in re.findall(
                r"(imp_[a-z]+)\s*:\s*(\d*\.?\d+)", match.group(1)
            )
        }
        expected_dimensions = {
            "imp_financial",
            "imp_compliance",
            "imp_operation",
            "imp_reputation",
            "imp_fraud",
            "imp_strategy",
            "imp_data",
            "imp_hse",
        }
        self.assertEqual(set(weights), expected_dimensions)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_web_uses_canonical_impact_floor_factor(self):
        html = read_text("web/risk_heatmap.html")
        self.assertRegex(html, r"impact_floor_factor\s*:\s*\.75")
        self.assertRegex(html, r"cfg\.impact_floor_factor")

    def test_embedded_sample_config_matches_exported_config(self):
        exported = json.loads(read_text("data/export/config.json"))
        script = read_text("web/sample_data.js").strip()
        prefix = "window.SAMPLE_DATA = "
        self.assertTrue(script.startswith(prefix))
        embedded = json.loads(script[len(prefix):].removesuffix(";"))
        self.assertEqual(embedded["config"], exported)


if __name__ == "__main__":
    unittest.main()
