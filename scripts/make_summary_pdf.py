"""Builds ARIA_Equity_Research_Validation_Summary.pdf from the saved backtest outputs (re-run it after the sweep finishes).

    python -X utf8 scripts/scenario_report_validation.py --robustness     # first: writes report_validation/robustness.json
    python -X utf8 scripts/make_summary_pdf.py [out.pdf]

Reads: data/scenario_backtest/UNIVERSE_SCENARIO_REPORT.md (Experiment 1 tables), report_validation/rows.parquet (Experiment 2 rows),
report_validation/robustness.json (paired differences, CIs, costs, split, calibrated interval) and the per-company result summaries (coverage).
Every number in the PDF is computed here or parsed from those files; the published-study figures are the only external numbers and are
labelled with their sources. No broker data is invented."""
from __future__ import annotations

import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
SB = ROOT / "data" / "scenario_backtest"
RV = SB / "report_validation"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "ARIA_Equity_Research_Validation_Summary.pdf"
TMP = SB / "_pdf_tmp"
TMP.mkdir(exist_ok=True)
GREEN, RED, GREY, INK, AMBER = "#1f6f50", "#b4412f", "#8a8f87", "#1c2a24", "#c47a2c"
if not (RV / "robustness.json").exists():
    sys.exit("run `python -X utf8 scripts/scenario_report_validation.py --robustness` first")
J = json.loads((RV / "robustness.json").read_text(encoding="utf-8"))
HS = (3, 6, 12)

st = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=st["Heading1"], fontSize=15, textColor=colors.HexColor(INK), spaceAfter=6)
H2 = ParagraphStyle("H2", parent=st["Heading2"], fontSize=11.5, textColor=colors.HexColor(GREEN), spaceBefore=8, spaceAfter=4)
P = ParagraphStyle("P", parent=st["Normal"], fontSize=9, leading=12.5)
SM = ParagraphStyle("SM", parent=P, fontSize=7.8, leading=10.5, textColor=colors.HexColor("#444444"))
BUL = ParagraphStyle("BUL", parent=P, leftIndent=10, bulletIndent=0)
BIG = ParagraphStyle("BIG", parent=P, fontSize=10.5, leading=16, spaceAfter=7)          # brokerage page: larger, airier text
BIGB = ParagraphStyle("BIGB", parent=BIG, leftIndent=12, bulletIndent=0)
BIGS = ParagraphStyle("BIGS", parent=SM, fontSize=9, leading=13)
CELL = ParagraphStyle("CELL", parent=SM, fontSize=7.4, leading=9.6, textColor=colors.HexColor(INK))
HWC = ParagraphStyle("HWC", parent=CELL, textColor=colors.white, fontName="Helvetica-Bold")
BIGCELL = ParagraphStyle("BIGCELL", parent=CELL, fontSize=9, leading=12.5)
BIGHW = ParagraphStyle("BIGHW", parent=BIGCELL, textColor=colors.white, fontName="Helvetica-Bold")
BOX = ParagraphStyle("BOX", parent=P, fontSize=9, leading=12.5, textColor=colors.HexColor(INK))


def tbl(rows, widths=None, head=True, font=8, wrap=False):
    if wrap:
        rows = [[Paragraph(str(c), HWC if (head and i == 0) else CELL) if not isinstance(c, Paragraph) else c for c in r] for i, r in enumerate(rows)]
    t = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), font), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9ceca")),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f4")])]
    if head:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(GREEN)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(style))
    return t


