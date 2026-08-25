# -*- coding: utf-8 -*-
"""共享评分模型：Excel 导出脚本与 Python 报告脚本共用，保证三件套数值一致。

公式体系（v1.1，含一票否决下限 / 分领域权重 / 关键控制短板 / 控制挽回率）：
    综合影响 I = max( Σ(wᵢ×维度ᵢ)/Σ(已评分维度的wᵢ), floor × MAX(已评分维度) )
                                                                    ∈ [1, 5]
                 wᵢ 取该风险所属领域的权重行，未配置领域回退全领域默认
    固有风险   = 可能性 L × I                                ∈ [1, 25]
    控制分     = MIN(关键控制点得分)（无关键标记 → 退回全部控制点取 MIN）
    剩余风险   = 固有 × (1 − 折减系数[控制分])                ∈ [0, 25]
    控制挽回率 = (固有 − 剩余) / 固有
    等级       = 五档可调阈值：极高/高/中/低/极低
"""
import csv
import json
import os

DIMS = ["imp_financial", "imp_compliance", "imp_operation", "imp_reputation",
        "imp_fraud", "imp_strategy", "imp_data", "imp_hse"]
DIM_LABELS = {
    "imp_financial": "经济损失",
    "imp_compliance": "合规法律",
    "imp_operation": "运营中断",
    "imp_reputation": "声誉舆情",
    "imp_fraud": "舞弊风险",
    "imp_strategy": "战略影响",
    "imp_data": "数据安全",
    "imp_hse": "健康安全",
}
RISK_FIELDS = ["risk_id", "name", "domain", "description", "owner_dept",
               "period", "likelihood"] + DIMS + ["rationale"]
CONTROL_FIELDS = ["control_id", "risk_id", "period", "description", "score", "key"]

# 风险领域体系：对齐《企业内部控制应用指引》（18 项业务循环归并）
# 与《中央企业全面风险管理指引》风险大类（战略/财务/运营/合规）
DOMAINS = ["战略与投资", "治理与决策", "资金活动", "财务报告与税务", "资产管理",
           "采购与外包", "合同管理", "工程项目", "人力资源", "信息系统",
           "合规与法律", "安全环保"]
DOMAIN_CATEGORY = {
    "战略与投资": "战略与治理", "治理与决策": "战略与治理",
    "资金活动": "财务", "财务报告与税务": "财务", "资产管理": "财务",
    "采购与外包": "运营", "合同管理": "运营", "工程项目": "运营",
    "人力资源": "运营", "信息系统": "运营",
    "合规与法律": "合规与安全", "安全环保": "合规与安全",
}
# 大类展示顺序
CATEGORY_ORDER = ["战略与治理", "财务", "运营", "合规与安全"]

