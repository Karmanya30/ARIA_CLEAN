"""
Render a stored report (the dict from ``report.build_report``) as one self-contained HTML document:
inline CSS, inline SVG charts, print styles (browser "Save as PDF" gives a clean PDF). The same
document is shown inside the app (sandboxed iframe) and offered as the download, so there is one
renderer and the two can never drift.

Every figure is tagged with what it is -- ACTUAL (reported), CALCULATED (derived by code), ESTIMATE
(model forecast), ASSUMPTION (a model input), SOURCE TEXT (quoted from a source) or AI INTERPRETATION
(written by the language model from cited figures/sources) -- so facts, forecasts and opinion are never
blurred. All dynamic text is HTML-escaped.
"""
from __future__ import annotations

import re
from html import escape

from modules.equity_research.intelligence.comps import VERDICT_BANDS, group_name
from modules.equity_research.intelligence.facts import fmt

_TAGS = {
    "raw": ("ACTUAL", "t-actual"), "actual": ("ACTUAL", "t-actual"), "calculated": ("CALCULATED", "t-calc"),
    "estimate": ("ESTIMATE", "t-est"), "assumption": ("ASSUMPTION", "t-assume"), "ai": ("AI INTERPRETATION", "t-ai"),
    "source": ("SOURCE TEXT", "t-src"), "rule": ("RULE-BASED", "t-calc"), "llm": ("AI INTERPRETATION", "t-ai"),
    "template": ("CALCULATED", "t-calc"),
}
RATING_CLASS = {"BUY": "r-buy", "HOLD": "r-hold", "SELL": "r-sell"}

CSS = """
:root{--ink:#0f1b2d;--muted:#5b6778;--faint:#94a0b1;--line:#e3e8ef;--bg:#f4f6fa;--card:#fff;--navy:#0b1f3a;--accent:#1d4ed8;
--green:#0f8a5f;--red:#c62828;--amber:#b45309;--est:#7c3aed}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.page{max-width:1020px;margin:0 auto;padding:0 0 40px}
.cover{background:linear-gradient(135deg,#0b1f3a,#16386b);color:#fff;padding:28px 34px 22px}
.cover h1{margin:0;font-size:28px;letter-spacing:-.01em}.cover .sub{opacity:.85;margin-top:2px}
.cover .meta{display:flex;flex-wrap:wrap;gap:6px 26px;margin-top:14px;font-size:12.5px;opacity:.92}
.cover .meta b{display:block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;opacity:.7;font-weight:600}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:11.5px;font-weight:700;background:rgba(255,255,255,.16)}
.pill.ok{background:#0f8a5f}.pill.warn{background:#b45309}
.legend{background:#fff;border-bottom:1px solid var(--line);padding:8px 34px;font-size:11.5px;color:var(--muted)}
.legend .tag{margin-right:4px}
main{padding:0 34px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:18px 0;padding:18px 22px;page-break-inside:avoid}
h2{margin:0 0 4px;font-size:17px;letter-spacing:-.01em}h2 .n{color:var(--accent);margin-right:6px}
h3{margin:16px 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
p{margin:6px 0}.muted{color:var(--muted)}.small{font-size:12px}
.tag{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.06em;padding:1px 6px;border-radius:4px;vertical-align:middle;white-space:nowrap}
.t-actual{background:#e6f4ea;color:#166534}.t-calc{background:#e0ecff;color:#1e40af}.t-est{background:#f0e7ff;color:#6d28d9}
.t-assume{background:#fff4e0;color:#9a5b00}.t-ai{background:#fde7f3;color:#9d174d}.t-src{background:#eef1f5;color:#475569}
.summary{display:grid;grid-template-columns:260px 1fr;gap:20px}
.stance{border-radius:10px;padding:14px 16px;color:#fff;text-align:center}
.stance .big{font-size:22px;font-weight:800;letter-spacing:-.01em}.stance .lbl{font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.85}
.r-buy{background:var(--green)}.r-hold{background:#c47a08}.r-sell{background:var(--red)}.r-none{background:#64748b}
.stance dl{margin:10px 0 0;display:grid;grid-template-columns:1fr auto;gap:2px 10px;text-align:left;font-size:12.5px}.stance dt{opacity:.85}.stance dd{margin:0;font-weight:700}
ul{margin:6px 0 6px 18px;padding:0}li{margin:3px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:8px}
.tile{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:#fbfcfe}
.tile .v{font-size:16px;font-weight:700}.tile .l{font-size:11.5px;color:var(--muted)}.tile .p{font-size:10.5px;color:var(--faint)}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td.l,thead th.l{text-align:left}td.l{white-space:normal}
thead th{background:#f6f8fb;font-weight:700;color:#334155;border-bottom:2px solid var(--line)}
th.est,td.est{background:#faf7ff}th.est{color:var(--est)}td.est{font-style:italic}
.scroll{overflow-x:auto}table.tight th,table.tight td{padding:4px 5px;font-size:11.5px}table.wide th,table.wide td,table.wide td.l{padding:3px 3px;font-size:10.5px;white-space:nowrap}.median td,.median th{font-weight:700;background:#f6f8fb}
.heat td{text-align:center;font-weight:600}.base{outline:2px solid var(--ink);outline-offset:-2px}
.cases{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:8px 0}
.case{border:1px solid var(--line);border-radius:10px;padding:12px;text-align:center}.case .v{font-size:20px;font-weight:800}
.case.bear{border-top:4px solid var(--red)}.case.base{border-top:4px solid var(--accent)}.case.bull{border-top:4px solid var(--green)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.side{border-radius:10px;padding:10px 14px}.side.bull{background:#eaf7f1}.side.bear{background:#fdeeee}
.chip{display:inline-block;border:1px solid var(--line);background:#fff;border-radius:99px;padding:0 8px;margin:2px 3px 0 0;font-size:11px}
.callout{border-left:4px solid var(--accent);background:#eef3ff;padding:8px 12px;border-radius:6px;margin:8px 0}
.callout.warn{border-left-color:var(--red);background:#fdeeee}.callout.good{border-left-color:var(--green);background:#eaf7f1}
.quote{border-left:3px solid var(--line);margin:6px 0;padding:2px 10px;font-size:12.5px}.quote .meta{font-size:11px;color:var(--faint)}
.na{border:1px dashed var(--faint);border-radius:8px;padding:8px 12px;margin:8px 0;background:#fafbfc}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.chart{max-width:640px}.chart h4{margin:0 0 2px;font-size:12px;color:var(--muted)}
.check{margin:3px 0}.check.review b,.check.blocked b{color:var(--amber)}.finding{display:block;margin-left:18px;color:var(--muted);font-size:12px}
.bar{text-align:right;padding:8px 16px}.bar button{padding:6px 14px;border-radius:8px;border:1px solid #ccd4e3;background:#fff;cursor:pointer}.disc h3{text-transform:none;letter-spacing:0;color:var(--ink);font-size:13px}@page{size:A4;margin:12mm}@media print{.noprint{display:none}.disc{page-break-before:always}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}.disclaimer{font-size:11.5px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px;margin-top:8px}
.sev-high{color:var(--red);font-weight:700}.sev-medium{color:var(--amber);font-weight:700}
@media print{.scroll{overflow:visible}table th,table td,table.tight th,table.tight td,table.wide th,table.wide td,table.wide td.l{font-size:9px;padding:2px 3px}body{background:#fff}section{border-color:#ccc;break-inside:avoid}.cover{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@media (max-width:760px){.summary,.two,.cases{grid-template-columns:1fr}main{padding:0 12px}.cover{padding:20px 16px}}
"""


def tag(kind: str) -> str:
    label, cls = _TAGS.get(kind, (kind.upper(), "t-src"))
    return f'<span class="tag {cls}">{label}</span>'


def _e(x) -> str:
    return escape("" if x is None else str(x))


def _table(head: list[str], rows: list[list[str]], *, est_from: int | None = None, cls: str = "", text: tuple[int, ...] = ()) -> str:
    """``text`` lists the columns holding sentences: they left-align and wrap instead of staying on one line."""
    ths = "".join(f'<th class="{"est" if est_from is not None and i >= est_from else ""}{" l" if i == 0 or i in text else ""}">{h}</th>' for i, h in enumerate(head))
    trs = ""
    for r in rows:
        tds = "".join(f'<td class="{"est" if est_from is not None and i >= est_from else ""}{" l" if i == 0 or i in text else ""}">{c}</td>' for i, c in enumerate(r))
        trs += f"<tr>{tds}</tr>"
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>'


# ── SVG charts ─────────────────────────────────────────────────────────────
def bars(title: str, columns: list[str], values: list[float | None], unit: str, n_actual: int | None = None) -> str:
    """Bar chart; columns from ``n_actual`` on are estimates (hatched). Missing values leave a gap."""
    real = [v for v in values if v is not None]
    if not real:
        return ""
    w, h, pad_l, pad_b, pad_t = 460, 190, 10, 34, 20
    lo, hi = min(0.0, min(real)), max(0.0, max(real))
    span = (hi - lo) or 1.0
    bw = (w - pad_l) / len(values)
    y = lambda v: pad_t + (h - pad_b - pad_t) * (1 - (v - lo) / span)  # noqa: E731
    parts = ['<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             '<rect width="6" height="6" fill="#efe7ff"/><line x1="0" y1="0" x2="0" y2="6" stroke="#7c3aed" stroke-width="2"/></pattern></defs>']
    for i, (c, v) in enumerate(zip(columns, values)):
        x = pad_l + i * bw + bw * 0.16
        est = n_actual is not None and i >= n_actual
        if v is not None:
            top, base = y(max(v, 0)), y(min(v, 0))
            parts.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw * 0.68:.1f}" height="{max(base - top, 1):.1f}" '
                         f'fill="{"url(#hatch)" if est else "#1d4ed8"}" stroke="{"#7c3aed" if est else "none"}" rx="2"/>')
            parts.append(f'<text x="{x + bw * 0.34:.1f}" y="{top - 4:.1f}" font-size="9.5" text-anchor="middle" fill="#334155">{_e(fmt(v, unit))}</text>')
        parts.append(f'<text x="{x + bw * 0.34:.1f}" y="{h - 16}" font-size="9" text-anchor="middle" fill="#64748b">{_e(c[-8:] if len(c) > 9 else c)}</text>')
    parts.append(f'<line x1="{pad_l}" x2="{w}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#cbd5e1"/>')
    return f'<div class="chart"><h4>{_e(title)}</h4><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{_e(title)}">{"".join(parts)}</svg></div>'