def box(paras, bg="#eef3ee", border=GREEN, width=176 * mm):
    """Light tinted callout with dark text (never light text on a dark fill)."""
    t = Table([[paras]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)), ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(border)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def pct(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return "n/a" if x is None else f"{100 * x:+.{d}f}pp"


def cis(c, d=1, sign=False):
    if not c:
        return "n/a"
    f = (lambda v: f"{100 * v:+.{d}f}") if sign else (lambda v: f"{100 * v:.{d}f}")
    return f"{f(c['est'])}% [{f(c['lo'])}, {f(c['hi'])}]"


def dci(c, d=1):
    """Paired difference in percentage points with CI and p."""
    if not c:
        return "n/a"
    p = "<.001" if c["p"] < .001 else f"{c['p']:.3f}"
    return f"{100 * c['est']:+.{d}f} [{100 * c['lo']:+.{d}f}, {100 * c['hi']:+.{d}f}] p {p}"


def err(c):
    return [[c["est"] - c["lo"]], [c["hi"] - c["est"]]]


# ---------------------------------------------------------------- coverage
status = {}
for p in glob.glob(str(SB / "results" / "*.summary.json")):
    try:
        s = json.load(open(p)).get("status")
    except Exception:
        continue
    status[s] = status.get(s, 0) + 1
n_all = sum(status.values())
LABEL = {"ok": "Scored (forecasts validated)", "insufficient_history": "Insufficient history (< 3 fiscal years / no valid origin)",
         "model_refused": "ARIA's valuation model declined (loss-making, no payout history, ...)", "no_price": "No price history available",
         "retry": "Data source unreachable (to retry)", "no_screener_page": "No statements page", "failed": "Failed"}

# ------------------------------------------------------- experiment 1 tables
md = (SB / "UNIVERSE_SCENARIO_REPORT.md").read_text(encoding="utf-8")


def exp1(line):
    m = re.search(rf"#### {line}\n\n(.*?)\n\n", md, re.S)
    out = {}
    if not m:
        return out
    for r in m.group(1).split("\n")[2:]:
        c = [x.strip() for x in r.strip("|").split("|")]
        if c and c[0].isdigit():
            out[int(c[0])] = c
    return out


E1 = {ln: exp1(ln) for ln in ("revenue", "ebitda", "margin", "eps")}


def num(s):
    m = re.search(r"-?\d+(\.\d+)?", s.replace("+", ""))
    return float(m.group()) if m else np.nan


def bias_ci(c):
    n = [float(x) for x in re.findall(r"[-+]?\d+\.\d+", c[2])]
    return n if len(n) == 3 else [np.nan] * 3


def skill(c, which="rw"):
    m = re.search(rf"{which} ([-+]\d+\.\d+)", c[7])
    return float(m.group(1)) if m else np.nan


# ------------------------------------------------------- experiment 2 rows
R = pd.read_parquet(RV / "rows.parquet")
R = R[R["horizon_m"].isin(HS)]
n_comp2 = R["symbol"].nunique()
mix = R[R["horizon_m"] == 12]["rating"].value_counts(normalize=True)
HL = {h: J["by_definition"]["headline"][str(h)] for h in HS}
WZ = {h: J["by_definition"]["winsor"][str(h)] for h in HS}
sp = {h: float(R[R.horizon_m == h][["upside", "excess_return"]].dropna().corr(method="spearman").iloc[0, 1]) for h in HS}
tp = {h: R[R.horizon_m == h].dropna(subset=["tp_err_abs"]) for h in HS}
d12 = R[R["horizon_m"] == 12].dropna(subset=["tp", "p_h", "p0"])
up = d12[d12["tp"] > d12["p0"]]
tp_met_12 = float((up["p_h"] >= up["tp"]).mean()) if len(up) else np.nan
imp_mean = float((d12["forecast_return"] - d12["price_return"]).mean())
imp_med = float((d12["forecast_return"] - d12["price_return"]).median())

# ------------------------------------------------------------------ charts
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
ks = [1, 3, 5]

# c1: typical miss and bias (with 90% CI error bars)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 2.6))
for ln, c, lab in (("revenue", GREEN, "Revenue"), ("ebitda", AMBER, "EBITDA")):
    a1.plot(ks, [100 * num(E1[ln][k][3]) if k in E1[ln] else np.nan for k in ks], marker="o", color=c, label=lab)
    b = np.array([bias_ci(E1[ln][k]) if k in E1[ln] else [np.nan] * 3 for k in ks])
    off = -0.1 if ln == "revenue" else 0.1
    a2.errorbar(np.array(ks) + off, 100 * b[:, 0], yerr=[100 * (b[:, 0] - b[:, 1]), 100 * (b[:, 2] - b[:, 0])], fmt="o", color=c, capsize=3, label=lab)
a1.set_xlabel("Years ahead"); a1.set_ylabel("Typical miss (%)"); a1.set_xticks(ks); a1.grid(alpha=.25); a1.legend(frameon=False)
a1.set_title("Typical miss (median absolute error)", fontsize=8)
a2.axhline(0, color="black", lw=.6); a2.set_xticks(ks); a2.set_xlabel("Years ahead"); a2.set_ylabel("Bias: forecast vs actual (%)"); a2.grid(alpha=.25)
a2.set_title("Bias with 90% CI (+ = forecast too high)", fontsize=8)
fig.tight_layout(); fig.savefig(TMP / "c1.png", dpi=170); plt.close(fig)

# c1b: skill vs naive
fig, ax = plt.subplots(figsize=(7.0, 2.3))
labs, vals, cols = [], [], []
for ln, lab in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("margin", "Margin")):
    for k in ks:
        if k in E1[ln]:
            labs.append(f"{lab}\n{k}y"); vals.append(skill(E1[ln][k], "mr" if ln == "margin" else "rw")); cols.append(GREEN if vals[-1] > 0 else RED)
ax.bar(range(len(vals)), vals, color=cols)
for i, v in enumerate(vals):
    ax.text(i, v + (0.015 if v >= 0 else -0.05), f"{v:+.2f}", ha="center", fontsize=7)
ax.axhline(0, color="black", lw=.6); ax.set_xticks(range(len(vals))); ax.set_xticklabels(labs, fontsize=7)
ax.set_ylabel("Skill vs naive"); ax.set_ylim(min(vals + [0]) - 0.12, max(vals + [0]) + 0.12)
fig.tight_layout(); fig.savefig(TMP / "c1b.png", dpi=170); plt.close(fig)

# c2: hit rate by call with 95% CI vs the base rate of the same event
fig, axs = plt.subplots(1, 3, figsize=(7.0, 2.5), sharey=True)
for ax, h in zip(axs, HS):
    for i, (k, c) in enumerate((("BUY", GREEN), ("HOLD", GREY), ("SELL", RED))):
        pr = HL[h]["per_rating"][k]
        ax.bar(i, 100 * pr["hit"]["est"], color=c, yerr=100 * np.array(err(pr["hit"])), capsize=3)
        ax.plot([i - .4, i + .4], [100 * pr["hit_base_rate_all_stocks"]] * 2, color="black", lw=1.4, ls="--")
    ax.set_xticks(range(3)); ax.set_xticklabels(["BUY", "HOLD", "SELL"]); ax.set_title(f"{h} months", fontsize=8); ax.set_ylim(0, 75); ax.grid(axis="y", alpha=.25)
axs[0].set_ylabel("Hit rate (%), 95% CI")
axs[0].plot([], [], color="black", ls="--", label="same event, all stocks (naive)"); axs[0].legend(frameon=False, fontsize=6.5, loc="upper left")
fig.tight_layout(); fig.savefig(TMP / "c2.png", dpi=170); plt.close(fig)

# c3: median excess by call with 95% CI
fig, ax = plt.subplots(figsize=(7.0, 2.4))
x = np.arange(3)
for i, (k, c) in enumerate((("BUY", GREEN), ("HOLD", GREY), ("SELL", RED))):
    me = [HL[h]["per_rating"][k]["median_excess"] for h in HS]
    ax.bar(x + (i - 1) * .25, [100 * m["est"] for m in me], .25, label=k, color=c, yerr=100 * np.array([[m["est"] - m["lo"] for m in me], [m["hi"] - m["est"] for m in me]]), capsize=3)
ax.axhline(0, color="black", lw=.6); ax.set_xticks(x); ax.set_xticklabels([f"{h} months" for h in HS]); ax.set_ylabel("Median excess vs Nifty (%), 95% CI"); ax.legend(frameon=False, ncol=3)
ax.grid(axis="y", alpha=.25)
fig.tight_layout(); fig.savefig(TMP / "c3.png", dpi=170); plt.close(fig)

