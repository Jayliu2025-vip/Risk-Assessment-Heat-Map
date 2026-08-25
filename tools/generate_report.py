# -*- coding: utf-8 -*-
"""读 data/export 下的 CSV 对，输出汇报图集与高管简报：
    output/{period}_inherent_heatmap.png   固有热力图（气泡）
    output/{period}_residual_heatmap.png   剩余热力图（气泡）
    output/{period}_domain_distribution.png 领域×等级分布
    output/trend_{base}_vs_{compare}.png    两期剩余风险对比哑铃图
    output/executive_report_{period}.pdf    高管简报（封面+四图）

用法：python tools/generate_report.py [--data-root data/export] [--period 2026H1]
"""
import argparse
import math
import os
import sys
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LEVEL_COLORS, LEVEL_LABELS, LEVEL_ORDER, DIM_LABELS, DIMS,
                    DOMAINS, FREQ_SUGGESTION, assess_all, load_config,
                    load_dataset)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

LIK_LABELS = {1: "极低", 2: "低", 3: "中", 4: "高", 5: "极高"}
IMP_LABELS = {1: "轻微", 2: "较小", 3: "中等", 4: "较大", 5: "重大"}


def load_period(data_root, period):
    d = os.path.join(data_root, str(period))
    return d


def impact_cell(value):
    """将正数综合影响按 Excel/JavaScript 口径四舍五入到 1~5 档。"""
    return math.floor(value + 0.5)


def bubble_offsets(count):
    """返回单元格中心周围的确定性网格偏移，任意数量均不重复。"""
    if count <= 0:
        return []
    columns = min(3, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / columns)
    x_step = 0 if columns == 1 else min(0.34, 0.80 / (columns - 1))
    y_step = 0 if rows == 1 else min(0.34, 0.80 / (rows - 1))
    x_start = -x_step * (columns - 1) / 2
    y_start = y_step * (rows - 1) / 2
    return [
        (round(x_start + (index % columns) * x_step, 6),
         round(y_start - (index // columns) * y_step, 6))
        for index in range(count)
    ]


def draw_bubble_heatmap(ax, assessed, cfg, mode, period):
    # 背景格子按固有值分档淡色铺底，气泡颜色按各自等级
    for li in range(1, 6):
        for ii in range(1, 6):
            v = li * ii
            lv = "minimal"
            for k in ("extreme", "high", "medium", "low"):
                th = {"extreme": 20, "high": 12, "medium": 6, "low": 3}[k]
                if v >= th:
                    lv = k
                    break
            ax.add_patch(Rectangle((ii - 0.5, li - 0.5), 1, 1,
                                   facecolor=LEVEL_COLORS[lv], alpha=0.28, ec="white", lw=1.5))
    # 同格气泡确定性错开
    cells = {}
    for a in assessed:
        key = (a["likelihood"], impact_cell(a["impact"]))
        cells.setdefault(key, []).append(a)
    for key, items in sorted(cells.items()):
        li, ii = key
        for a, (dx, dy) in zip(items, bubble_offsets(len(items))):
            x = ii + dx
            y = li + dy
            lv = a[f"{mode}_level"]
            ax.scatter(x, y, s=430, c=LEVEL_COLORS[lv], edgecolors="white",
                       linewidths=1.4, zorder=3)
            ax.text(x, y, a["risk_id"], ha="center", va="center",
                    fontsize=6.2, color="white", weight="bold", zorder=4)
    handles = [Patch(facecolor=LEVEL_COLORS[k], label=f"{LEVEL_LABELS[k]}") for k in LEVEL_ORDER]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1),
              title="等级", frameon=False, fontsize=9)
    ax.set_xlim(0.45, 5.55)
    ax.set_ylim(0.45, 5.55)
    ax.set_xticks(range(1, 6))
    ax.set_yticks(range(1, 6))
    ax.set_xticklabels([f"{i}\n{IMP_LABELS[i]}" for i in range(1, 6)], fontsize=9)
    ax.set_yticklabels([f"{i} {LIK_LABELS[i]}" for i in range(1, 6)], fontsize=9)
    ax.set_xlabel("综合影响档（四舍五入）", fontsize=11)
    ax.set_ylabel("发生可能性", fontsize=11)
    tag = "固有" if mode == "inherent" else "剩余"
    ax.set_title(f"{tag}风险评估热力图 · {period}（n={len(assessed)}）",
                 fontsize=14, weight="bold", pad=12)


def draw_domain_distribution(fig_ax, assessed):
    ax = fig_ax
    present = {a["domain"] for a in assessed}
    domains = [d for d in DOMAINS if d in present] + sorted(present - set(DOMAINS))
    counts = {d: {k: 0 for k in LEVEL_ORDER} for d in domains}
    for a in assessed:
        counts[a["domain"]][a["residual_level"]] += 1
    y = list(range(len(domains)))[::-1]
    left = [0] * len(domains)
    for k in LEVEL_ORDER:
        vals = [counts[d][k] for d in domains]
        bars = ax.barh(y, vals, left=left, color=LEVEL_COLORS[k],
                       label=LEVEL_LABELS[k], height=0.62)
        for b, v in zip(bars, vals):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, b.get_y() + b.get_height() / 2,
                        str(v), ha="center", va="center", fontsize=9,
                        color="white", weight="bold")
        left = [l + v for l, v in zip(left, vals)]
    ax.set_yticks(y)
    ax.set_yticklabels(domains, fontsize=10)
    ax.set_xlabel("风险数量（按剩余等级）", fontsize=11)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title("各领域剩余风险等级分布", fontsize=14, weight="bold", pad=12)
    ax.spines[["top", "right"]].set_visible(False)