def football(methods: list[dict], price: float | None, fair: float | None) -> str:
    if not methods:
        return ""
    pts = [m["low"] for m in methods] + [m["high"] for m in methods] + ([price] if price else [])
    lo, hi = min(pts), max(pts)
    pad = (hi - lo) * 0.06 or 1
    w, rowh = 620, 30
    x = lambda v: 170 + (v - lo + pad) / (hi - lo + 2 * pad) * (w - 190)  # noqa: E731
    h = rowh * len(methods) + 40
    out = []
    for i, m in enumerate(methods):
        yy = 14 + i * rowh
        out.append(f'<text x="0" y="{yy + 15}" font-size="11.5" fill="#0f1b2d">{_e(m["label"])}</text>')
        out.append(f'<rect x="{x(m["low"]):.1f}" y="{yy + 3}" width="{max(x(m["high"]) - x(m["low"]), 2):.1f}" height="18" rx="4" fill="#dbe7ff" stroke="#1d4ed8"/>')
        out.append(f'<rect x="{x(m["mid"]) - 1.5:.1f}" y="{yy}" width="3" height="24" fill="#0b1f3a"/>')
        out.append(f'<text x="{x(m["high"]) + 6:.1f}" y="{yy + 16}" font-size="10.5" fill="#475569">{_e(fmt(m["low"], "₹"))} – {_e(fmt(m["high"], "₹"))}</text>')
    for v, colour, label in ((price, "#c62828", "Price"), (fair, "#0f8a5f", "Fair value")):
        if v:
            out.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="6" y2="{h - 18}" stroke="{colour}" stroke-width="2" stroke-dasharray="4 3"/>')
            out.append(f'<text x="{x(v):.1f}" y="{h - 5}" font-size="10" text-anchor="middle" fill="{colour}">{label} {_e(fmt(v, "₹"))}</text>')
    return f'<svg viewBox="0 0 {w + 110} {h}" width="100%" role="img" aria-label="Valuation ranges by method">{"".join(out)}</svg>'


def heat(sens: dict, price: float | None) -> str:
    head = ["WACC \\ terminal growth"] + [f"{g * 100:.1f}%" for g in sens["tg_values"]]
    rows = []
    for i, w in enumerate(sens["wacc_values"]):
        cells = [f"<b>{w * 100:.1f}%</b>"]
        for j, v in enumerate(sens["prices"][i]):
            if v is None:
                cells.append('<span class="muted">n/a</span>')
                continue
            ratio = v / price if price else 1
            bg = "#bfe8d3" if ratio >= 1.2 else "#e3f5ec" if ratio >= 1 else "#fbe4e4" if ratio >= 0.8 else "#f5c2c2"
            cells.append(f'<span style="display:block;background:{bg};margin:-5px -8px;padding:5px 8px" class="{"base" if i == 2 and j == 2 else ""}">{_e(fmt(v, "₹"))}</span>')
        rows.append(cells)
    return _table(head, rows, cls="heat")


# ── sections ───────────────────────────────────────────────────────────────
def _stance_block(r: dict) -> str:
    s = r["stance"]
    cls = RATING_CLASS.get(s["rating"] or "", "r-none")
    if s["rating"]:
        fv = fmt(s["fair_value"], "₹") if s["fair_value"] is not None else "withheld"
        rng = f"{fmt(s['low'], '₹')} – {fmt(s['high'], '₹')}"
        body = (f'<div class="lbl">Model-implied view</div><div class="big">{_e(s["stance"])}</div><div class="lbl">rating {_e(s["rating"])}</div>'
                f'<dl><dt>Fair value</dt><dd>{_e(fv)}</dd><dt>Range</dt><dd>{_e(rng)}</dd><dt>Price</dt><dd>{_e(fmt(s["price"], "₹"))}</dd>'
                f'<dt>Upside</dt><dd>{_e(fmt(s["upside_pct"], "%"))}</dd><dt>Confidence</dt><dd>{_e((s["confidence"] or "").replace("_", " "))}</dd></dl>')
    else:
        body = '<div class="lbl">Model-implied view</div><div class="big">Not assessed</div><div class="lbl">no rating is given</div>'
    return f'<div class="stance {cls}">{body}</div>'


def _summary(r: dict) -> str:
    origin = r.get("narrative_origin", {}).get("thesis", "template")
    risks = [x for x in r["risks"] if x["origin"] == "rule"][:3] or r["risks"][:3]
    thesis = "".join(f"<li>{_e(t)}</li>" for t in r["thesis"]) or '<li class="muted">No thesis could be written from the available data.</li>'
    rk = "".join(f'<li><span class="sev-{_e(x["severity"])}">{_e(x["title"] or x["category"])}</span> {_e(x["detail"])}</li>' for x in risks) or '<li class="muted">No rule-based risk flags were raised.</li>'
    notes = "".join(f"<li>{_e(n)}</li>" for n in r["stance"]["notes"])
    return (f'<section><h2><span class="n">1</span>Summary</h2><div class="summary">{_stance_block(r)}<div>'
            f'<h3>Investment thesis {tag("ai" if origin == "llm" else "calculated")}</h3><ul>{thesis}</ul>'
            f'<h3>Key risks {tag("rule")}</h3><ul>{rk}</ul>{f"<h3>Why no point estimate</h3><ul>{notes}</ul>" if r["stance"]["withheld"] and notes else ""}'
            f'</div></div></section>')


def _executive(r: dict) -> str:
    tiles = "".join(f'<div class="tile"><div class="v">{_e(x["text"])}</div><div class="l">{_e(x["label"])}</div>'
                    f'<div class="p">{_e(x["period"])} {tag(x["kind"])}</div></div>' for x in r["snapshot"])
    drivers = "".join(f'<li>{_e(d["text"])} {tag(d["origin"])}</li>' for d in r["drivers"]) or '<li class="muted">No drivers could be identified from the data.</li>'
    v = r["valuation"]
    snap = "".join(f'<div class="tile"><div class="v">{_e(fmt(m["mid"], "₹"))}</div><div class="l">{_e(m["label"])}</div><div class="p">{tag("calculated")}</div></div>' for m in v["methods"])
    return (f'<section><h2><span class="n">2</span>Executive summary</h2><h3>Key drivers</h3><ul>{drivers}</ul>'
            f'<h3>Valuation snapshot</h3><div class="tiles">{snap or "<p class=muted>No valuation method could be computed.</p>"}</div>'
            f'<h3>Financial snapshot</h3><div class="tiles">{tiles or "<p class=muted>No validated statement data available.</p>"}</div></section>')


def _company(r: dict) -> str:
    c, n = r["cover"], r.get("narrative_origin", {})
    kind = "ai" if n.get("business") == "llm" else "source"
    team = c.get("management") or []
    lead = "" if team else "; ".join(c["leadership"])
    facts = "".join(f"<li><b>{k}:</b> {_e(v)}</li>" for k, v in (("Leadership", lead), ("Employees", f"{c['employees']:,}" if c["employees"] else None), ("Website", c["website"])) if v)
    na = "".join(f'<div class="na"><b>{_e(x["item"])}.</b> {_e(x["reason"])}</div>' for x in r["not_available"] if x["item"].startswith(("Business segments", "Customer", "Shareholding")))
    return (f'<section><h2><span class="n">3</span>Company overview</h2><h3>Business description {tag(kind)}</h3><p>{_e(r["business"])}</p>'
            f'<ul>{facts}</ul>{_management(team)}{_ownership(r)}{_wiki(r, 'Company')}<h3>Not available from the configured sources</h3>{na}</section>')


def _management(team: list[dict]) -> str:
    if not team:
        return ""
    def pay(m: dict) -> str:
        if not m.get("pay_cr"):
            return ""
        return fmt(m["pay_cr"], "₹ Cr") + (f" (FY{m['pay_year']})" if m.get("pay_year") else "")
    rows = [[_e(m["name"]), _e(m["title"]), _e(m.get("age") or ""), _e(pay(m))] for m in team]
    return (f'<h3>Key management {tag("source")}</h3>{_table(["Name", "Designation", "Age", "Total pay"], rows, text=(1,))}'
            '<p class="muted small">Source: Yahoo Finance; pay as reported there, blank where not reported.</p>')