# c4: paired differences in hit rate, ARIA minus baseline, with 95% CI
fig, ax = plt.subplots(figsize=(7.0, 2.5))
bl = [("random_same_mix", "Random, same mix", GREY), ("always_BUY", "Always BUY", AMBER), ("always_SELL", "Always SELL", RED)]
for i, (k, lab, c) in enumerate(bl):
    d = [HL[h]["hit"]["paired_vs"][k] for h in HS]
    ax.bar(x + (i - 1) * .27, [100 * v["est"] for v in d], .27, color=c, label=lab, yerr=100 * np.array([[v["est"] - v["lo"] for v in d], [v["hi"] - v["est"] for v in d]]), capsize=3)
ax.axhline(0, color="black", lw=.6); ax.set_xticks(x); ax.set_xticklabels([f"{h} months" for h in HS]); ax.set_ylabel("ARIA minus baseline,\nhit rate (pp), 95% CI"); ax.legend(frameon=False, fontsize=7, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0))
ax.grid(axis="y", alpha=.25)
fig.tight_layout(); fig.savefig(TMP / "c4.png", dpi=170); plt.close(fig)

# c5: yearly long-short (raw and winsorised)
pw = J["portfolio"]["winsor"]["years"]; pr_ = J["portfolio"]["headline"]["years"]
fig, ax = plt.subplots(figsize=(7.0, 2.3))
yy = [t["year"] for t in pr_]
ax.bar(np.arange(len(yy)) - .2, [100 * t["long_short"] for t in pr_], .4, color=GREEN, label="long BUY / short SELL, raw")
ax.bar(np.arange(len(yy)) + .2, [100 * t["long_short"] for t in pw], .4, color=GREY, label="clipped at 1st/99th percentile")
ax.axhline(0, color="black", lw=.6); ax.set_xticks(range(len(yy))); ax.set_xticklabels([f"FY{y}" for y in yy]); ax.set_ylabel("12-month return (%)"); ax.legend(frameon=False, fontsize=7)
ax.grid(axis="y", alpha=.25)
fig.tight_layout(); fig.savefig(TMP / "c5.png", dpi=170); plt.close(fig)

# c6: scenario coverage, as shipped vs empirically calibrated, out of sample, with 95% CI
IV = J["interval"]
fig, axs = plt.subplots(1, 3, figsize=(7.0, 2.5), sharey=True)
for ax, ln, lab in zip(axs, ("revenue", "ebitda", "margin"), ("Revenue", "EBITDA", "EBITDA margin")):
    cells = IV["cells"][ln]
    kk = [int(k) for k, c in cells.items() if "test_calibrated" in c]
    for j, (key, c, nm) in enumerate((("test_uncalibrated", GREY, "as shipped"), ("test_calibrated", GREEN, "calibrated on FY2018-21"))):
        v = [cells[str(k)][key] for k in kk]
        ax.bar(np.array(kk) + (j - .5) * .38, [100 * a["est"] for a in v], .38, color=c, label=nm, yerr=100 * np.array([[a["est"] - a["lo"] for a in v], [a["hi"] - a["est"] for a in v]]), capsize=2.5)
    ax.axhline(68, color="black", ls="--", lw=1); ax.set_title(lab, fontsize=8); ax.set_xticks(kk); ax.set_xlabel("Years ahead"); ax.set_ylim(0, 100); ax.grid(axis="y", alpha=.25)
axs[0].set_ylabel("Share inside the interval (%), FY2022-25"); axs[0].legend(frameon=False, fontsize=6.5, loc="upper left")
fig.tight_layout(); fig.savefig(TMP / "c6.png", dpi=170); plt.close(fig)

# --------------------------------------------------------------------- story
now = dt.datetime.now().strftime("%d %b %Y, %H:%M")
S = []
S += [Paragraph("ARIA equity research: validation summary", ParagraphStyle("T", parent=H1, fontSize=19)),
      Paragraph(f"Point-in-time backtest of ARIA's forecasts, target prices and recommendations against what actually happened. Generated {now} (IST) from "
                f"{n_all:,} NSE/BSE companies. Figures are as of this run and will move slightly as the last companies finish. Intervals are 95% unless stated, "
                "obtained by resampling whole companies (2,000 draws).", P), Spacer(1, 6)]

rev = E1["revenue"]
r12 = HL[12]
bsw = WZ[12]["buy_minus_sell"]
sk1 = skill(rev[1]) if 1 in rev else np.nan
skill_rng = [skill(E1[ln][k]) for ln in ("revenue", "ebitda") for k in (1, 3, 5) if k in E1[ln]]
v_fc = (f"<b>Financial forecasting: modest improvement over naive.</b> The base case beats 'carry the last value forward' by a skill of {sk1:+.2f} at one year ahead "
        f"(range {min(skill_rng):+.2f} to {max(skill_rng):+.2f} across revenue and EBITDA at 1, 3 and 5 years). Typical misses are large ({pct(num(rev[1][3]), 0)} of revenue at one year, "
        f"{pct(num(rev[5][3]), 0) if 5 in rev else 'n/a'} at five).")
c_buy = r12["per_rating"]["BUY"]["median_excess"]
v_rec = (f"<b>Recommendations: edge not demonstrated.</b> The 12-month hit rate is {cis(r12['hit']['aria'])}, only {pp(r12['hit']['paired_vs']['random_same_mix']['est'])} "
         f"(95% CI {pp(r12['hit']['paired_vs']['random_same_mix']['lo'])} to {pp(r12['hit']['paired_vs']['random_same_mix']['hi'])}) above random calls with the same mix, and "
         f"{abs(100 * r12['hit']['paired_vs']['always_SELL']['est']):.1f}pp below simply saying SELL on everything. BUY calls' median excess return is {cis(c_buy, 1, True)}, a CI that "
         f"{'includes' if c_buy['lo'] <= 0 <= c_buy['hi'] else 'excludes'} zero. On a common 3-class scoring ARIA is less accurate ({pct(r12['classes']['accuracy']['est'])}) than always predicting the majority outcome ({pct(r12['classes']['majority_accuracy'])}).")
v_rk = (f"<b>Ranking: weak signal.</b> BUY &gt; HOLD &gt; SELL in median excess return at every horizon (at 3 months the differences are within the noise), and the BUY-minus-SELL spread is statistically positive "
        f"({cis(bsw, 1, True)} per 12 months, outliers clipped), but it is driven by a few years (FY2020-21), shrinks to roughly half in liquid stocks, "
        f"and the rank correlation of upside with realised excess return is only {sp[12]:.2f}.")