def draw_trend(ax, base_rows, cmp_rows, base_p, cmp_p, top_n=12):
    cmap = {a["risk_id"]: a for a in base_rows}
    deltas = []
    for a in base_rows:
        prev = next((p for p in cmp_rows if p["risk_id"] == a["risk_id"]), None)
        if prev:
            deltas.append((a, prev["residual"], a["residual"] - prev["residual"]))
    deltas.sort(key=lambda t: -abs(t[2]))
    show = deltas[:top_n][::-1]
    if not show:
        ax.text(0.5, 0.5, "无两期可比数据", ha="center", va="center", fontsize=14)
        return
    ys = range(len(show))
    for y, (a, prev_res, d) in zip(ys, show):
        worse = d > 0
        ax.plot([prev_res, a["residual"]], [y, y], color="#B0B0B0", lw=2, zorder=2)
        ax.scatter([prev_res], [y], s=90, c="#7F7F7F", zorder=3)
        ax.scatter([a["residual"]], [y], s=130,
                   c=("#C00000" if worse else "#70AD47"), zorder=4)
        ax.text(max(prev_res, a["residual"]) + 0.35, y,
                f"{d:+.2f}", va="center", fontsize=8.5,
                color=("#C00000" if worse else "#70AD47"), weight="bold")
    ax.set_yticks(list(ys))
    ax.set_yticklabels([f"{a['risk_id']} {a['name'][:10]}" for a, _, _ in show], fontsize=9)
    ax.set_xlabel("剩余风险分（灰点＝上期，彩点＝本期）", fontsize=11)
    ax.set_xlim(0, max(max(pr, a["residual"]) for a, pr, _ in show) + 1.8)
    ax.set_title(f"两期剩余风险变化 TOP{len(show)}　{cmp_p} → {base_p}（红＝恶化 绿＝改善）",
                 fontsize=13, weight="bold", pad=12)
    ax.spines[["top", "right"]].set_visible(False)