def _industry(r: dict) -> str:
    comps, cp = r["valuation"]["comps"], r.get("competitive")
    tbl = ""
    if cp and cp.get("rows"):
        pct = lambda v: fmt(v * 100, "%") if v is not None else "n/a"  # noqa: E731
        rows = []
        for p in cp["rows"]:
            cells = [_e(p["name"]), _e(fmt(p["mcap_cr"], "₹ Cr")), _e(fmt(p["revenue_cr"], "₹ Cr")), _e(pct(p["rev_growth"])), _e(pct(p["op_margin"])), _e(pct(p["roe"]))]
            rows.append([f"<b>{x}</b>" for x in cells] if p["subject"] else cells)
        what = {"mcap_cr": "market cap", "revenue_cr": "revenue", "rev_growth": "revenue growth", "op_margin": "operating margin", "roe": "ROE"}
        ranks = "; ".join(f"{what[k]} {v['rank']} of {v['of']}" for k, v in cp["ranks"].items())
        k, n = cp.get("revenue_peers"), cp.get("peers")
        who = f"the {k} of {n} peers with revenue data" if k is not None and k != n else "these peers"
        share = (f" Its revenue is {fmt(cp['revenue_share'] * 100, '%')} of the combined revenue of the company and {who}: a share of this listed "
                 "peer set, not of the industry.") if cp.get("revenue_share") else ""
        tbl = (f'<h3>Competitive position vs listed peers {tag("calculated")}</h3>'
               + _table(["Company", "Market cap", "Revenue (TTM)", "Revenue growth (latest qtr, YoY)", "Operating margin", "ROE"], rows)
               + (f'<p class="small">Rank among them (1 = highest): {_e(ranks)}.{_e(share)}</p>' if ranks or share else "")
               + '<p class="muted small">All companies on the same Yahoo Finance trailing figures; the company is in bold.</p>')
    elif comps and comps["peers"]:
        rows = [[_e(p["name"]), _e(fmt(p["mcap_cr"], "₹ Cr")), _e(fmt(p["rev_growth"] * 100 if p["rev_growth"] is not None else None, "%")),
                 _e(fmt(p["op_margin"] * 100 if p["op_margin"] is not None else None, "%")), _e(fmt(p["roe"] * 100 if p["roe"] is not None else None, "%"))]
                for p in comps["peers"]]
        tbl = f'<h3>Peer operating benchmarks {tag("actual")}</h3>' + _table(["Peer", "Market cap", "Revenue growth (latest qtr, YoY)", "Operating margin", "ROE"], rows)
    group = (comps or {}).get("group") or (cp or {}).get("group")
    peer_note = f'<p class="muted small">Peer set: {_e(group_name(group))} group, chosen from a fixed list of large listed companies; Yahoo Finance data.</p>' if group else \
        '<p class="muted">No comparable peer set was available for this company.</p>'
    na = "".join(f'<div class="na"><b>{_e(x["item"])}.</b> {_e(x["reason"])}</div>' for x in r["not_available"] if x["item"].startswith("Industry"))
    news = "".join(f'<li><span class="muted">N{i + 1} · {_e(n["date"])}</span> {_e(n["title"])} <span class="muted">({_e(n["source"])})</span> {tag("source")}</li>' for i, n in enumerate(r["news"]))
    return (f'<section><h2><span class="n">4</span>Industry and competitive position</h2>{peer_note}{tbl}{na}'
            f'{_wiki(r, "Industry")}{f"<h3>Recent headlines</h3><ul>{news}</ul>" if news else ""}</section>')


def _fin_tables(r: dict) -> str:
    out = []
    for t in _tables(r, exclude=_OWN_SECTION):
        head = [_e(t["title"])] + [_e(c) + ("" if "Recent" in t["title"] else " A") for c in t["columns"]]
        rows = [[_e(x["label"]) + " " + tag(x["kind"])] + [_e(fmt(x["values"].get(c), x["unit"])) for c in t["columns"]] for x in t["rows"]]
        out.append(f'{_table(head, rows)}<p class="muted small">Source: {_e(t["source"])}. A = actual.</p>')
    charts = ""
    inc = next((t for t in r["financials"]["tables"] if t["title"].startswith("Income")), None)
    if inc:
        def series(label: str):
            row = next((x for x in inc["rows"] if x["label"].startswith(label)), None)
            if row is None:
                return [], ""
            return [row["values"].get(c) for c in inc["columns"]], row["unit"]
        for lab, title in (("Revenue", "Revenue (₹ Cr)"), ("Net profit", "Net profit (₹ Cr)"), ("EBITDA margin", "EBITDA margin"), ("Pre-tax", "Profit before tax")):
            vals, unit = series(lab)
            if any(v is not None for v in vals):
                charts += bars(title, inc["columns"], vals, unit)
    return (f'<section><h2><span class="n">5</span>Financial analysis</h2><p class="small">{_e(r["financials"]["text"])} '
            f'{tag("ai" if r.get("narrative_origin", {}).get("financial") == "llm" else "calculated")}</p>'
            f'<div class="charts">{charts}</div>{"".join(out)}</section>')


_OWN_SECTION = ("DuPont", "Common-size", "Shareholding")


def _tables(r: dict, *, only: tuple = (), exclude: tuple = ()) -> list[dict]:
    return [t for t in r["financials"]["tables"]
            if (not only or t["title"].startswith(only)) and not t["title"].startswith(exclude)]


def _render_table(t: dict) -> str:
    head = [_e(t["title"])] + [_e(c) + " A" for c in t["columns"]]
    rows = [[_e(x["label"]) + " " + tag(x["kind"])] + [_e(fmt(x["values"].get(c), x["unit"])) for c in t["columns"]] for x in t["rows"]]
    return f'{_table(head, rows)}<p class="muted small">Source: {_e(t["source"])}. A = actual.</p>'


def _dupont(r: dict) -> str:
    ts = _tables(r, only=("DuPont",))
    if not ts:
        return '<section><h2><span class="n">0</span>DuPont analysis</h2><div class="na">Needs at least two years of balance-sheet and profit data; not available for this company.</div></section>'
    note = r.get("dupont_note") or ""
    return (f'<section><h2><span class="n">0</span>DuPont analysis</h2><p class="small muted">Return on equity split into its drivers. The factors multiply to ROE '
            f'(identity checked by ARIA\'s tests), so the table shows what changed, not just that it changed.</p>{_render_table(ts[0])}'
            f'{f"<div class=callout>{_e(note)} {tag(chr(99) + chr(97) + chr(108) + chr(99) + chr(117) + chr(108) + chr(97) + chr(116) + chr(101) + chr(100))}</div>" if note else ""}</section>')


def _common(r: dict) -> str:
    ts = _tables(r, only=("Common-size",))
    if not ts:
        return ""
    return ('<section><h2><span class="n">0</span>Common-size statements</h2><p class="small muted">Every line as a share of revenue (income statement) or of total assets '
            '(balance sheet), so companies and years of different size can be compared.</p>' + "".join(_render_table(t) for t in ts) + "</section>")


def _wiki_link(w: dict) -> str:
    url = w.get("url") or ""
    return f'<a href="{_e(url)}" target="_blank" rel="noreferrer">article</a>. ' if url.startswith("https://en.wikipedia.org/") else ""


def _wiki(r: dict, kind: str) -> str:
    items = [w for w in r.get("wiki") or [] if w.get("kind") == kind]
    return "".join(f'<h3>{kind} background {tag("source")}</h3><p class="small">{_e(w["text"])}</p><p class="muted small">Source: Wikipedia, "{_e(w["title"])}". '
                   f'{_wiki_link(w)}Encyclopedic and may be dated or incomplete; not verified by ARIA. Text licensed CC BY-SA 4.0.</p>' for w in items)


def _ownership(r: dict) -> str:
    own, ts = r.get("ownership") or {}, _tables(r, only=("Shareholding",))
    if ts:
        t = ts[0]
        rows = [[_e(x["label"])] + [_e(fmt(x["values"].get(col), "%")) for col in t["columns"]] for x in t["rows"]]
        moves = [f"{who} {own[k]:+.2f}pp" for who, k in (("promoters", "promoters_change"), ("FIIs", "fiis_change"), ("DIIs", "diis_change")) if own.get(k) is not None]
        trend = f"Change over the last four quarters: {', '.join(moves)}. " if moves else ""
        p = own.get("pledged_pct")
        pledge = (f"Promoters have pledged {fmt(p, '%')} of their holding (flagged by screener.in)." if p is not None
                  else "No promoter pledge is flagged by screener.in, which flags only material pledges.")
        return (f'<h3>Shareholding pattern {tag("actual")}</h3>{_table(["% of shares"] + [_e(col) for col in t["columns"]], rows)}'
                f'<p class="small">{_e(trend + pledge)}</p><p class="muted small">Source: {_e(t["source"])}.</p>')
    o = r["cover"].get("ownership") or {}
    bits = [f"{k}: {fmt(v, '%')}" for k, v in (("Insiders", o.get("insiders")), ("Institutions", o.get("institutions"))) if v is not None]
    return f'<h3>Ownership {tag("actual")}</h3><p>{_e(" · ".join(bits))}. Latest snapshot from Yahoo Finance; history and pledge data are not available.</p>' if bits else ""


def _ratios(r: dict) -> str:
    groups = ""
    for g in r["ratio_groups"]:
        rows = [[_e(x["label"]) + f' <span class="muted small">{_e(x["method"])}</span>', _e(x["period"]), _e(x["text"]), tag(x["kind"])] for x in g["items"]]
        groups += f'<h3>{_e(g["group"])}</h3>' + _table(["Ratio", "Period", "Value", "Basis"], rows)
    na = "".join(f'<div class="na"><b>{_e(x["item"])}.</b> {_e(x["reason"])}</div>' for x in r["not_available"] if x["item"].startswith(("Gross", "Current", "ROIC", "Altman")))
    return f'<section><h2><span class="n">6</span>Ratio analysis</h2>{groups}{na}</section>'