S += [box([Paragraph("Overall verdict", ParagraphStyle("VT", parent=H2, spaceBefore=0)), Paragraph(v_fc, BOX), Spacer(1, 3), Paragraph(v_rec, BOX), Spacer(1, 3), Paragraph(v_rk, BOX)],
          bg="#fbf4e6", border=AMBER), Spacer(1, 6)]

S += [Paragraph("1. Key findings", H1)]
bullets = [
    f"<b>Financial forecasts (Experiment 1).</b> ARIA's base-case revenue forecast misses the later reported figure by a typical <b>{pct(num(rev[1][3]), 0)}</b> at one year ahead, "
    f"<b>{pct(num(rev[3][3]), 0) if 3 in rev else 'n/a'}</b> at three and <b>{pct(num(rev[5][3]), 0) if 5 in rev else 'n/a'}</b> at five (median absolute log error). 'Skill vs naive' (section 3) says whether that is better than a trivial guess.",
    f"<b>Scenario coverage.</b> The reported revenue fell between ARIA's bear and bull cases only {min(num(rev[k][5].split('/')[1]) for k in (1, 3, 5) if k in rev):.0f}-{max(num(rev[k][5].split('/')[1]) for k in (1, 3, 5) if k in rev):.0f}% of the time. "
    "That is a description of the scenario spread, not a failed 68% calibration: the cases were never designed as a stated-probability interval (their spread equals ARIA's own Monte Carlo sigma, about +-1 sigma). "
    "Section 7 builds an empirically calibrated interval and tests it out of sample.",
    f"<b>Recommendations (Experiment 2).</b> Across {n_comp2:,} companies the hit rates are {pct(HL[3]['hit']['aria']['est'])} / {pct(HL[6]['hit']['aria']['est'])} / {pct(HL[12]['hit']['aria']['est'])} at 3 / 6 / 12 months, "
    f"against {pct(HL[3]['hit']['baseline']['random_same_mix'])} / {pct(HL[6]['hit']['baseline']['random_same_mix'])} / {pct(HL[12]['hit']['baseline']['random_same_mix'])} for random calls with the same mix. The edge over random is not significant at 3 months and small at 6 and 12.",
    f"<b>Why 'always SELL' scores well.</b> {pct(J['why_always_sell']['12']['all']['share_underperform'], 0)} of stock-years trail the Nifty over 12 months: the median stock lags a cap-weighted index "
    "(a few big winners lift the mean, most stocks lag the median). So hit rates must be read against the base rate of the same event, not against 50%.",
    f"<b>Target prices are far off.</b> Median absolute target-price error at 12 months is {pct(tp[12].tp_err_abs.median(), 0)}, with targets sitting {pct(abs(tp[12].tp_err_signed.median()), 0)} {'below' if tp[12].tp_err_signed.median() < 0 else 'above'} realised prices (ARIA's intrinsic value is usually below the market price).",
    "<b>Broker comparison.</b> No dataset of Indian brokerages' dated targets and ratings is available, so no head-to-head against brokers has been run (see section 8). Published academic studies are shown for context only.",
]
S += [Paragraph(b, BUL, bulletText="-") for b in bullets]

S += [Paragraph("2. Coverage", H2)]
rows = [["Outcome", "Companies", "Share"]] + [[LABEL.get(k, k), f"{v:,}", pct(v / n_all)] for k, v in sorted(status.items(), key=lambda kv: -kv[1])]
S += [tbl(rows, [105 * mm, 25 * mm, 22 * mm]), Paragraph(
    "Only 'Scored' companies enter the accuracy figures. Many NSE/BSE names are small, newly listed or delisted, so they lack the 3+ fiscal years of statements or price history a point-in-time test needs. "
    "Today's listings only, so survivorship flatters every result.", SM)]

# ---- experiment 1
S += [PageBreak(), Paragraph("3. Experiment 1: how accurate are ARIA's financial forecasts?", H1),
      Paragraph("For each past fiscal year-end (FY2018 to FY2025) ARIA's own bear/base/bull projections were rebuilt using only information public by then (annual results assumed available 90 days after year-end), "
                "then compared with what the company later reported. Typical miss = median absolute error of the base case.", P), Spacer(1, 4)]
skill_txt = (f"<b>How to read 'Skill vs naive'.</b> A naive guess needs no model: <i>rw</i> carries the last reported value forward, <i>cagr</i> continues the recent growth rate, <i>mr</i> assumes the margin returns to its own average. "
             "Skill = 1 - (ARIA's typical miss / the naive guess's typical miss). <b>+0.20 means ARIA's typical error is 20% smaller than the naive one; 0 means no better; negative means worse.</b> "
             f"At one year ahead revenue skill vs 'rw' is {sk1:+.2f}, i.e. ARIA is only about {abs(100 * sk1):.0f}% better than repeating last year's figure; the advantage grows with the horizon "
             f"({skill(rev[5]):+.2f} at five years) because last year's value becomes a poor guess for a growing company.") if 1 in rev and 5 in rev else ""
S += [box([Paragraph(skill_txt, BOX)], bg="#eef3ee"), Spacer(1, 5)]
hdr = ["Line", "Years ahead", "Companies", "Typical miss", "Bias (base)", "Between bear and bull (scenario coverage)", "Skill vs naive*"]
rows = [hdr]
for ln, lab in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("margin", "EBITDA margin (pp)"), ("eps", "EPS (banks)")):
    for k in (1, 3, 5):
        if k in E1[ln]:
            c = E1[ln][k]
            band = c[5].split("/")[1].strip() if "/" in c[5] else c[5]
            rows.append([lab, str(k), c[1], c[3] if ln == "margin" else f"{100 * num(c[3]):.0f}%", c[2].split("[")[0].strip(), band, c[7].split(";")[0].strip()])
S += [tbl(rows, [30 * mm, 18 * mm, 22 * mm, 22 * mm, 24 * mm, 36 * mm, 24 * mm], font=7.4, wrap=True),
      Paragraph("*Skill vs the main naive baseline (rw for levels, mr for margin). Bias is ln(forecast/actual): +0.10 means about 10% too high; margin bias is in percentage points. "
                "Ten-year horizons cannot be validated with 12 years of statements. 'Between bear and bull' is the share of reported figures that landed between the two cases.", SM), Spacer(1, 4),
      Image(str(TMP / "c1.png"), width=165 * mm, height=61 * mm), Image(str(TMP / "c1b.png"), width=165 * mm, height=54 * mm),
      Paragraph("Top: typical miss (left) and bias with 90% confidence intervals (right). Bottom: skill against the naive guess; green is better than naive, red worse.", SM)]