DEFAULT_CONFIG = {
    "version": "1.1",
    "weights": {
        "imp_financial": 0.25,
        "imp_compliance": 0.20,
        "imp_operation": 0.12,
        "imp_reputation": 0.10,
        "imp_fraud": 0.10,
        "imp_strategy": 0.10,
        "imp_data": 0.08,
        "imp_hse": 0.05,
    },
    "domain_weights": {
        "战略与投资": {"imp_financial": 0.20, "imp_compliance": 0.10, "imp_operation": 0.20,
                    "imp_reputation": 0.20, "imp_fraud": 0.05, "imp_strategy": 0.20,
                    "imp_data": 0.03, "imp_hse": 0.02},
        "治理与决策": {"imp_financial": 0.18, "imp_compliance": 0.20, "imp_operation": 0.12,
                    "imp_reputation": 0.20, "imp_fraud": 0.08, "imp_strategy": 0.18,
                    "imp_data": 0.03, "imp_hse": 0.01},
        "资金活动": {"imp_financial": 0.32, "imp_compliance": 0.20, "imp_operation": 0.08,
                   "imp_reputation": 0.12, "imp_fraud": 0.08, "imp_strategy": 0.10,
                   "imp_data": 0.06, "imp_hse": 0.04},
        "财务报告与税务": {"imp_financial": 0.28, "imp_compliance": 0.25, "imp_operation": 0.08,
                       "imp_reputation": 0.16, "imp_fraud": 0.04, "imp_strategy": 0.10,
                       "imp_data": 0.06, "imp_hse": 0.03},
        "资产管理": {"imp_financial": 0.32, "imp_compliance": 0.08, "imp_operation": 0.16,
                   "imp_reputation": 0.12, "imp_fraud": 0.12, "imp_strategy": 0.08,
                   "imp_data": 0.04, "imp_hse": 0.08},
        "采购与外包": {"imp_financial": 0.20, "imp_compliance": 0.20, "imp_operation": 0.08,
                     "imp_reputation": 0.12, "imp_fraud": 0.20, "imp_strategy": 0.08,
                     "imp_data": 0.05, "imp_hse": 0.07},
        "合同管理": {"imp_financial": 0.20, "imp_compliance": 0.25, "imp_operation": 0.12,
                   "imp_reputation": 0.16, "imp_fraud": 0.08, "imp_strategy": 0.12,
                   "imp_data": 0.04, "imp_hse": 0.03},
        "工程项目": {"imp_financial": 0.28, "imp_compliance": 0.12, "imp_operation": 0.16,
                   "imp_reputation": 0.16, "imp_fraud": 0.08, "imp_strategy": 0.10,
                   "imp_data": 0.02, "imp_hse": 0.08},
        "人力资源": {"imp_financial": 0.15, "imp_compliance": 0.16, "imp_operation": 0.20,
                   "imp_reputation": 0.16, "imp_fraud": 0.12, "imp_strategy": 0.12,
                   "imp_data": 0.04, "imp_hse": 0.05},
        "信息系统": {"imp_financial": 0.10, "imp_compliance": 0.12, "imp_operation": 0.28,
                   "imp_reputation": 0.16, "imp_fraud": 0.12, "imp_strategy": 0.08,
                   "imp_data": 0.12, "imp_hse": 0.02},
        "合规与法律": {"imp_financial": 0.10, "imp_compliance": 0.38, "imp_operation": 0.08,
                    "imp_reputation": 0.20, "imp_fraud": 0.04, "imp_strategy": 0.08,
                    "imp_data": 0.10, "imp_hse": 0.02},
        "安全环保": {"imp_financial": 0.10, "imp_compliance": 0.22, "imp_operation": 0.22,
                   "imp_reputation": 0.18, "imp_fraud": 0.00, "imp_strategy": 0.06,
                   "imp_data": 0.02, "imp_hse": 0.20},
    },
    "impact_floor_factor": 0.75,
    "reduction_map": {"1": 0.00, "2": 0.15, "3": 0.40, "4": 0.55, "5": 0.70},
    "thresholds": {"extreme": 20, "high": 12, "medium": 6, "low": 3},
    "ref_reduction": 0.40,
}

LEVEL_ORDER = ["extreme", "high", "medium", "low", "minimal"]
LEVEL_LABELS = {"extreme": "极高", "high": "高", "medium": "中",
                "low": "低", "minimal": "极低"}
LEVEL_COLORS = {"extreme": "#C00000", "high": "#ED7D31", "medium": "#FFC000",
                "low": "#8EAADB", "minimal": "#70AD47"}
FREQ_SUGGESTION = {"extreme": "每年必审", "high": "每年审计",
                   "medium": "两年一轮", "low": "按需抽查",
                   "minimal": "按需抽查"}


def load_config(path=None):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for key in ("weights", "reduction_map", "thresholds"):
            cfg[key].update(user.get(key, {}))
        if "domain_weights" in user:
            base = dict(cfg["domain_weights"])
            base.update(user["domain_weights"])
            for dom in base:
                if dom in user["domain_weights"]:
                    base[dom].update(user["domain_weights"][dom])
            cfg["domain_weights"] = base
        cfg["impact_floor_factor"] = user.get("impact_floor_factor",
                                              cfg["impact_floor_factor"])
        cfg["ref_reduction"] = user.get("ref_reduction", cfg["ref_reduction"])
        cfg["version"] = user.get("version", cfg["version"])
    return cfg


def _is_yes(v):
    return str(v).strip() in ("是", "1", "true", "True", "Y", "y")