def _forecast(r: dict) -> str:
    f = r["forecast"]
    if not f:
        return '<section><h2><span class="n">7</span>Forecasts</h2><div class="na">No forecast: it needs a valuation model that could be computed for this company.</div></section>'
    cols, n = f["columns"], f["n_actual"]
    merged: dict[str, dict] = {}
    for x in f["rows"]:  # an actual row and an estimate row with the same label share one line
        m = merged.setdefault(x["label"], {"unit": x["unit"], "kinds": [], "values": {}})
        m["kinds"].append(x["kind"])
        m["values"].update({c: v for c, v in x["values"].items() if v is not None})
    rows = []
    for label, m in merged.items():
        badge = " ".join(tag(k) for k in dict.fromkeys(m["kinds"]))
        rows.append([_e(label) + " " + badge] + [_e(fmt(m["values"][c], m["unit"])) if c in m["values"] else "" for c in cols])
    charts = ""
    for lab, title in (("Revenue", "Revenue (₹ Cr)  A → E"), ("EBITDA", "EBITDA (₹ Cr)  A → E"), ("EPS", "EPS (₹)  A → E")):
        pair = [x for x in f["rows"] if x["label"] == lab]
        if pair:
            vals = [next((x["values"].get(c) for x in pair if x["values"].get(c) is not None), None) for c in cols]
            charts += bars(title, cols, vals, pair[0]["unit"], n_actual=n)
    return (f'<section><h2><span class="n">7</span>Forecasts <span class="tag t-actual">ACTUAL</span> → <span class="tag t-est">ESTIMATE</span></h2>'
            f'<p class="small muted">{_e(f["note"])}</p><div class="charts">{charts}</div>'
            f'{_table(["Fiscal year / period"] + [_e(c) for c in cols], rows, est_from=n + 1, cls="tight")}</section>')


def _assumptions(r: dict) -> str:
    if not r["assumption_table"]:
        return '<section><h2><span class="n">8</span>Assumptions</h2><div class="na">No valuation assumptions to show: no model was run.</div></section>'
    rows = [[_e(a["assumption"]), _e(a["historical"]), _e(a["forecast"]), _e(a["reason"]), tag(a["kind"])] for a in r["assumption_table"]]
    return (f'<section><h2><span class="n">8</span>Assumptions</h2><p class="small muted">Everything the valuation depends on. Configured inputs (risk-free rate, equity '
            f'risk premium, terminal growth) are set in ARIA\'s configuration, not read from live markets.</p>'
            f'{_table(["Assumption", "Historical", "Forecast", "Source / reason", "Basis"], rows, text=(1, 2, 3))}</section>')


def _valuation(r: dict) -> str:
    v, s = r["valuation"], r["stance"]
    kind = "ai" if r.get("narrative_origin", {}).get("valuation") == "llm" else "calculated"
    parts = [f'<p>{_e(v["text"])} {tag(kind)}</p>']
    if v["methods"]:
        parts.append(f'<h3>Valuation by method (₹ per share) {tag("calculated")}</h3>{football(v["methods"], s["price"], s["fair_value"])}')
        parts.append(_table(["Method", "Low", "Mid", "High", "Weight", "Basis"], [[_e(m["label"]), _e(fmt(m["low"], "₹")), _e(fmt(m["mid"], "₹")), _e(fmt(m["high"], "₹")), _e(f'{m["weight"]:.1f}'), _e(m["basis"])] for m in v["methods"]], text=(5,)))
    dcf = v["dcf"]
    if dcf and dcf.get("walk"):
        w = dcf["walk"]
        parts.append(f'<h3>DCF build {tag("estimate")}</h3>' + _table(
            ["12-month period", "Revenue", "EBITDA", "Free cash flow", "Discount factor", "Present value"],
            [[_e(y["period"]), _e(fmt(y["revenue"], "₹ Cr")), _e(fmt(y["ebitda"], "₹ Cr")), _e(fmt(y["fcf"], "₹ Cr")), f'{y["discount_factor"]:.3f}', _e(fmt(y["pv"], "₹ Cr"))] for y in w["years"]], est_from=0))
        parts.append(_table(["Bridge", "Value"], [[_e(x["label"]), _e(x["text"])] for x in w["summary"]]))
        xc = w.get("exit_check")
        if xc:
            parts.append(f'<div class="callout"><b>Exit-multiple cross-check.</b> Using the peer-median EV/EBITDA of {_e(fmt(xc["multiple"], "x"))} for the terminal value gives '
                         f'{_e(fmt(xc["per_share"], "₹"))} per share, against {_e(fmt(v["dcf"]["result"]["per_share"], "₹"))} from perpetual growth. Shown for comparison only; it is not blended into the fair value. {tag("calculated")}</div>')
        lb = dcf.get("lbo")
        if lb and lb.get("per_share") is not None:
            cover = f" Interest cover would bottom at {fmt(lb['min_cover'], 'x')}." if lb.get("min_cover") else ""
            parts.append(f'<div class="callout"><b>LBO cross-check.</b> A financial buyer borrowing {lb["leverage"]:g}x EBITDA at {_e(fmt(lb["rate"] * 100, "%"))}, repaying debt '
                         f'from free cash flow and selling after {lb["years"]} years at its entry multiple could pay up to {_e(fmt(lb["entry_multiple"], "x"))} EBITDA, about '
                         f'{_e(fmt(lb["per_share"], "₹"))} a share, and still earn {lb["irr"] * 100:.0f}% a year.{_e(cover)} It shows what leverage alone can justify; it is not a '
                         f'fair value and is not blended. {tag("calculated")}</div>')
        rev = dcf.get("reverse")
        if rev and rev.get("implied_growth") is not None:
            parts.append(f'<div class="callout"><b>Reverse DCF.</b> Today\'s price implies about {_e(fmt(rev["implied_growth"] * 100, "%"))} annual revenue growth for ten years, '
                         f'against the model\'s {_e(fmt(dcf["inputs"]["growth"][0] * 100, "%"))} in year 1. {tag("calculated")}</div>')
        elif rev and rev.get("reason") == "above_range":
            parts.append('<div class="callout"><b>Reverse DCF.</b> No revenue growth up to 50% a year justifies today\'s price under these assumptions.</div>')
    ddm = v["ddm"]
    if ddm:
        parts.append(f'<h3>Dividend discount model {tag("estimate")}</h3>' + _table(["Year", "Dividend / share"], [[str(i + 1), _e(fmt(d, "₹"))] for i, d in enumerate(ddm["result"]["dividends"])], est_from=0))
    comps = v["comps"]
    if comps:
        med = comps["medians"]
        rows = [[_e(p["name"]), _e(fmt(p["mcap_cr"], "₹ Cr")), _e(fmt(p["ev_cr"], "₹ Cr")), _e(fmt(p["revenue_cr"], "₹ Cr")), _e(fmt(p["ebitda_cr"], "₹ Cr")), _e(fmt(p["net_income_cr"], "₹ Cr"))]
                + [("<s>" + _e(fmt(p[k], "x")) + "</s>") if k in p["excluded"] else _e(fmt(p[k], "x")) for k in ("pe", "fwd_pe", "ev_sales", "ev_ebitda", "pb")] for p in comps["peers"]]
        rows.append(["<b>Median (used)</b>"] + [""] * 5 + [_e(fmt(med.get(k), "x")) if k != "ev_sales" else "" for k in ("pe", "fwd_pe", "ev_sales", "ev_ebitda", "pb")])
        parts.append(f'<h3>Comparable companies {tag("actual")}</h3><p class="small muted">{_e(group_name(comps["group"]))} peers. Struck-through multiples were excluded from the median (data artifact or not meaningful).</p>'
                     + _table(["Company", "Market cap", "EV", "Revenue", "EBITDA", "Net income", "P/E", "Fwd P/E", "EV/Sales", "EV/EBITDA", "P/B"], rows))
    na = "".join(f"<li><b>{_e(k)}</b>: {_e(why)}</li>" for k, why in v["skipped"].items())
    notes = "".join(f"<li>{_e(n)}</li>" for n in v["notes"] + s["notes"])
    street = v["street"]
    if street.get("target_mean"):
        parts.append(f'<h3>Street context {tag("actual")}</h3><p>Analyst targets: mean {_e(fmt(street["target_mean"], "₹"))}, range {_e(fmt(street["target_low"], "₹"))} – '
                     f'{_e(fmt(street["target_high"], "₹"))} ({int(street["analysts"] or 0)} analysts). Shown for context; it is not an input to the fair value.</p>')
    parts.append(f'<ul>{notes}</ul>' + (f'<h3>Methods not run</h3><ul>{na}</ul>' if na else ""))
    return f'<section><h2><span class="n">9</span>Valuation</h2>{"".join(parts)}</section>'


def _sensitivity(r: dict) -> str:
    v, sc, s = r["valuation"], r["scenarios"], r["stance"]
    dcf = v["dcf"]
    parts = []
    if sc:
        mc = sc["monte_carlo"]
        if mc:
            parts.append(f'<div class="callout"><b>Monte Carlo.</b> Across {mc["n"]:,} seeded scenarios (growth, margin, WACC and terminal growth varied), the DCF value has a 10th–90th percentile range of '
                         f'{_e(fmt(mc["p10"], "₹"))} – {_e(fmt(mc["p90"], "₹"))} (median {_e(fmt(mc["p50"], "₹"))}); {mc["prob_above_price"] * 100:.0f}% of scenarios exceed today\'s price. {tag("calculated")}</div>')
    if dcf and dcf.get("sensitivity"):
        parts.append(f'<h3>DCF value per share: WACC × terminal growth {tag("calculated")}</h3>{heat(dcf["sensitivity"], s["price"])}'
                     '<p class="small muted">Green: at or above today\'s price. Red: below. Outlined cell: base case. n/a: the model refuses that combination.</p>')
        sw = dcf.get("margin_swing")
        if sw and sw[0] is not None and sw[1] is not None:
            parts.append(f'<p>EBITDA margin ±2pp moves the DCF between {_e(fmt(sw[0], "₹"))} and {_e(fmt(sw[1], "₹"))}.</p>')
    return f'<section><h2><span class="n">10</span>Sensitivity and Monte Carlo</h2>{"".join(parts) or "<div class=na>No sensitivity analysis: no DCF or DDM could be computed.</div>"}</section>'