# ---- experiment 2
S += [PageBreak(), Paragraph("4. Experiment 2: would ARIA's report have worked as an investment call?", H1),
      Paragraph("For every scored company and year, ARIA's own valuation rule (unchanged code) produced a target price and a BUY / HOLD / SELL call from point-in-time data. "
                "Outcomes use prices 3, 6 and 12 months later, total return (dividends included) versus the Nifty 50 price index. Rules were fixed before looking at results.", P),
      Paragraph("<b>What counts as a success.</b> BUY succeeds if the stock beats the Nifty (excess &gt; 0). SELL succeeds if it trails the Nifty (excess &lt; 0). "
                "<b>HOLD succeeds if the stock stays within +-5 / 7.5 / 10 percentage points of the Nifty</b> at 3 / 6 / 12 months, i.e. 'no material over- or under-performance'. "
                "BUY/SELL are sign tests and HOLD is a band test, so their hit rates are not comparable; each is shown against the base rate of the same event for all stocks. "
                "A single common scoring (3 classes, same threshold X) is given in section 5.", P), Spacer(1, 4)]
mix_txt = ", ".join(f"{k} {pct(v, 0)}" for k, v in mix.items())
S += [Paragraph(f"Mix of calls (12-month rows): {mix_txt}. Target price withheld by the model in about {pct(J['controls']['share_target_withheld'], 0)} of cases (the call is then made from the nearest edge of the fair-value range).", P), Spacer(1, 4)]
rows = [["Measure", "3 months", "6 months", "12 months"],
        ["Rows (company-years)"] + [f"{HL[h]['n_obs']:,}" for h in HS],
        ["ARIA hit rate [95% CI]"] + [cis(HL[h]["hit"]["aria"]) for h in HS],
        ["Random calls, same mix"] + [pct(HL[h]["hit"]["baseline"]["random_same_mix"]) for h in HS],
        ["Always BUY (= buy-and-hold)"] + [pct(HL[h]["hit"]["baseline"]["always_BUY"]) for h in HS],
        ["Always SELL"] + [pct(HL[h]["hit"]["baseline"]["always_SELL"]) for h in HS],
        ["Median excess return: BUY [95% CI]"] + [cis(HL[h]["per_rating"]["BUY"]["median_excess"], 1, True) for h in HS],
        ["Median excess return: HOLD [95% CI]"] + [cis(HL[h]["per_rating"]["HOLD"]["median_excess"], 1, True) for h in HS],
        ["Median excess return: SELL [95% CI]"] + [cis(HL[h]["per_rating"]["SELL"]["median_excess"], 1, True) for h in HS],
        ["Median |target - price| / price"] + [pct(tp[h].tp_err_abs.median(), 0) for h in HS],
        ["Rank corr. (upside vs excess return)"] + [f"{sp[h]:.2f}" for h in HS]]
S += [tbl(rows, [58 * mm, 39 * mm, 39 * mm, 39 * mm], font=7.8), Spacer(1, 4),
      Image(str(TMP / "c2.png"), width=165 * mm, height=59 * mm),
      Paragraph("Hit rate of each call with 95% CI; the dashed line is the hit rate of the same event if every stock were scored (what a naive rule would get). A bar above its dashed line is the only sign of skill.", SM),
      Image(str(TMP / "c3.png"), width=165 * mm, height=56 * mm),
      Paragraph("Median excess return after each type of call, with 95% CI (bars whose interval crosses zero are not distinguishable from the market).", SM)]

# ---- robustness
S += [PageBreak(), Paragraph("5. Statistical robustness", H1),
      Paragraph("<b>Method.</b> Every ARIA-minus-baseline figure is a <b>paired</b> difference on the same rows. 95% CIs resample whole companies (2,000 draws, seed 0). "
                "p-values are clustered-bootstrap two-sided; a second test shuffles the calls among companies within each origin year (2,000 permutations). "
                "'Random' draws calls 1,000 times with ARIA's own BUY/HOLD/SELL mix. Mean excess returns are dominated by a few small-cap multi-baggers, so mean-based figures below are also given with the excess return clipped at its 1st/99th percentile ('clipped'); medians are unaffected.", P),
      Paragraph("5.1 ARIA minus each baseline", H2)]
rows = [["ARIA minus ...", "3 months", "6 months", "12 months"]]
for k, lab in (("random_same_mix", "random calls, same mix"), ("always_BUY", "always BUY (buy-and-hold)"), ("always_SELL", "always SELL"), ("always_HOLD", "always HOLD")):
    rows.append([f"Hit rate (pp): {lab}"] + [dci(HL[h]["hit"]["paired_vs"][k]) for h in HS])
for k, lab in (("random_same_mix", "random calls, same mix"), ("always_BUY (= buy-and-hold)", "buy-and-hold every stock"), ("always_SELL", "always SELL")):
    rows.append([f"Signed excess return (pp, clipped): {lab}"] + [dci(WZ[h]["signed_excess"]["paired_vs"][k]) for h in HS])
rows.append(["Permutation p, hit rate vs same-year mix"] + [f"{HL[h]['hit']['perm_year']['p']:.3f}" for h in HS])
S += [tbl(rows, [58 * mm, 39 * mm, 39 * mm, 39 * mm], font=7.2, wrap=True),
      Paragraph("Signed excess = +excess return for a BUY, -excess for a SELL, 0 for a HOLD (a long/short book of the calls). Always-SELL's positive signed return and higher hit rate reflect the base rate, see 5.3.", SM),
      Image(str(TMP / "c4.png"), width=165 * mm, height=59 * mm), Paragraph("5.2 Each call separately (12 months)", H2)]