def validate_config(cfg):
    rows = {"全领域默认": cfg["weights"]}
    rows.update(cfg.get("domain_weights", {}))
    for name, w in rows.items():
        wsum = round(sum(w.values()), 6)
        if abs(wsum - 1.0) > 1e-6:
            raise ValueError(f"权重行[{name}]之和必须为 1，当前 {wsum}")
    if not 0 <= cfg.get("impact_floor_factor", 0.75) <= 1:
        raise ValueError("一票否决系数必须在 0~1 之间")
    if any(not (0 <= v <= 0.95) for v in cfg["reduction_map"].values()):
        raise ValueError("折减系数必须在 0~0.95 之间")


def effective_weights(risk, cfg):
    dw = cfg.get("domain_weights") or {}
    return dw.get(risk["domain"], cfg["weights"])


def composite_impact(risk, cfg):
    """八维加权；留空（None）的维度视为不适用，权重在已打分维度上重新归一化。
    返回 None 表示该风险未打任何影响维度分。"""
    w = effective_weights(risk, cfg)
    lin = 0.0
    wsum = 0.0
    mx = 0
    for d in DIMS:
        v = risk.get(d)
        if not isinstance(v, int):
            continue
        ww = w.get(d, 0)
        lin += v * ww
        wsum += ww
        mx = max(mx, v)
    if wsum == 0:
        return None
    floor = cfg.get("impact_floor_factor", 0.75) * mx
    return round(max(lin / wsum, floor), 2)


def inherent_score(risk, cfg):
    impact = composite_impact(risk, cfg)
    return None if impact is None else round(risk["likelihood"] * impact, 2)


def weakest_control_score(controls, risk_id, period):
    same = [c for c in controls
            if c["risk_id"] == risk_id and c["period"] == period]
    if not same:
        return None
    key = [c for c in same if _is_yes(c.get("key", ""))]
    pool = key if key else same
    return min(c["score"] for c in pool)


def reduction_of(control_score, cfg):
    if control_score is None:
        return 0.0
    return cfg["reduction_map"].get(str(control_score), 0.0)


def residual_score(inherent, control_score, cfg):
    red = reduction_of(control_score, cfg)
    return round(inherent * (1 - red), 2)


def level_of(value, cfg):
    t = cfg["thresholds"]
    if value >= t["extreme"]:
        return "extreme"
    if value >= t["high"]:
        return "high"
    if value >= t["medium"]:
        return "medium"
    if value >= t["low"]:
        return "low"
    return "minimal"


def assess_all(risks, controls, cfg):
    """返回按 risk_id+period 的评估字典列表。"""
    out = []
    for r in risks:
        inh = inherent_score(r, cfg)
        weak = weakest_control_score(controls, r["risk_id"], r["period"])
        res = residual_score(inh, weak, cfg) if inh is not None else None
        out.append({
            **r,
            "impact": composite_impact(r, cfg),
            "inherent": inh,
            "weakest_control": weak,
            "reduction": reduction_of(weak, cfg),
            "residual": res,
            "recovery": round((inh - res) / inh, 4)
                if inh is not None and inh > 0 else None,
            "inherent_level": level_of(inh, cfg) if inh is not None else "minimal",
            "residual_level": level_of(res, cfg) if res is not None else "minimal",
        })
    return out


def read_csv(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_dataset(data_dir, config_path=None):
    """data_dir 下直接放 risks.csv / controls.csv / config.json。"""
    cfg = load_config(os.path.join(data_dir, "config.json")
                      if not config_path else config_path)
    validate_config(cfg)
    risks_raw = read_csv(os.path.join(data_dir, "risks.csv"))
    controls_raw = read_csv(os.path.join(data_dir, "controls.csv"))
    risks = [{**{k: r.get(k, "") for k in ("risk_id", "name", "domain", "description",
                                           "owner_dept", "period", "rationale")},
              "likelihood": int(r["likelihood"]),
              **{d: (None if not str(r.get(d, "")).strip() else int(r[d]))
                 for d in DIMS}} for r in risks_raw]
    controls = [{**{k: c[k] for k in ("control_id", "risk_id", "period", "description")},
                 "score": int(c["score"]), "key": c.get("key", "否")}
                for c in controls_raw]
    return cfg, risks, controls


def periods_of(risks):
    seen = []
    for r in risks:
        if r["period"] not in seen:
            seen.append(r["period"])
    return seen


if __name__ == "__main__":
    print("common.py 为共享模块，请运行 export_from_excel.py / generate_report.py")