def _debate(r: dict) -> str:
    d = r["debate"]
    if not (d["bull"] or d["bear"]):
        return ""

    def chips(evidence: list[dict]) -> str:
        return "".join(f'<span class="chip">{_e(x["label"])} <b>{_e(x["value"])}</b></span>' for x in evidence)

    def side(title, cls, args):
        items = "".join(f'<p>{_e(a["claim"])}<br>{chips(a["evidence"])}</p>' for a in args)
        return f'<div class="side {cls}"><b>{title}</b> {tag("ai")}{items or "<p class=muted>No argument the evidence supports.</p>"}</div>'

    j = d["judge"]
    judge = ""
    if j:
        judge = (f'<div class="callout"><b>Judge: {_e(j["call"])}</b> (conviction {j["conviction"] * 100:.0f}%) {tag("ai")}'
                 f'{" — differs from the valuation-implied rating" if d["aligned"] is False else ""}<br><b>Swing factor:</b> {_e(j["swing_factor"])}<br>'
                 f'<b>What would change the call:</b> {_e(j["change_my_mind"])}</div>')
    return (f'<section><h2><span class="n">11</span>Bull vs bear</h2><p class="small muted">Each side may only cite calculated figures; the values shown come from the ledger, '
            f'not from the model.</p><div class="two">{side("Bull case", "bull", d["bull"])}{side("Bear case", "bear", d["bear"])}</div>{judge}</section>')


def _risks(r: dict) -> str:
    rows = "".join(f'<li><span class="sev-{_e(x["severity"])}">[{_e(x["category"])}]</span> {"<b>" + _e(x["title"]) + ".</b> " if x["title"] else ""}{_e(x["detail"])} {tag(x["origin"])}</li>' for x in r["risks"])
    cats = "".join(f"<li>{_e(c)}</li>" for c in r["catalysts"])
    cat_block = f"<h3>Catalysts {tag('ai')}</h3><ul>{cats}</ul>" if cats else ""
    return (f'<section><h2><span class="n">12</span>Risks and catalysts</h2><h3>Risks</h3><ul>{rows or "<li class=muted>None flagged.</li>"}</ul>'
            f'{cat_block}</section>')


def _verification(r: dict) -> str:
    a = r["audit"]
    checks = "".join(f'<div class="check {_e(c["status"])}"><b>{"✓" if c["status"] == "pass" else "ℹ" if c["status"] == "info" else "⚠"} {_e(c["title"])}</b>'
                     + "".join(f'<span class="finding">{_e(m)}</span>' for m in c["findings"]) + "</div>" for c in a["checks"])
    kinds: dict[str, int] = {}
    for f in r["facts"]:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    src = "".join(f"<li>{_e(x['source'])}: {x['count']} figures</li>" for x in r["sources"])
    return (f'<section><h2><span class="n">13</span>Verification, sources and methodology</h2><h3>Verification: {_e(a["status"])}</h3>{checks}'
            f'<h3>Sources</h3><ul>{src}</ul><p class="small muted">{len(r["facts"])} figures in the ledger: {kinds.get("raw", 0)} reported, '
            f'{kinds.get("calculated", 0)} calculated, {kinds.get("assumption", 0)} assumed. Every figure carries its source, period and method in the JSON export.</p>'
            f'<h3>Methodology</h3><p class="small">Statements: screener.in ({_e(r["cover"]["basis"])}); shareholding: screener.in, from quarterly exchange filings. Market data, peers, '
            f'analyst targets, management and the balance-sheet detail behind the Altman Z-score: Yahoo Finance. Headlines: Google News RSS. '
            f'Valuation: deterministic DCF (or DDM and justified P/B for lenders) and peer multiples, reconciled by method agreement; bull/base/bear and Monte Carlo are fixed-rule variations '
            f'of the same model; the exit-multiple and LBO checks are shown for comparison and never blended. The language model writes prose only.</p></section>')


# ── forecasts and scenarios: every case worked through, line by line ───────
_DCF_LINES = (("Revenue", "revenue", "revenue", "₹ Cr"), ("Revenue growth", "growth", "rev_growth", "%"), ("EBITDA", "ebitda", "ebitda", "₹ Cr"),
              ("EBITDA margin", "margin", "opm", "%"), ("Depreciation and amortisation", "da", None, "₹ Cr"), ("EBIT", "ebit", "ebit", "₹ Cr"),
              ("Tax on EBIT", "tax", None, "₹ Cr"), ("NOPAT (EBIT after tax)", "nopat", None, "₹ Cr"), ("Capex", "capex", None, "₹ Cr"),
              ("Increase in working capital", "nwc_change", None, "₹ Cr"), ("Unlevered free cash flow", "fcf", None, "₹ Cr"))
_DDM_LINES = (("EPS", "eps", "eps", "₹"), ("EPS growth", "growth", None, "%"), ("Dividend per share", "dps", None, "₹"))


def _num(v, unit: str) -> str:
    return _e(fmt(v * 100 if unit == "%" and v is not None else v, unit))


def _cell(v, unit: str) -> str:
    """Year-table cell with the unit moved to the row label: plain numbers keep 13 year columns on one line."""
    if v is None:
        return _num(v, unit)
    return f"{v * 100:.1f}" if unit == "%" else f"{v:,.2f}" if unit == "₹" else f"{v:,.0f}"


def _case_table(case: dict, hist: dict | None, dcf: bool) -> str:
    d = case["detail"]
    if "reason" in d:
        return f'<div class="na">The model refuses this case: {_e(d["reason"])}</div>'
    n = len(d["discount_factor"])
    hcols = hist["columns"] if hist else []
    cols = hcols + [f"Y{i + 1}E" for i in range(n)]
    rows = []
    for label, key, hkey, unit in (_DCF_LINES if dcf else _DDM_LINES):
        actual = [_cell(v, unit) if hkey and v is not None else "" for v in (hist["rows"].get(hkey, [None] * len(hcols)) if hist and hkey else [None] * len(hcols))]
        rows.append([_e(f"{label} ({unit})")] + actual + [_cell(v, unit) for v in d["lines"][key]])
    rows.append(["Discount factor"] + [""] * len(hcols) + [_e(f"{k:.3f}") for k in d["discount_factor"]])
    pv = d["pv_fcf"] if dcf else d["pv_dps"]
    rows.append(["Present value of " + ("free cash flow (₹ Cr)" if dcf else "dividend (₹)")] + [""] * len(hcols) + [_cell(v, "₹ Cr" if dcf else "₹") for v in pv])
    a = d["assumptions"]
    rate = f'WACC {a["wacc"]:.1%}' if dcf else f'cost of equity {a["coe"]:.1%}'
    head = (f'<p class="small"><b>Assumptions:</b> year-1 growth {a["g1"]:.1%}, fading to {a["g_final"]:.1%} by year {n}; '
            + (f'EBITDA margin {a["margin"]:.1%}; tax {a["tax"]:.1%}; capex {a["capex_pct"]:.1%} of revenue; working capital {a["nwc_pct"]:.1%} of revenue; '
               if dcf else f'payout {a["payout"]:.0%}; ')
            + f'{rate}; terminal growth {a["terminal_growth"]:.1%}. {tag("assumption")}</p>')
    b = d["bridge"]
    if dcf:
        bridge = [("Sum of PV of free cash flow (10 years)", fmt(b["sum_pv_fcf"], "₹ Cr")), ("Terminal-year free cash flow", fmt(b["terminal_fcf"], "₹ Cr")),
                  ("Terminal value", fmt(b["terminal_value"], "₹ Cr")), ("PV of terminal value", fmt(b["pv_terminal"], "₹ Cr")),
                  ("Terminal value share of EV", fmt(b["tv_share"] * 100, "%")), ("Enterprise value", fmt(b["enterprise_value"], "₹ Cr")),
                  ("Less: net debt", fmt(b["net_debt"], "₹ Cr")), ("Less: minority interest", fmt(b["nci"], "₹ Cr")),
                  ("Equity value", fmt(b["equity_value"], "₹ Cr")), ("Shares", fmt(b["shares_cr"], "Cr shares")),
                  ("Value per share", fmt(b["per_share"], "₹")), ("Implied EV / year-1 EBITDA", fmt(b["ev_ebitda_fwd"], "x"))]
    else:
        bridge = [("Sum of PV of dividends (10 years)", fmt(b["sum_pv_dividends"], "₹")), ("Terminal payout", fmt(b["terminal_payout"] * 100, "%")),
                  ("Terminal value", fmt(b["terminal_value"], "₹")), ("PV of terminal value", fmt(b["pv_terminal"], "₹")), ("Value per share", fmt(b["per_share"], "₹"))]
    return (head + _table(["Line item"] + [_e(c) for c in cols], rows, est_from=len(hcols) + 1, cls="tight wide")
            + f'<h4>Bridge to value per share {tag("calculated")}</h4>' + _table(["Step", "Value"], [[_e(k), _e(v)] for k, v in bridge], cls="tight"))