rows = [["Call", "Rows (companies)", "Hit rate [95% CI]", "Same event, all stocks", "Hit minus base (pp)", "Median excess [95% CI]", "Mean excess, clipped [95% CI]"]]
for k in ("BUY", "HOLD", "SELL"):
    v, w = HL[12]["per_rating"][k], WZ[12]["per_rating"][k]
    rows.append([k, f"{v['n_obs']:,} ({v['n_companies']:,})", cis(v["hit"]), pct(v["hit_base_rate_all_stocks"]), dci(v["hit_minus_base_rate"]).split(" p ")[0], cis(v["median_excess"], 1, True), cis(w["mean_excess"], 1, True)])
rows.append(["BUY minus SELL", "", "", "", "", "", f"{cis(WZ[12]['buy_minus_sell'], 1, True)}; raw {cis(HL[12]['buy_minus_sell'], 1, True)}"])
S += [tbl(rows, [20 * mm, 25 * mm, 28 * mm, 22 * mm, 30 * mm, 28 * mm, 33 * mm], font=7, wrap=True)]

S += [Paragraph("5.3 Why 'always SELL' scores 53-56%", H2)]
wa = J["why_always_sell"]
bysz = "; ".join(f"{k} {pct(v['share_underperform'], 0)}" for k, v in wa["12"]["by_size"].items())
S += [box([Paragraph(
    f"Over 12 months <b>{pct(wa['12']['all']['share_underperform'])}</b> of all stock-years trail the Nifty (95% CI {cis(wa['12']['sell_hit_ci'])}), "
    f"{pct(wa['6']['all']['share_underperform'])} over 6 months and {pct(wa['3']['all']['share_underperform'])} over 3 months. The median stock returned {pct(wa['12']['all']['median_stock_total_return'])} against {pct(wa['12']['all']['median_nifty_return'])} for the median Nifty window "
    f"(median excess {pct(wa['12']['all']['median_excess'], 1)}), while the <i>mean</i> excess is {pct(wa['12']['all']['mean_excess'], 1)}: returns are heavily right-skewed, a handful of multi-baggers lift the mean while most stocks lag a cap-weighted index. "
    f"Share trailing the Nifty by size bucket: {bysz}; the universe is {pct(J['controls']['size_mix'].get('small', 0), 0)} small-cap, where lagging is most common. Adding dividends to the index (the TRI proxy) raises the share to {pct(wa['12']['all']['share_underperform_tri_proxy'])}. "
    "Survivorship pushes the other way (failed stocks are missing), so the true base rate is if anything higher. Conclusion: a SELL hit rate of 53-56% is a base rate, not skill; the fair test is ARIA's SELL hit rate against the same event across all stocks.", BOX)], bg="#eef3ee"),
      Paragraph("5.4 Benchmark and return methodology", H2),
      Paragraph(J["tri"] + " The comparison below repeats the 12-month results under four return definitions; the qualitative conclusions are the same under each.", P)]
rows = [["Excess-return definition (12 months)", "Rows", "ARIA hit rate [95% CI]", "Hit minus random (pp)", "Median excess: BUY / SELL", "BUY minus SELL, mean [95% CI]"]]
for dk, lab in (("headline", "Total return vs Nifty price return (main run)"), ("pr_vs_pr", "Price return vs price return (like for like)"), ("tr_vs_tri", "Total return vs Nifty TRI proxy (+1.3%/yr)"),
                ("alpha", "Beta-adjusted alpha vs TRI proxy"), ("winsor", "Main run, clipped at 1st/99th percentile")):
    c = J["by_definition"][dk]["12"]
    rows.append([lab, f"{c['n_obs']:,}", cis(c["hit"]["aria"]), dci(c["hit"]["paired_vs"]["random_same_mix"]).split(" p ")[0],
                 f"{cis(c['per_rating']['BUY']['median_excess'], 1, True)} / {cis(c['per_rating']['SELL']['median_excess'], 1, True)}", cis(c["buy_minus_sell"], 1, True)])
S += [tbl(rows, [46 * mm, 13 * mm, 28 * mm, 22 * mm, 38 * mm, 29 * mm], font=7, wrap=True),
      Paragraph(f"Alpha = stock total return - [rf + beta x (TRI proxy - rf)] with a constant 6.5% risk-free rate and a raw OLS beta on the 260 weekly returns before each origin (cached prices; available for {pct(J['beta_coverage'], 0)} of rows). "
                "The price-return and TRI-proxy versions bracket the headline numbers.", SM),
      Paragraph("5.5 One common outcome definition: 3-class accuracy (12 months)", H2)]
cl = HL[12]["classes"]
rows = [["ARIA call \\ realised", f"Outperform (> +{100 * HL[12]['X']:.0f}pp)", "In line", f"Underperform (< -{100 * HL[12]['X']:.0f}pp)", "Precision"]]
for i, k in enumerate(("BUY", "HOLD", "SELL")):
    rows.append([k] + [f"{v:,}" for v in cl["confusion"][i]] + [pct(cl["precision"][i])])
rows.append(["Recall"] + [pct(x) for x in cl["recall"]] + [""])
S += [tbl(rows, [36 * mm, 38 * mm, 28 * mm, 42 * mm, 26 * mm], font=7.6),
      Paragraph(f"Realised class uses the same X as the HOLD band, fixed in advance. Class shares: {', '.join(f'{n} {pct(s_, 0)}' for n, s_ in zip(cl['labels'], cl['outcome_share']))}. "
                f"<b>Accuracy {cis(cl['accuracy'])}; always predicting the majority class ('{cl['majority_class']}') gets {pct(cl['majority_accuracy'])}; random calls with ARIA's mix {pct(cl['random_same_mix_accuracy'])}. "
                f"ARIA minus majority baseline: {dci(cl['accuracy_minus_majority'])}.</b> "
                f"At 3 and 6 months the same gap is {dci(HL[3]['classes']['accuracy_minus_majority'], 1).split(' p ')[0]} and {dci(HL[6]['classes']['accuracy_minus_majority'], 1).split(' p ')[0]}. "
                "ARIA beats random assignment but not the trivial majority-class rule, because the market's skew makes 'underperform' the most common outcome.", SM)]

S += [Paragraph("5.6 Portfolio-style evaluation (12 months, equal weight, rebalanced yearly)", H2),
      Paragraph("Long every BUY and short every SELL at each origin year (hypothetical: borrowing is unavailable for most Indian cash stocks); also long-BUY-only against the Nifty. Costs are charged as a round-trip rate on the fraction of the book replaced (turnover; the first year is a full build). "
                "The cost-adjusted CI is the gross bootstrap CI shifted by the average cost.", P), Image(str(TMP / "c5.png"), width=165 * mm, height=54 * mm)]
