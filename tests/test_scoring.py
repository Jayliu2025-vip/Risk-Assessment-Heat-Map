# -*- coding: utf-8 -*-
"""评分模型一致性测试：python -m unittest discover -s tests -v
   （亦兼容 pytest tests/）

金标准数值与 tools/sample_data.py 内置示例绑定：
R012 2026H1 = 22.25 → 18.91（八维影响 I=4.45，EDR 关键控制 2 分，折减 15%）
R013 2026H1 = 15.00 → 12.75（战略影响 5 分触发下限，I = 0.75 × 5 = 3.75）
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools"))
from common import (DEFAULT_CONFIG, DIMS, assess_all, composite_impact,
                    effective_weights, level_of, load_config, load_dataset,
                    reduction_of, residual_score, validate_config,
                    weakest_control_score)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mk_risk(lik=3, fin=3, comp=3, ops=3, rep=3, fraud=3, strat=3, data=3,
            hse=3, domain="资金活动"):
    return {"risk_id": "RX", "name": "测试", "domain": domain,
            "description": "", "owner_dept": "", "period": "T",
            "likelihood": lik, "imp_financial": fin, "imp_compliance": comp,
            "imp_operation": ops, "imp_reputation": rep, "imp_fraud": fraud,
            "imp_strategy": strat, "imp_data": data, "imp_hse": hse}


class ImpactTests(unittest.TestCase):
    def test_linear_weighted(self):
        r = mk_risk(fin=4, comp=4, ops=2, rep=3, fraud=4, domain="资金活动")
        # 资金活动权重 .32/.20/.08/.12/.08/.10/.06/.04
        self.assertEqual(composite_impact(r, DEFAULT_CONFIG), 3.52)

    def test_na_dimension_renormalized(self):
        r = mk_risk(fin=4, comp=None, ops=None, rep=None, fraud=None,
                    strat=None, data=None, hse=None)
        # 仅经济损失打分：权重归一化后 I 恰为该维度分值
        self.assertEqual(composite_impact(r, DEFAULT_CONFIG), 4.0)

    def test_all_dims_blank_returns_none(self):
        r = mk_risk(fin=None, comp=None, ops=None, rep=None, fraud=None,
                    strat=None, data=None, hse=None)
        self.assertIsNone(composite_impact(r, DEFAULT_CONFIG))

    def test_floor_dominates(self):
        r = mk_risk(fin=1, comp=1, ops=1, rep=1, fraud=5)  # 合规一票否决型
        i = composite_impact(r, DEFAULT_CONFIG)
        self.assertGreaterEqual(i, 0.75 * 5 - 1e-9)   # 下限 3.75
        self.assertLessEqual(i, 5)

    def test_floor_boundary(self):
        r = mk_risk(fin=1, comp=1, ops=4, rep=1, fraud=1, strat=1, data=1, hse=1)
        # 线性加权仅 1.24，一票否决下限 0.75×4=3.00 生效
        self.assertEqual(composite_impact(r, DEFAULT_CONFIG), 3.0)

    def test_domain_weights_used(self):
        r = mk_risk(fin=5, comp=1, ops=1, rep=1, fraud=1, domain="资产管理")
        w = effective_weights(r, DEFAULT_CONFIG)
        self.assertEqual(w["imp_financial"], 0.32)
        self.assertEqual(w["imp_hse"], 0.08)

    def test_domain_fallback(self):
        r = mk_risk(domain="未收录领域")
        w = effective_weights(r, DEFAULT_CONFIG)
        self.assertEqual(w, DEFAULT_CONFIG["weights"])


class ControlTests(unittest.TestCase):
    def test_key_controls_only(self):
        ctrls = [{"risk_id": "R", "period": "T", "score": 5, "key": "否"},
                 {"risk_id": "R", "period": "T", "score": 2, "key": "是"}]
        self.assertEqual(weakest_control_score(ctrls, "R", "T"), 2)

    def test_fallback_when_no_key(self):
        ctrls = [{"risk_id": "R", "period": "T", "score": 4, "key": "否"},
                 {"risk_id": "R", "period": "T", "score": 3, "key": "否"}]
        self.assertEqual(weakest_control_score(ctrls, "R", "T"), 3)

    def test_none_when_no_controls(self):
        self.assertIsNone(weakest_control_score([], "R", "T"))

    def test_period_mismatch_ignored(self):
        ctrls = [{"risk_id": "R", "period": "其他期", "score": 1, "key": "是"}]
        self.assertIsNone(weakest_control_score(ctrls, "R", "T"))


class ResidualLevelTests(unittest.TestCase):
    def test_reduction_map(self):
        self.assertEqual(reduction_of(1, DEFAULT_CONFIG), 0.0)
        self.assertEqual(reduction_of(3, DEFAULT_CONFIG), 0.40)
        self.assertEqual(reduction_of(None, DEFAULT_CONFIG), 0.0)

    def test_residual(self):
        self.assertEqual(residual_score(20, 3, DEFAULT_CONFIG), 12.0)
        self.assertEqual(residual_score(10, None, DEFAULT_CONFIG), 10.0)

    def test_level_boundaries(self):
        lv = lambda v: level_of(v, DEFAULT_CONFIG)
        self.assertEqual(lv(20), "extreme")
        self.assertEqual(lv(19.99), "high")
        self.assertEqual(lv(12), "high")
        self.assertEqual(lv(11.99), "medium")
        self.assertEqual(lv(6), "medium")
        self.assertEqual(lv(3), "low")
        self.assertEqual(lv(2.99), "minimal")

    def test_recovery(self):
        out = assess_all([mk_risk(lik=4)], [], DEFAULT_CONFIG)
        a = out[0]
        self.assertAlmostEqual(a["recovery"], 0.0)  # 无控制点 → 挽回率 0


class ConfigTests(unittest.TestCase):
    def test_domain_taxonomy(self):
        from common import DOMAIN_CATEGORY, DEFAULT_CONFIG, DOMAINS
        for d in DOMAINS:
            self.assertIn(d, DEFAULT_CONFIG["domain_weights"])
            self.assertIn(d, DOMAIN_CATEGORY)
            self.assertAlmostEqual(
                sum(DEFAULT_CONFIG["domain_weights"][d].values()), 1.0, places=6)

    def test_bad_weight_sum_raises(self):
        import copy
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["weights"]["imp_financial"] = 0.5
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_bad_domain_row_raises(self):
        import copy
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["domain_weights"]["信息系统"]["imp_operation"] = 0.9
        with self.assertRaises(ValueError):
            validate_config(cfg)

    def test_floor_out_of_range(self):
        import copy
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["impact_floor_factor"] = 1.5
        with self.assertRaises(ValueError):
            validate_config(cfg)


class GoldenDatasetTests(unittest.TestCase):
    """锁定三件套共用的金标准数值（与网页端/Excel 公式交叉核对过）。"""

    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.risks, cls.ctrls = load_dataset(
            os.path.join(ROOT, "data", "export", "2026H1"))
        cls.assessed = {a["risk_id"]: a
                        for a in assess_all(cls.risks, cls.ctrls, cls.cfg)}

    def test_r012_top_risk(self):
        a = self.assessed["R012"]
        self.assertEqual((a["impact"], a["inherent"],
                          a["weakest_control"], a["residual"]),
                         (4.45, 22.25, 2, 18.91))
        self.assertEqual(a["residual_level"], "high")
        self.assertAlmostEqual(a["recovery"], 0.1501, places=3)

    def test_r013_floor_applied(self):
        a = self.assessed["R013"]
        # 数据安全/健康安全留空 → 权重重归一化；战略 5 触发一票否决下限 3.75
        self.assertEqual((a["impact"], a["inherent"], a["residual"]),
                         (3.75, 15.00, 12.75))
        self.assertEqual(a["residual_level"], "high")

    def test_r004_key_control(self):
        a = self.assessed["R004"]
        self.assertEqual((a["weakest_control"], a["residual"], a["recovery"]),
                         (4, 6.75, 0.55))

    def test_prev_period_r012(self):
        _, risks, ctrls = load_dataset(
            os.path.join(ROOT, "data", "export", "2025H2"))
        a = {x["risk_id"]: x for x in assess_all(risks, ctrls, self.cfg)}["R012"]
        # 八维权重（信息系统）下 I=4.45，固有 17.80，弱控制 2 → 15.13
        self.assertEqual((a["impact"], a["inherent"], a["residual"]),
                         (4.45, 17.80, 15.13))

    def test_rationale_field_roundtrip(self):
        self.assertTrue(all(r.get("rationale") for r in self.risks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