def draw_transition(ax, base_rows, cmp_rows, base_p, cmp_p):
    prev = {a["risk_id"]: a for a in cmp_rows}
    mat = {p: {c: 0 for c in LEVEL_ORDER} for p in LEVEL_ORDER}
    for a in base_rows:
        p = prev.get(a["risk_id"])
        if p:
            mat[p["residual_level"]][a["residual_level"]] += 1
    total = sum(mat[p][c] for p in LEVEL_ORDER for c in LEVEL_ORDER)
    mx = max(1, max(mat[p][c] for p in LEVEL_ORDER for c in LEVEL_ORDER))
    for i, p in enumerate(LEVEL_ORDER):
        for j, c in enumerate(LEVEL_ORDER):
            n = mat[p][c]
            if n:
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor=LEVEL_COLORS[c],
                                       alpha=0.15 + 0.65 * (n / mx),
                                       ec="white", lw=2))
            else:
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor="#F5F6F8",
                                       ec="white", lw=2))
            if n:
                ax.text(j + 0.5, i + 0.42, str(n), ha="center", va="center",
                        fontsize=15, weight="bold",
                        color=LEVEL_COLORS[c] if n / mx < 0.55 else "white")
                ax.text(j + 0.5, i + 0.72, f"{n / total:.0%}", ha="center",
                        va="center", fontsize=8, color="#6B7280")
    ax.set_xlim(0, 5)
    ax.set_ylim(5, 0)
    ax.set_xticks([i + 0.5 for i in range(5)])
    ax.set_yticks([i + 0.5 for i in range(5)])
    ax.set_xticklabels([LEVEL_LABELS[k] for k in LEVEL_ORDER], fontsize=10)
    ax.set_yticklabels([LEVEL_LABELS[k] for k in LEVEL_ORDER], fontsize=10)
    ax.set_xlabel(f"本期剩余等级（{base_p}）", fontsize=11)
    ax.set_ylabel(f"上期剩余等级（{cmp_p}）", fontsize=11)
    improved = sum(mat[p][c] for i, p in enumerate(LEVEL_ORDER)
                   for c in LEVEL_ORDER[i + 1:])
    worsened = sum(mat[p][c] for i, p in enumerate(LEVEL_ORDER)
                   for c in LEVEL_ORDER[:i])
    ax.set_title(f"两期风险等级迁徙矩阵（改善 {improved} 条 / 恶化 {worsened} 条 / 持平 {total - improved - worsened} 条）",
                 fontsize=13, weight="bold", pad=12)


def perturbed_weights(cfg, dim, factor):
    """把某一维度的权重（全局行+全部领域行）缩放 factor 后逐行归一化。"""
    import copy
    c2 = copy.deepcopy(cfg)
    rows = [c2["weights"]] + list(c2.get("domain_weights", {}).values())
    for w in rows:
        w[dim] = w.get(dim, 0) * factor
        s = sum(w.values()) or 1.0
        for k in list(w):
            w[k] = w[k] / s
    return c2


def sensitivity_analysis(ax, cfg, risks, controls, base_rank, top_ids):
    scenarios = [("基准", {rid: base_rank[rid] for rid in top_ids})]
    overlaps = []
    base_top5 = set(top_ids[:5])
    for d in DIMS:
        for f, tag in ((0.8, "-20%"), (1.2, "+20%")):
            cfg2 = perturbed_weights(cfg, d, f)
            a2 = sorted(assess_all(risks, controls, cfg2),
                        key=lambda x: -x["residual"])
            ranks = {a["risk_id"]: i + 1 for i, a in enumerate(a2)}
            top5 = {a["risk_id"] for a in a2[:5]}
            overlaps.append(len(top5 & base_top5))
            scenarios.append((f"{DIM_LABELS[d]} {tag}", ranks))
    n_rows = len(scenarios)
    for i, (name, ranks) in enumerate(scenarios):
        y = n_rows - 1 - i
        ax.text(-0.5, y + 0.5, name, ha="right", va="center", fontsize=9.5,
                weight="bold" if i == 0 else "normal",
                color="#1F4E79" if i == 0 else "#374151")
        for j, rid in enumerate(top_ids):
            rk = ranks.get(rid)
            if rk is None or rk > 8:
                ax.add_patch(Rectangle((j, y), 1, 1, facecolor="#F0F1F4",
                                       ec="white", lw=1.5))
                continue
            shade = {1: "#1F4E79", 2: "#2E75B6", 3: "#5B9BD5",
                     4: "#9DC3E6", 5: "#BDD7EE"}.get(rk, "#E2EFD9")
            ax.add_patch(Rectangle((j, y), 1, 1, facecolor=shade, ec="white", lw=1.5))
            ax.text(j + 0.5, y + 0.5, str(rk), ha="center", va="center",
                    fontsize=10, weight="bold",
                    color="white" if rk <= 3 else "#374151")
    ax.set_xlim(-3.6, len(top_ids))
    ax.set_ylim(0, n_rows)
    ax.set_xticks([j + 0.5 for j in range(len(top_ids))])
    ax.set_xticklabels(top_ids, fontsize=9.5)
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    stable = sum(1 for o in overlaps if o == 5)
    worst = min(overlaps)
    n_scen = len(overlaps)
    ax.set_title(f"权重敏感性分析：各维度权重 ±20% 下的剩余风险排名（TOP5 稳定 {stable}/{n_scen}，"
                 f"最差场景重合 {worst}/5）", fontsize=12.5, weight="bold", pad=12)
    return stable, worst, overlaps