rows = [["Strategy / period", "Years > 0", "Avg turnover", "Gross, raw", "Net of 0 bps (clipped)", "25 bps", "50 bps", "100 bps"]]
for name, short in (("long BUY / short SELL", "Long-short"), ("long BUY only, excess vs Nifty", "Long BUY vs Nifty")):
    for sn, rr in J["portfolio"]["winsor"]["strategies"][name].items():
        raw = J["portfolio"]["headline"]["strategies"][name][sn]
        rows.append([f"{short}, {sn}", f"{rr['positive_years']}/{len(rr['years'])}", pct(rr["turnover_avg"], 0), pct(raw["gross_by_year_mean"], 1)] + [cis(rr["cost_bps"][str(c)], 1) for c in (0, 25, 50, 100)])
S += [tbl(rows, [37 * mm, 15 * mm, 17 * mm, 18 * mm, 30 * mm, 20 * mm, 20 * mm, 20 * mm], font=6.8, wrap=True),
      Paragraph("Costs barely move the result because the gross spread is large relative to 25-100 bps x turnover; small-cap round trips can cost more than 100 bps and are not modelled beyond this sweep. Yearly figures swing from -6% to +171% (raw): the average is driven by FY2020-21.", SM),
      Paragraph("Liquidity filter and chronological split", H2)]
rows = [["12-month universe", "Rows", "Hit rate [95% CI]", "Hit minus random (pp)", "BUY minus SELL, raw [95% CI]", "Long-short, clipped, 50 bps"]]
for name, v in J["liquidity"].items():
    c = v["core_12m"]
    ls = v["portfolio_w"]["strategies"]["long BUY / short SELL"]["all years"]["cost_bps"]["50"]
    rows.append([name if name != "all" else "all stocks", f"{c['n_obs']:,}", cis(c["hit"]["aria"]), dci(c["hit"]["paired_vs"]["random_same_mix"]).split(" p ")[0], cis(c["buy_minus_sell"], 1, True), cis(ls, 1, True)])
S += [tbl(rows, [44 * mm, 14 * mm, 28 * mm, 26 * mm, 34 * mm, 30 * mm], font=7, wrap=True), Spacer(1, 5)]
rows = [["Chronological split", "Rows", "Hit rate [95% CI]", "Hit minus random (pp) [CI]", "BUY minus SELL [95% CI]", "3-class accuracy minus majority (pp)"]]
for h in HS:
    for nm, lab in (("early", "FY2018-21"), ("late", "FY2022-25")):
        c = J["oos"][str(h)][nm]
        rows.append([f"{h}m, {lab}", f"{c['n_obs']:,}", cis(c["hit"]["aria"]), dci(c["hit"]["paired_vs"]["random_same_mix"]).split(" p ")[0], cis(c["buy_minus_sell"], 1, True), dci(c["classes"]["accuracy_minus_majority"]).split(" p ")[0]])
S += [tbl(rows, [26 * mm, 14 * mm, 28 * mm, 38 * mm, 32 * mm, 38 * mm], font=7, wrap=True),
      Paragraph("Nothing is fitted on either half (rules and bands were fixed in advance), so this tests stability over time. The edge over random is absent in FY2018-21 at 3 and 6 months and appears in FY2022-25; the BUY-minus-SELL spread is positive in both halves. "
                "The 68%-interval scale in section 7 is the only quantity fitted on early data.", SM)]

# ---- data controls
ct = J["controls"]
S += [Paragraph("6. Data controls", H2),
      Paragraph("<b>Not controlled:</b> delisted and failed companies are absent (survivorship flatters every strategy); statements are screener.in's restated figures with an assumed 90-day publication lag; "
                "sector labels and the risk-free rate, equity risk premium and terminal growth are today's values applied to the past; the Nifty TRI is a proxy; "
                "overlapping origins share market shocks that company-level bootstrapping cannot capture; no borrow, impact or tax is modelled.", P),
      Paragraph(f"<b>Quantified:</b> {pct(ct['share_origins_unclassified_sector'], 0)} of origins have no usable sector label; {pct(ct['share_origins_structural_break'], 0)} are flagged structural break and {pct(ct['share_origins_short_history'], 0)} short history; "
                f"the size mix is {pct(ct['size_mix'].get('small', 0), 0)} small, {pct(ct['size_mix'].get('mid', 0), 0)} mid, {pct(ct['size_mix'].get('large', 0), 0)} large.", P)]
rows = [["12-month slice", "Rows", "Hit rate [95% CI]", "Hit minus random (pp)", "BUY minus SELL, raw [95% CI]"]]
for k, c in ct["sensitivity"].items():
    rows.append([k, f"{c['n_obs']:,}", cis(c["hit"]["aria"]), dci(c["hit"]["paired_vs"]["random_same_mix"]).split(" p ")[0], cis(c["buy_minus_sell"], 1, True)])
for k, c in ct["by_size"].items():
    if not c.get("suppressed"):
        rows.append([f"{k}-cap only", f"{c['n_obs']:,}", cis(c["hit"]["aria"]), dci(c["hit"]["paired_vs"]["random_same_mix"]).split(" p ")[0], cis(c["buy_minus_sell"], 1, True)])
S += [tbl(rows, [62 * mm, 16 * mm, 30 * mm, 32 * mm, 36 * mm], font=7, wrap=True),
      Paragraph("Dropping structural-break and short-history origins leaves both the hit-rate edge and the spread unchanged; dropping unclassified sectors leaves the hit-rate edge but shrinks the raw spread. The signal is strongest in small caps and weak in large caps (hit minus random not significant).", SM)]

# ---- scenario coverage / calibrated interval
S += [PageBreak(), Paragraph("7. Scenario coverage and an empirically calibrated interval", H1),
      Paragraph("The bear and bull cases were not designed as a stated-probability interval; their spread equals ARIA's own Monte Carlo sigma, so they behave like a roughly +-1 sigma scenario range. 'Scenario coverage' (the share of reported figures between the cases) is therefore a description, not a calibration failure of a 68% interval. "
                "To give a usable interval, the log-width of [bear, bull] around the base case is multiplied by a factor chosen on early origins (FY2018-21) so that 68% of reported figures fall inside, and that interval is then scored on FY2022-25 origins it never saw.", P),
      Image(str(TMP / "c6.png"), width=165 * mm, height=59 * mm)]