def _scenarios_section(r: dict) -> str:
    sc = r.get("scenarios")
    if not sc:
        return ('<section><h2><span class="n">7</span>Forecasts and scenarios</h2><div class="na">No scenarios: they need a DCF or DDM, '
                'which could not be computed (or was withheld by verification) for this company.</div></section>')
    dcf = sc["model"] == "DCF"
    price = r["stance"]["price"] if r.get("stance") else None
    cards = "".join(f'<div class="case {c["key"]}"><div class="muted small">{c["name"]} case · weight {c["weight"]:.0%}</div><div class="v">{_e(fmt(c["value"], "₹")) if c["value"] else "n/a"}</div>'
                    f'<div>{_e(fmt(c["upside_pct"], "%")) if c["upside_pct"] is not None else ""} vs price</div><div class="small muted">{_e(c["assumptions"])}</div></div>' for c in sc["cases"])
    # side by side
    def pick(c, fn):
        d = c["detail"]
        return "n/a" if "reason" in d else fn(d)
    if dcf:
        spec = [("Year-1 revenue growth", lambda d: fmt(d["assumptions"]["g1"] * 100, "%")), ("Year-10 revenue growth", lambda d: fmt(d["assumptions"]["g_final"] * 100, "%")),
                ("EBITDA margin", lambda d: fmt(d["assumptions"]["margin"] * 100, "%")), ("WACC", lambda d: fmt(d["assumptions"]["wacc"] * 100, "%")),
                ("Terminal growth", lambda d: fmt(d["assumptions"]["terminal_growth"] * 100, "%")), ("Year-5 revenue", lambda d: fmt(d["lines"]["revenue"][4], "₹ Cr")),
                ("Year-5 EBITDA", lambda d: fmt(d["lines"]["ebitda"][4], "₹ Cr")), ("Year-5 free cash flow", lambda d: fmt(d["lines"]["fcf"][4], "₹ Cr")),
                ("Sum of PV of free cash flow", lambda d: fmt(d["bridge"]["sum_pv_fcf"], "₹ Cr")), ("PV of terminal value", lambda d: fmt(d["bridge"]["pv_terminal"], "₹ Cr")),
                ("Terminal value share of EV", lambda d: fmt(d["bridge"]["tv_share"] * 100, "%")), ("Enterprise value", lambda d: fmt(d["bridge"]["enterprise_value"], "₹ Cr")),
                ("Equity value", lambda d: fmt(d["bridge"]["equity_value"], "₹ Cr")), ("Implied EV / year-1 EBITDA", lambda d: fmt(d["bridge"]["ev_ebitda_fwd"], "x"))]
    else:
        spec = [("Year-1 EPS growth", lambda d: fmt(d["assumptions"]["g1"] * 100, "%")), ("Cost of equity", lambda d: fmt(d["assumptions"]["coe"] * 100, "%")),
                ("Terminal growth", lambda d: fmt(d["assumptions"]["terminal_growth"] * 100, "%")), ("Year-5 EPS", lambda d: fmt(d["lines"]["eps"][4], "₹")),
                ("Year-5 dividend per share", lambda d: fmt(d["lines"]["dps"][4], "₹")), ("Sum of PV of dividends", lambda d: fmt(d["bridge"]["sum_pv_dividends"], "₹")),
                ("PV of terminal value", lambda d: fmt(d["bridge"]["pv_terminal"], "₹"))]
    rows = [[_e(label)] + [_e(pick(c, fn)) for c in sc["cases"]] for label, fn in spec]
    rows.append(["<b>Value per share</b>"] + [f'<b>{_e(fmt(c["value"], "₹"))}</b>' for c in sc["cases"]])
    rows.append(["Upside / downside vs price"] + [_e(fmt(c["upside_pct"], "%")) for c in sc["cases"]])
    rows.append(["Probability weight"] + [_e(f'{c["weight"]:.0%}') for c in sc["cases"]])
    weighted = ""
    if sc.get("weighted"):
        weighted = (f'<div class="callout"><b>Probability-weighted value: {_e(fmt(sc["weighted"], "₹"))}</b>'
                    + (f' ({_e(fmt(sc["weighted_upside_pct"], "%"))} vs today\'s price {_e(fmt(price, "₹"))})' if sc.get("weighted_upside_pct") is not None else "")
                    + f'. Bear 25%, base 50%, bull 25%: a stated convention, not a forecast of likelihood. {tag("calculated")}</div>')
    cases = "".join(f'<h3>{c["name"]} case: {_e(c["assumptions"])} {tag("estimate")}</h3>{_case_table(c, sc.get("history"), dcf)}' for c in sc["cases"])
    intro = ("Each case is the same model with fixed, stated changes to its drivers. Every case below starts from the reported history "
             "(ACTUAL), runs the full forecast year by year (ESTIMATE), discounts it, and bridges enterprise value to value per share, so "
             "any number can be traced to the line above it.")
    return (f'<section><h2><span class="n">7</span>Forecasts and scenarios</h2><p class="small muted">{intro}</p><div class="cases">{cards}</div>'
            f'<h3>Scenarios side by side {tag("calculated")}</h3>{_table(["", "Bear", "Base", "Bull"], rows, cls="tight")}{weighted}{cases}</section>')


# ── fundamental analysis ───────────────────────────────────────────────────
_RATING = {"strong": ("var(--green)", "Strong"), "mixed": ("#b45309", "Mixed"), "weak": ("var(--red)", "Weak"), "n/a": ("var(--faint)", "No data")}
_SENTIMENT_WORDS = {"strong": "Positive", "mixed": "Neutral", "weak": "Negative"}
_PASS = {True: '<span style="color:var(--green);font-weight:700">Pass</span>', False: '<span style="color:var(--red);font-weight:700">Fail</span>', None: '<span class="muted">n/a</span>'}


def _scorecard_html(f: dict) -> str:
    sc = f.get("scorecard")
    if not sc:
        return ""
    rows = []
    for p in sc["pillars"]:
        colour, word = _RATING[p["rating"]]
        if p["name"] == "Sentiment":
            word = _SENTIMENT_WORDS.get(p["rating"], word)
        mark = {1: '<span style="color:var(--green)">▲</span>', -1: '<span style="color:var(--red)">▼</span>', 0: '<span class="muted">●</span>'}
        why = "<br>".join(f'{mark[x["sign"]]} {_e(x["text"])}' for x in p["reasons"]) or '<span class="muted">nothing to measure for this company</span>'
        rows.append([_e(p["name"]), f'<b style="color:{colour}">{word}</b>', why])
    ov = sc["overlay"]
    cls = {"concern": "warn", "support": "good"}.get(ov["tone"], "")
    it = f.get("intelligence") or {}
    badge = ""
    if it.get("score") is not None:
        colour = _RATING[it["band"]][0]
        divs = "".join(f'<li><b>{_e(d["severity"])}</b>: {_e(d["text"])} <span class="muted">({_e(d["evidence"])})</span></li>' for d in it["divergences"])
        badge = (f'<p><b style="color:{colour}">Intelligence score {it["score"]}/100 ({it["band"]})</b> <span class="small muted">coverage {it["coverage"]:.0%}'
                 f'{", low evidence" if it["low_evidence"] else ""}</span></p>' + (f'<ul class="small">{divs}</ul>' if divs else ""))
    return (f'<h3>Fundamental scorecard {tag("calculated")}</h3><div class="callout {cls}"><b>{_e(ov["reading"])}</b></div>{badge}'
            f'<p class="small muted">Six pillars, each built from the measures below: ▲ counts for, ▼ against, ● neutral. A pillar is strong at two or more net points and weak at '
            f'minus one or lower. The reading never changes the fair value or the rating: it says how much weight the call deserves.</p>'
            + _table(["Pillar", "Rating", "What it rests on"], rows, cls="tight", text=(2,)))


def _checklist(rows: list[dict], score: tuple | None = None) -> str:
    return _table(["Test", "Result", "Detail"], [[_e(x["test"]), _PASS[x["passed"]], _e(x["detail"])] for x in rows], cls="tight", text=(0, 2))


def _lenses_html(f: dict) -> str:
    L = f.get("lenses") or {}
    parts = []
    g = L.get("graham") or {}
    if g.get("available"):
        line = ""
        if g.get("number") is not None:
            line = (f'Graham number <b>{_e(fmt(g["number"], "₹"))}</b> (the most a defensive investor should pay, from EPS {_e(fmt(g["eps"], "₹"))} and book value '
                    f'{_e(fmt(g["bvps"], "₹"))} per share): margin of safety <b>{g["margin_of_safety"]:+.0%}</b> against today\'s price. ')
        parts.append(f'<h4>Graham: the defensive investor {tag("calculated")}</h4><p class="small">{line}<b>{g["score"]} of {g["tested"]} tests pass.</b></p>' + _checklist(g["tests"]))
    b = L.get("buffett") or {}
    if b.get("available"):
        parts.append(f'<h4>Buffett: consistency and retained earnings {tag("calculated")}</h4><p class="small"><b>{b["score"]} of {b["tested"]} tests pass.</b></p>' + _checklist(b["tests"]))
    ly = L.get("lynch") or {}
    gb = L.get("greenblatt") or {}
    rows = []
    if ly.get("available"):
        rows.append(["Lynch: PEG ratio", f'{ly["peg"]:.2f}', f'P/E {ly["pe"]:.1f}x / EPS growth {ly["growth"] * 100:.1f}% a year: a {ly["category"]}; {ly["reading"]}'])
    if gb.get("available"):
        rows.append(["Greenblatt: earnings yield", f'{gb["earnings_yield"] * 100:.1f}%', f'EBIT / enterprise value vs the {gb["risk_free"] * 100:.2f}% risk-free rate; ROIC {gb["roic"] * 100:.1f}%: {gb["verdict"]}'])
        if gb.get("eva"):
            e = gb["eva"]
            rows.append(["Economic value added (EVA)", fmt(e["value"], "₹ Cr"), f'(ROIC - WACC {e["spread"]:+.1f}pp) x invested capital {fmt(e["invested_capital"], "₹ Cr")}: '
                         + ("earns above its cost of capital" if e["value"] > 0 else "earns below its cost of capital")])
    if rows:
        parts.append(f'<h4>Growth and return lenses {tag("calculated")}</h4>' + _table(["Lens", "Value", "Reading"], [[_e(c) for c in x] for x in rows], cls="tight", text=(2,)))
    if not parts:
        return ""
    return ('<h3>Investor lenses</h3><p class="small muted">Each framework asks a different question of the same statements, with the pass marks its author published '
            '(Graham 1949, Buffett 1977–, Lynch 1989, Greenblatt 2005, Stern Stewart). They are screens, not verdicts: a growth company will fail Graham and a bank will not fit Greenblatt.</p>'
            + "".join(parts))