def cover_page(pdf, assessed, cfg, period, compare_p):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor("white")
    n_ext = sum(1 for a in assessed if a["residual_level"] == "extreme")
    n_high = sum(1 for a in assessed if a["residual_level"] == "high")
    avg = sum(a["residual"] for a in assessed) / len(assessed)
    rec = [a["recovery"] for a in assessed if a["recovery"] is not None]
    avg_rec = sum(rec) / len(rec) if rec else 0
    top = sorted(assessed, key=lambda a: -a["residual"])[:10]

    fig.text(0.07, 0.90, "内部审计风险评估报告", fontsize=26, weight="bold", color="#1F4E79")
    fig.text(0.07, 0.845, f"评估期间：{period}" +
             (f"　（环比 {compare_p}）" if compare_p else ""), fontsize=13, color="#404040")
    fig.text(0.07, 0.81, f"生成时间：{datetime.now():%Y-%m-%d %H:%M}", fontsize=9, color="#808080")

    cards = [("风险总数", str(len(assessed)), "#1F4E79"),
             ("平均剩余分", f"{avg:.2f}", "#ED7D31"),
             ("极高风险", str(n_ext), "#C00000"),
             ("高风险", str(n_high), "#FFC000"),
             ("控制挽回率", f"{avg_rec:.0%}", "#70AD47")]
    for i, (label, val, color) in enumerate(cards):
        x = 0.07 + i * 0.178
        fig.patches.append(Rectangle((x, 0.68), 0.16, 0.095, transform=fig.transFigure,
                                     facecolor=color, alpha=0.12, ec="none"))
        fig.text(x + 0.08, 0.735, val, fontsize=18, weight="bold", color=color, ha="center")
        fig.text(x + 0.08, 0.70, label, fontsize=9.5, color="#404040", ha="center")

    fig.text(0.07, 0.63, "审计优先级 TOP10（按剩余风险降序）", fontsize=13, weight="bold")
    col_labels = ["排名", "编号", "风险名称", "领域", "可能性", "固有", "最弱控制", "剩余", "等级", "建议频次"]
    rows = [[str(i + 1), a["risk_id"], a["name"][:12], a["domain"],
             LIK_LABELS[a["likelihood"]], f'{a["inherent"]:.1f}',
             str(a["weakest_control"]) if a["weakest_control"] else "—",
             f'{a["residual"]:.2f}', LEVEL_LABELS[a["residual_level"]],
             FREQ_SUGGESTION[a["residual_level"]]] for i, a in enumerate(top)]
    tab = fig.add_axes([0.07, 0.16, 0.86, 0.44])
    tab.axis("off")
    table = tab.table(cellText=rows, colLabels=col_labels, loc="upper center",
                      cellLoc="center", colWidths=[0.05, 0.07, 0.17, 0.11, 0.08,
                                                   0.07, 0.09, 0.08, 0.08, 0.12])
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.55)
    for (r, c), cell in table.get_celld().items():
        if r == 0:
            cell.set_facecolor("#1F4E79")
            cell.set_text_props(color="white", weight="bold")
        elif r <= len(rows):
            lv_key = top[r - 1]["residual_level"]
            if c == 8:
                cell.set_facecolor(LEVEL_COLORS[lv_key])
                cell.set_text_props(color="white", weight="bold")
            elif r % 2 == 0:
                cell.set_facecolor("#F2F6FC")
    pdf.savefig(fig)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=os.path.join(ROOT, "data", "export"))
    ap.add_argument("--period", default=None, help="基准期间，默认取字典序最大的")
    ap.add_argument("--compare", default=None, help="对比期间，默认另一期；设为 none 关闭趋势图")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "output"))
    ap.add_argument("--sensitivity", action="store_true",
                    help="附加权重敏感性分析（各维度 ±20%% 扰动）")
    args = ap.parse_args()

    cfg = load_config(os.path.join(args.data_root, "config.json"))
    all_periods = [p for p in os.listdir(args.data_root)
                   if os.path.isdir(os.path.join(args.data_root, p))]
    all_periods.sort()
    if not all_periods:
        sys.exit(f"[错误] {args.data_root} 下没有期间目录，请先运行 export_from_excel.py")
    base_p = args.period or all_periods[-1]

    def assess(p):
        from common import load_dataset
        _, risks, controls = load_dataset(load_period(args.data_root, p))
        return assess_all(risks, controls, cfg)

    assessed = assess(base_p)
    cmp_p = args.compare
    cmp_rows = None
    if cmp_p != "none":
        cmp_p = cmp_p or next((p for p in reversed(all_periods) if p != base_p), None)
        if cmp_p and os.path.isdir(load_period(args.data_root, cmp_p)):
            cmp_rows = assess(cmp_p)

    os.makedirs(args.outdir, exist_ok=True)

    fig, ax = plt.subplots(figsize=(11.69, 7.2))
    draw_bubble_heatmap(ax, assessed, cfg, "inherent", base_p)
    fig.tight_layout()
    f1 = f"{base_p}_inherent_heatmap.png"
    fig.savefig(os.path.join(args.outdir, f1), dpi=150, bbox_inches="tight")

    fig, ax = plt.subplots(figsize=(11.69, 7.2))
    draw_bubble_heatmap(ax, assessed, cfg, "residual", base_p)
    fig.tight_layout()
    f2 = f"{base_p}_residual_heatmap.png"
    fig.savefig(os.path.join(args.outdir, f2), dpi=150, bbox_inches="tight")

    fig, ax = plt.subplots(figsize=(10, 5.2))
    draw_domain_distribution(ax, assessed)
    fig.tight_layout()
    f3 = f"{base_p}_domain_distribution.png"
    fig.savefig(os.path.join(args.outdir, f3), dpi=150, bbox_inches="tight")

    f4 = None
    f5 = None
    if cmp_rows:
        fig, ax = plt.subplots(figsize=(10.5, 6.5))
        draw_trend(ax, assessed, cmp_rows, base_p, cmp_p)
        fig.tight_layout()
        f4 = f"trend_{base_p}_vs_{cmp_p}.png"
        fig.savefig(os.path.join(args.outdir, f4), dpi=150, bbox_inches="tight")

        fig, ax = plt.subplots(figsize=(8.2, 7.2))
        draw_transition(ax, assessed, cmp_rows, base_p, cmp_p)
        fig.tight_layout()
        f5 = f"transition_{base_p}_vs_{cmp_p}.png"
        fig.savefig(os.path.join(args.outdir, f5), dpi=150, bbox_inches="tight")

    f6 = None
    if args.sensitivity:
        _, risks_b, controls_b = load_dataset(load_period(args.data_root, base_p))
        ranked = sorted(assessed, key=lambda x: -x["residual"])
        base_rank = {a["risk_id"]: i + 1 for i, a in enumerate(ranked)}
        top_ids = [a["risk_id"] for a in ranked[:8]]
        fig, ax = plt.subplots(figsize=(11, 8.5))
        stable, worst, overlaps = sensitivity_analysis(ax, cfg, risks_b, controls_b,
                                                       base_rank, top_ids)
        fig.tight_layout()
        f6 = f"sensitivity_{base_p}.png"
        fig.savefig(os.path.join(args.outdir, f6), dpi=150, bbox_inches="tight")
        print(f"\n[权重敏感性分析] 各维度 ±20% 扰动（逐行归一化），TOP5 与基准重合度："
              f"{overlaps} → 完全稳定 {stable}/{len(overlaps)}，最差 {worst}/5")

    pdf_path = os.path.join(args.outdir, f"executive_report_{base_p}.pdf")
    with PdfPages(pdf_path) as pdf:
        cover_page(pdf, assessed, cfg, base_p, cmp_p)
        for fname in filter(None, (f1, f2, f3, f4, f5, f6)):
            img = plt.imread(os.path.join(args.outdir, fname))
            fig = plt.figure(figsize=(11.69, 8.27))
            ax = fig.add_axes([0.03, 0.03, 0.94, 0.94])
            ax.imshow(img)
            ax.axis("off")
            pdf.savefig(fig)
            plt.close(fig)
        meta = pdf.infodict()
        meta["Title"] = f"内部审计风险评估报告 {base_p}"
        meta["Author"] = "Risk Assessment Heat Map"

    print(f"[完成] 输出目录 {os.path.relpath(args.outdir, ROOT)}：")
    for f in filter(None, (f1, f2, f3, f4, f5, f6)):
        print("  -", f)
    print("  -", os.path.basename(pdf_path))

    print("\n[交叉验证用] 剩余风险 TOP8（供三件套数值核对）：")
    top8 = sorted(assessed, key=lambda x: -x["residual"])[:8]
    tpl = ("  {rid} {name:<14} L={lik} I={imp:>5.2f} "
           "固有={inh:>5.2f} 控制分={wc} 剩余={res:>5.2f} 挽回率={rec:>4.0%} [{lv}]")
    for a in top8:
        wc = a["weakest_control"] if a["weakest_control"] is not None else "-"
        rec = a["recovery"] if a["recovery"] is not None else 0
        print(tpl.format(rid=a["risk_id"], name=a["name"][:12], lik=a["likelihood"],
                         imp=a["impact"], inh=a["inherent"], wc=wc,
                         res=a["residual"], rec=rec,
                         lv=LEVEL_LABELS[a["residual_level"]]))

    domains = []
    for a in assessed:
        if a["domain"] not in domains:
            domains.append(a["domain"])
    print("\n[控制挽回率·领域排名]（(固有-剩余)/固有，越高说明控制环境化解能力越强）：")
    stats = []
    for dom in domains:
        rows = [a for a in assessed if a["domain"] == dom]
        recs = [a["recovery"] for a in rows if a["recovery"] is not None]
        avg_r = sum(recs) / len(recs) if recs else 0
        stats.append((dom, avg_r, len(rows)))
    for dom, avg_r, n in sorted(stats, key=lambda t: -t[1]):
        print(f"  {dom:<8} 平均挽回率 {avg_r:>5.0%}　（{n} 条风险）")

    if cmp_rows:
        prev = {a["risk_id"]: a for a in cmp_rows}
        print(f"\n[两期等级迁徙] {cmp_p} → {base_p}：")
        for a in assessed:
            p = prev.get(a["risk_id"])
            if not p:
                continue
            if p["residual_level"] != a["residual_level"]:
                arrow = "改善" if a["residual"] < p["residual"] else "恶化"
                print(f"  {a['risk_id']} {a['name'][:12]:<14} "
                      f"{LEVEL_LABELS[p['residual_level']]} → {LEVEL_LABELS[a['residual_level']]}　{arrow}")


if __name__ == "__main__":
    main()