rows = [["Line", "Years", "Scale s (fit FY18-21)", "Test rows", "As shipped [95% CI]", "Calibrated [95% CI]", "Single s per line [95% CI]"]]
for ln, lab in (("revenue", "Revenue"), ("ebitda", "EBITDA"), ("margin", "Margin"), ("eps", "EPS (banks)")):
    for k, c in IV["cells"][ln].items():
        if "test_calibrated" in c:
            rows.append([lab, k, f"{c['scale']:.1f}x", f"{c['n_test']:,}", cis(c["test_uncalibrated"], 0), cis(c["test_calibrated"], 0), cis(c.get("test_pooled_scale"), 0)])
S += [tbl(rows, [24 * mm, 12 * mm, 28 * mm, 20 * mm, 30 * mm, 30 * mm, 32 * mm], font=7, wrap=True),
      Paragraph(f"Scale s multiplies the log distance from base to each case (margin: the percentage-point distance); s = 1 is the shipped cases. Revenue cases are very tight (s of 6-13x needed) because they only vary the growth path slightly, whereas EBITDA and margin cases need about 2-3x. "
                f"Out of sample the calibrated interval covers close to the 68% target (typically within about 9 points), where the shipped cases cover 5-45%. One scale per line over all horizons (last column) is worse than a scale per horizon. "
                f"{IV['n_dropped_degenerate_cases']:,} observations were dropped because the cases were not ordered bear &lt; base &lt; bull. Years 5 and EPS beyond 3 years have too few later origins to score.", SM)]

# ---- brokers (larger text, more spacing)
S += [PageBreak(), Paragraph("8. Comparison with brokerages", H1), Spacer(1, 4),
      Paragraph("<b>What can and cannot be claimed.</b> A fair head-to-head needs brokerages' own dated targets and ratings for the same stocks and dates. No free, permitted dataset of that kind was found, "
                "and nothing was scraped or invented. The table below puts ARIA's results next to <b>published academic studies of analyst target-price accuracy</b>. These use different markets, periods, sample "
                "selections and definitions, so they are context, not a ranking.", BIG), Spacer(1, 6)]
rows = [["Measure", "ARIA (this study, 12 months)", "Published evidence (analysts)"],
        ["Share of targets met at 12 months", f"{pct(tp_met_12)} of upside targets (price at or above target); ARIA's targets are often below the market price", "38% (US, 2000-2009, Bradshaw, Brown & Huang 2013); 63% of targets achieved within 12 months (Indian sample, 2024 study, per its abstract)"],
        ["Average absolute target-price error", f"median {pct(tp[12].tp_err_abs.median(), 0)}, mean {pct(tp[12].tp_err_abs.mean(), 0)}", "about 45% on average (US, Bradshaw, Brown & Huang 2013)"],
        ["Implied return minus actual return", f"mean {100 * imp_mean:+.0f} pp, median {100 * imp_med:+.0f} pp (forecast minus actual; negative = ARIA's implied return was below what happened)", "analysts' implied returns exceeded actual by about 15 pp on average (US)"],
        ["Recommendation hit ratio", f"BUY {cis(HL[12]['per_rating']['BUY']['hit'], 0)}, overall {cis(HL[12]['hit']['aria'], 0)}", "hit ratio not above 50% in a study of 1,000+ Indian recommendations (IIM Bangalore); analysts skew to BUY"]]
rows = [[Paragraph(str(c), BIGHW if i == 0 else BIGCELL) for c in r] for i, r in enumerate(rows)]
t = tbl(rows, [40 * mm, 66 * mm, 70 * mm], font=9)
t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("ALIGN", (1, 0), (-1, -1), "LEFT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
S += [t, Spacer(1, 8),
      Paragraph("Sources: Bradshaw, Brown &amp; Huang (2013), <i>Do sell-side analysts exhibit differential target price forecasting ability?</i>, Review of Accounting Studies 18(4), "
                "ideas.repec.org/a/spr/reaccs/v18y2013i4d10.1007_s11142-012-9216-5.html; Indian target-price accuracy study (Cogent Economics &amp; Finance, 2024), ideas.repec.org/a/taf/oaefxx/v12y2024i1p2423261.html; "
                "IIM Bangalore, <i>Investment value of analyst recommendations: evidence from the Indian stock market</i>, research.iimb.ac.in/fac_pubs/406. Figures are taken from abstracts/summaries and should be checked against the full papers before citing.", BIGS),
      Spacer(1, 8),
      Paragraph("<b>To run a real head-to-head</b>, supply a CSV of brokerage calls (columns: symbol, date, broker, rating, target, horizon) and run "
                "<font face='Courier'>python scripts/scenario_report_validation.py --brokers broker.csv</font>. It scores the brokers with the same outcome rules and prints them beside ARIA on the same symbols.", BIG),
      Spacer(1, 6), Paragraph("9. Limitations", H2)]
for b in ["Survivorship: only today's listed companies are included; delisted failures are missing, which flatters both ARIA and any benchmark.",
          "Statements are restated figures from screener.in (original as-first-reported values are not available) with an assumed 90-day publication lag; sector labels and risk-free/equity-premium inputs are today's.",
          "Experiment 2 tests ARIA's intrinsic-value call only; the live report also uses peer multiples and an LLM debate that cannot be reconstructed historically.",
          "Overlapping origins and horizons make the effective sample much smaller than the row counts; confidence intervals resample companies, not calendar time, so they are if anything too narrow (see the yearly spread in 5.6).",
          "The Nifty TRI could not be downloaded; a price-plus-1.3%-dividend proxy is used and results are shown under four return definitions.",
          "Published-study figures come from different markets and definitions and are shown as context, not as a like-for-like comparison."]:
    S.append(Paragraph(b, BUL, bulletText="-"))

doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                        title="ARIA equity research: validation summary", author="ARIA")
doc.build(S)
print("wrote", OUT, f"({n_all} companies, {n_comp2} in experiment 2)")