def _technical_html(f: dict) -> str:
    t = f.get("technical") or {}
    if not t.get("available"):
        return ""
    return (f'<h3>Technical read {tag("calculated")}</h3><p class="small muted">Trend, relative strength and momentum from the weekly price history. Trend and relative strength feed the '
            'scorecard; the rest is context.</p>' + _table(["Measure", "Value", "Reading"], [[_e(x["measure"]), _e(x["value"]), _e(x["reading"])] for x in t["rows"]], cls="tight", text=(2,)))


def _call_html(call: dict) -> str:
    if not call or not call.get("available"):
        return (f'<h3>Management on the latest earnings call</h3><div class="na">{_e((call or {}).get("reason", "no transcript"))}</div>')
    head = (f'The {_e(call["period"])} earnings call, {call["n_sentences"]} sentences read'
            + (f', {call["scored"]} scored: net tone <b>{call["net"]:+.2f}</b> ({call["positive_share"]:.0%} of sentences positive, {call["negative_share"]:.0%} negative). ' if call.get("net") is not None
               else ' (not scored: FinBERT is not installed). ')
            + (f'<a href="{_e(call["url"])}" target="_blank" rel="noreferrer">Open the transcript</a>.' if call.get("url") else ""))
    blocks = []
    for theme, quotes in call["themes"].items():
        qs = "".join(f'<div class="quote">“{_e(q["text"])}”<div class="meta">'
                     + (f'{_e(q["label"])} ({q["net"]:+.2f})' if q.get("net") is not None else "tone not scored") + '</div></div>' for q in quotes)
        blocks.append(f'<h4>{_e(theme)}</h4>{qs}')
    return (f'<h3>Management on the latest earnings call {tag("source")}</h3><p class="small">{head}</p><p class="small muted">{_e(call["method"])}</p>' + "".join(blocks))


def _documents_html(docs: dict) -> str:
    docs = docs or {}
    ar, cc = docs.get("annual_reports", [])[:3], docs.get("concalls", [])[:4]
    if not ar and not cc:
        return ""
    link = lambda label, url: f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(label)}</a>'  # noqa: E731
    items = [f"<li>{link(a['label'], a['url'])}</li>" for a in ar] + [f"<li>{link('Earnings call ' + c['period'] + ' (transcript)', c['transcript'])}</li>" for c in cc if c.get("transcript")]
    return (f'<h3>Company reports on file {tag("source")}</h3><p class="small muted">Linked from screener.in for the reader. Only the latest earnings-call transcript is read '
            f'and scored above; annual reports are not analysed.</p><ul class="small">{"".join(items)}</ul>')


def _fundamentals_section(r: dict) -> str:
    f = r.get("fundamentals") or {}
    if not f.get("available"):
        return ""
    parts = [_scorecard_html(f), _lenses_html(f)]
    p = f["piotroski"]
    mark = {True: '<span style="color:var(--green);font-weight:700">Pass</span>', False: '<span style="color:var(--red);font-weight:700">Fail</span>', None: '<span class="muted">n/a</span>'}
    if p.get("signals"):
        head = (f'<b>{p["score"]} of {p["tested"]} tested signals pass: {p["verdict"]}.</b> ' if p.get("available") else f'<b>Not scored:</b> {_e(p.get("reason", ""))}. ')
        parts.append(f'<h3>Piotroski F-score {tag("calculated")}</h3><p class="small">{head}Nine pass/fail tests of profitability, balance-sheet strength and '
                     f'efficiency (Piotroski, 2000). 8–9 is strong, 0–2 weak.</p>'
                     + _table(["Group", "Test", "Result", "Detail"], [[_e(x["group"]), _e(x["test"]), mark[x["passed"]], _e(x["detail"])] for x in p["signals"]], cls="tight", text=(1, 3)))
    elif p.get("reason"):
        parts.append(f'<h3>Piotroski F-score</h3><div class="na">{_e(p["reason"])}</div>')
    rows = []
    q = f["quality"]
    if q.get("cash_conversion") is not None:
        rows.append(["Cash conversion (3-year median)", fmt(q["cash_conversion"], "x"), q.get("verdict", ""), "operating cash flow / net profit"])
    if q.get("accruals") is not None:
        rows.append(["Accruals ratio (Sloan)", fmt(q["accruals"] * 100, "%"), "profits backed by cash" if q["accruals"] <= 0 else "profits ahead of cash",
                     "(net profit - operating cash flow) / average total assets"])
    v = f["value_creation"]
    if v.get("available"):
        rows.append(["ROIC vs WACC", f'{fmt(v["roic"], "%")} vs {fmt(v["wacc"], "%")} ({v["spread"]:+.1f}pp)',
                     "creates value" if v["creates_value"] else "earns less than its cost of capital", "return on invested capital minus WACC"])
    g = f["growth_check"]
    if g.get("available"):
        how = (f'reinvestment rate {g["reinvestment_rate"]:.0%} x ROIC {g["roic"]:.1%}' if "reinvestment_rate" in g else f'ROE {g["roe"]:.1%} x retention {g["retention"]:.0%}')
        rows.append(["Fundamental growth", "not meaningful" if g["fundamental"] is None else fmt(g["fundamental"] * 100, "%"),
                     g["note"] if g["fundamental"] is None else
                     (f'forecast year-1 growth {fmt(g["model"] * 100, "%")}: {g["verdict"]}' if g.get("model") is not None else ""), how])
    o = f["owner_earnings"]
    if o.get("available"):
        rows.append(["Owner earnings (Buffett)", fmt(o["value"], "₹ Cr"), f'{o["yield"]:.1%} of market value' if o.get("yield") is not None else "",
                     "net profit + depreciation - capex - working-capital build"])
    rim = f["residual_income"]
    if rim.get("available"):
        rows.append(["Residual income value", fmt(rim["per_share"], "₹") + " per share",
                     (f'{fmt(rim["upside"] * 100, "%")} vs price; {rim["reading"]}' if rim.get("upside") is not None else ""),
                     f'book {fmt(rim["book"], "₹")} + PV of excess returns {fmt(rim["pv_residual"], "₹")}'])
    if rows:
        parts.append(f'<h3>Quality, value creation and growth {tag("calculated")}</h3>'
                     + _table(["Measure", "Value", "Reading", "How it is calculated"], [[_e(c) for c in x] for x in rows], cls="tight", text=(2, 3)))
    if rim.get("available"):
        rr = rim["rows"]
        parts.append(f'<h4>Residual income model, year by year {tag("estimate")}</h4><p class="small muted">ROE {rim["roe"]:.1%} (3-year median) fades in a straight line to the '
                     f'{rim["coe"]:.1%} cost of equity over 10 years, so no excess return is assumed after that; book value grows by retained profit '
                     f'({1 - rim["payout"]:.0%} retained). A cross-check, not part of the blended fair value.</p>'
                     + _table(["Year"] + [f"Y{x['year']}E" for x in rr],
                              [["ROE"] + [_e(fmt(x["roe"] * 100, "%")) for x in rr], ["Opening book value per share"] + [_e(fmt(x["book"], "₹")) for x in rr],
                               ["Residual income per share"] + [_e(fmt(x["residual_income"], "₹")) for x in rr], ["Present value"] + [_e(fmt(x["pv"], "₹")) for x in rr]],
                              est_from=1, cls="tight wide"))
    parts.append(_technical_html(f))
    ns = f["news_signals"]
    if ns["items"]:
        summ = [[_e(cat), str(c["positive"]), str(c["negative"]), str(c["neutral"] + c["mixed"])] for cat, c in sorted(ns["summary"].items(), key=lambda kv: -sum(kv[1].values()))]
        colour = {"positive": "var(--green)", "negative": "var(--red)"}
        items = [[_e(it["category"]), f'<span style="color:{colour.get(it["direction"], "inherit")}">{_e(it["direction"])}</span>',
                  "" if it.get("net") is None else f'{it["net"]:+.2f}', _e(it["title"]), _e(f'{it.get("source", "")}, {it.get("date", "")}')] for it in ns["items"]]
        tone = (f' Overall tone <b>{ns["net"]:+.2f}</b> across {ns["scored"]} headlines (recent ones count more).' if ns.get("net") is not None else "")
        parts.append(f'<h3>News: forward-looking signals and tone {tag("source")}</h3><p class="small muted">{_e(ns["method"])}</p><p class="small">{tone}</p>'
                     + _table(["Theme", "Positive", "Negative", "Neutral / mixed"], summ, cls="tight")
                     + _table(["Theme", "Direction", "Tone", "Headline", "Outlet, date"], items, cls="tight", text=(3,)))
    parts += [_call_html(f.get("concall")), _documents_html(f.get("documents"))]
    intro = ("Is the business getting stronger, are its profits backed by cash, does it earn more than it costs to fund, is it priced sensibly by the classic investors' tests, "
             "what is the trend, and what do the news and management's own words say about the future? Scores are arithmetic on the reported statements and prices; "
             "tone is scored by FinBERT; quotes are verbatim.")
    return f'<section><h2><span class="n">6</span>Fundamental analysis</h2><p class="small muted">{intro}</p>{"".join(x for x in parts if x)}</section>'


KINDS = {
    "equity_research": ("Equity research report", ("summary", "executive", "company", "industry", "financials", "ratios", "dupont", "common", "fundamentals",
                                                    "forecast", "scenarios", "assumptions", "valuation", "sensitivity", "debate", "risks", "verification")),
    "financial_model": ("Financial model report", ("summary", "financials", "common", "ratios", "dupont", "fundamentals", "forecast", "scenarios", "assumptions",
                                                    "valuation", "sensitivity", "verification")),
    "valuation": ("Valuation report", ("summary", "fundamentals", "forecast", "scenarios", "assumptions", "valuation", "sensitivity", "debate", "risks", "verification")),
    "dupont": ("DuPont and ratio analysis", ("financials", "dupont", "ratios", "common", "verification")),
}
_SECTIONS = {"summary": _summary, "executive": _executive, "company": _company, "industry": _industry, "financials": _fin_tables, "ratios": _ratios,
             "dupont": _dupont, "common": _common, "forecast": _forecast, "assumptions": _assumptions, "valuation": _valuation,
             "sensitivity": _sensitivity, "debate": _debate, "risks": _risks, "verification": _verification,
             "scenarios": _scenarios_section, "fundamentals": _fundamentals_section}
_RATING_DEFS = {"BUY": "Undervalued: the model's fair value is above the price by at least the buy threshold for its confidence tier.",
                "HOLD": "Fairly valued: the price is within the band around fair value.",
                "SELL": "Overvalued: the model's fair value is below the price by at least the sell threshold."}


def _disclosure(r: dict) -> str:
    c, meta, a = r["cover"], r.get("meta") or {}, r["audit"]
    bands = "".join(f"<tr><td class=l>{t.replace('_', ' ').title()}</td><td>{b * 100:.0f}%</td><td>{s_ * 100:.0f}%</td></tr>" for t, (b, s_) in VERDICT_BANDS.items())
    sources = "".join(f"<li>{_e(x['source'])}</li>" for x in r["sources"])
    through = "".join(f"<li>{_e(k)}: {_e(v)}</li>" for k, v in c["data_through"].items())
    findings = "".join(f"<li>{_e(m)}</li>" for chk in a["checks"] if chk["status"] in ("review", "blocked") for m in chk["findings"]) or "<li>No open verification findings.</li>"
    limits = "".join(f"<li><b>{_e(x['item'])}.</b> {_e(x['reason'])}</li>" for x in r.get("not_available", []))
    origin = ", ".join(f"{k}: {'language model, from cited figures' if v == 'llm' else 'template built from figures'}" for k, v in (r.get("narrative_origin") or {}).items())
    ident = f"Report ID {_e(meta.get('id', 'unsaved'))} · version {_e(meta.get('version', 'draft'))} · generated {_e(c['report_date'])} · kind: {_e('Mutual fund analysis' if r.get('kind') == 'fund_analysis' else KINDS.get(r.get('kind'), KINDS['equity_research'])[0])}"
    html = f'''<section class="disc"><h2><span class="n">0</span>Important disclosures</h2><p class="small muted">{ident}</p>
<h3>1. Nature of this report</h3><p>This is an automated, AI-assisted report generated by ARIA from public data. It is provided for information and education only. It is <b>not investment advice, not a
recommendation or solicitation to buy, sell or hold any security</b>, and not a research report issued by a SEBI-registered Research Analyst under the SEBI (Research Analysts) Regulations, 2014.
ARIA is not a SEBI-registered research analyst or investment adviser. Consult a registered adviser before acting.</p>
<h3>2. No analyst certification</h3><p>No human analyst prepared, reviewed or certified this report. The "model-implied view" is the arithmetic result of the stated assumptions, not a personal opinion of any individual.</p>
<h3>3. Conflicts of interest</h3><p>ARIA does not trade or hold securities, does not receive compensation from any company it covers, and has no investment-banking or advisory relationship with them. The company was not consulted and did not review this report.</p>
<h3>4. How the stance is defined</h3><p class="small">The stance compares the model's fair value with the share price. The required gap widens as confidence in the fair value falls:</p>
<div class="scroll"><table><thead><tr><th class=l>Confidence tier</th><th>Undervalued if fair value exceeds price by</th><th>Overvalued if price exceeds fair value by</th></tr></thead><tbody>{bands}</tbody></table></div>
<ul class="small">{"".join(f"<li><b>{k}</b> - {v}</li>" for k, v in _RATING_DEFS.items())}</ul>
<p class="small">When the valuation approaches disagree by more than 2.5x, no point estimate is given, and when verification blocks a figure the stance is shown as "Not assessed".</p>
<h3>5. Data sources and data-through dates</h3><ul class="small">{through}</ul><ul class="small">{sources}</ul>
<p class="small">Market data and statements are taken from third-party websites, may be delayed, restated, incomplete or wrong, and were not checked against exchange filings. Risk-free rate, equity risk
premium and terminal growth are configured assumptions, not live market data.</p>
<h3>6. Use of artificial intelligence</h3><p class="small">Every figure is computed by code and traced to a source in the exported data. A language model writes prose only and may cite figures but not create them; sentences
containing untraceable numbers are removed. Section origin: {_e(origin) or "n/a"}. Language models can misread sources or omit context; sections tagged AI INTERPRETATION are interpretation, not fact.</p>
<h3>7. Verification status: {_e(a["status"])}</h3><ul class="small">{findings}</ul>
<h3>8. Limitations of this report</h3><ul class="small">{limits}<li><b>Forecasts and valuations</b> are estimates from stated assumptions and can be materially wrong; scenarios and Monte Carlo ranges are illustrations, not probabilities of real outcomes.</li>
<li><b>Peer sets</b> are fixed lists of listed companies and may not be true comparables.</li><li><b>Statements</b> follow screener.in's {_e(c["basis"])} presentation; leases and associates are not separately adjusted.</li></ul>
<h3>9. Risk warning</h3><p class="small">Investing in securities involves risk, including loss of capital. Past performance is not indicative of future results. Do not rely on this report as the sole basis for any decision.</p>
<h3>10. Reproducibility and attribution</h3><p class="small">The JSON export contains every input, assumption and result. Some valuation design ideas are adapted from open-source work; see THIRD_PARTY_NOTICES.md in the ARIA repository.</p>
</section>'''
    return _for_fund(html) if r.get("kind") == "fund_analysis" else html


def _swap(html: str, start: str, end: str, new: str) -> str:
    a, b = html.index(start), html.index(end)
    return html[:a] + new + html[b:]


def _for_fund(html: str) -> str:
    """Fund reports have no fair value, stance or language model: replace the sections that would be false for them."""
    parts = {
        ("<h3>2.", "<h3>3."): "<h3>2. No analyst certification</h3><p>No human analyst prepared, reviewed or certified this report, and it expresses no personal opinion about the scheme.</p>",
        ("<h3>4.", "<h3>5."): ("<h3>4. How to read the metrics</h3><p class='small'>All measures are backward-looking and computed from the scheme's NAV history (growth option). "
                               "They describe what happened, not what will happen, and ARIA does not rate or rank funds. Returns are compound annual growth between two NAV dates; "
                               "volatility, Sharpe and Sortino use daily NAV returns; the benchmark is the Nifty 50 price index.</p>"),
        ("<h3>6.", "<h3>7."): "<h3>6. Use of artificial intelligence</h3><p class='small'>No language model wrote any part of this report. Every figure is computed by code from the data sources listed.</p>",
        ("<h3>8.", "<h3>9."): ("<h3>8. Limitations of this report</h3><ul class='small'><li><b>Not investment advice.</b> Suitability depends on your goals, horizon and risk tolerance.</li>"
                               "<li><b>Returns</b> are for the growth option and ignore taxes, exit loads and stamp duty; the plan (Direct or Regular) matters for cost.</li>"
                               "<li>Missing data is listed in the section above.</li></ul>"),
    }
    for (start, end), new in parts.items():
        html = _swap(html, start, end, new)
    return html.replace("Investing in securities involves risk, including loss of capital.",
                        "Mutual fund investments are subject to market risks; read all scheme-related documents carefully. Investing involves risk, including loss of capital.")


def _number(sections: list[str]) -> list[str]:
    return [re.sub(r'<span class="n">\d+</span>', f'<span class="n">{i}</span>', s, count=1) for i, s in enumerate(sections, 1)]


def render_html(report: dict, kind: str | None = None, *, printable: bool = False, autoprint: bool = False) -> str:
    kind = kind if kind in KINDS else (report.get("kind") if report.get("kind") in KINDS else "equity_research")
    title, keys = KINDS[kind]
    c, meta = report["cover"], report.get("meta") or {}
    version = f'v{meta["version"]}' if meta.get("version") else "draft"
    status_ok = report["status"] == "publishable"
    legend = " ".join(f"{tag(k)}" for k in ("actual", "calculated", "estimate", "assumption", "source", "ai"))
    body = "".join(_number([f for f in (_SECTIONS[k](report) for k in keys) if f] + [_disclosure(report)]))
    price = f'{fmt(c["price"], "₹")}' if c["price"] else "n/a"
    through = "".join(f"<div><b>{_e(k)}</b>{_e(v)}</div>" for k, v in c["data_through"].items())
    bar = ('<div class="bar noprint"><button onclick="window.print()">Save as PDF / Print</button></div>' if printable else "")
    auto = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),400))</script>" if autoprint else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(report["title"])} — {_e(title)} — {_e(version)}</title><style>{CSS}</style></head><body>{bar}<div class="page">
<header class="cover"><div class="small" style="opacity:.8;letter-spacing:.08em;text-transform:uppercase">{_e(title)}</div><h1>{_e(c["name"])}</h1><div class="sub">{_e(c["symbol"])} · {_e(c["exchange"])} · {_e(c["sector"])} / {_e(c["industry"])}</div>
<div class="meta"><div><b>Price</b>{_e(price)}</div><div><b>Market cap</b>{_e(fmt(c["market_cap_cr"], "₹ Cr"))}</div><div><b>Report date</b>{_e(c["report_date"])}</div>
<div><b>Version</b>{_e(version)}</div>{through}<div><b>Verification</b><span class="pill {"ok" if status_ok else "warn"}">{"Passed" if status_ok else "Caveated"}</span></div></div>
<p class="small" style="opacity:.85;margin:12px 0 0">{_e(c["ai_disclosure"])} Not investment advice; see the disclosures on the last page.</p></header>
<div class="legend">Every figure is tagged: {legend}</div><main>{body}</main></div>{auto}</body></html>'''
