"""
Mutual-fund analysis from public NAV history (mfapi.in), benchmarked to the Nifty 50 price index.

Descriptive only: returns, risk, SIP outcomes, calendar-year and rolling returns, and the fund's rank among the
schemes in its AMFI category (AMFI's daily NAV file lists every scheme with its category). ARIA does not rate or
recommend funds. The public sources carry no holdings, expense ratio, AUM, turnover or fund-manager data, and the
report says so instead of inventing them. Every number is computed here from NAV series.
"""
from __future__ import annotations

import bisect
import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

import requests
from loguru import logger

from config import settings
from modules.equity_research.intelligence.data import _ttl_cache
from modules.equity_research.intelligence.facts import fmt
from modules.equity_research.intelligence.report_html import CSS, _disclosure, _e, _number, _table, bars, tag

API = "https://api.mfapi.in/mf"
AMFI_NAV = "https://portal.amfiindia.com/spages/NAVAll.txt"
BENCHMARK = "Nifty 50 (price index, excludes dividends)"
# An index fund's NAV is the Nifty 50 with dividends reinvested, less its costs: a total-return benchmark that is public.
TRI_PROXY_CODE = 120716  # UTI Nifty 50 Index Fund - Direct Plan - Growth
TRI_PROXY = ("Nifty 50 total-return proxy: the NAV of UTI Nifty 50 Index Fund (Direct, Growth), which tracks the index with dividends "
             "reinvested, less about 0.2% a year in costs")
MAX_CATEGORY = 150  # ponytail: ranks are computed on the fly; bigger categories (index funds) are skipped, not sampled
_DEBT = re.compile(r"debt scheme|liquid|overnight|money market|gilt", re.IGNORECASE)
_PHRASES = ("mutual fund analysis", "mutual fund report", "fund analysis", "fund report", "fund review")
_NOISE = re.compile(r"\b(give me|generate|make|create|please|an?|the|full|detailed|mutual fund analysis|mutual fund report|fund analysis|fund report|fund review|"
                    r"analysis|report|review|of|on|for|about)\b", re.IGNORECASE)
_NOT_PLAN = re.compile(r"idcw|dividend|bonus|payout|reinvest", re.IGNORECASE)


def is_fund_query(query: str) -> bool:
    return any(p in query.lower() for p in _PHRASES)


# ── data ───────────────────────────────────────────────────────────────────
def fund_name_from(query: str) -> str:
    return re.sub(r"\s+", " ", _NOISE.sub(" ", query)).strip(" ?.,")


def pick_scheme(results: list[dict], query: str) -> dict | None:
    """Prefer the Direct Growth plan unless the user asked for Regular or a dividend option. Legacy plans named neither
    Direct nor Regular (e.g. "Premium Plus") rank below the plan asked for; ties go to the shortest name."""
    q = query.lower()
    want_regular, want_div = "regular" in q, bool(_NOT_PLAN.search(q))

    def score(r: dict) -> tuple[int, int]:
        n = r["schemeName"].lower()
        plan = ("regular" in n) * 4 + ("direct" not in n and "regular" not in n) * 2 if want_regular else ("direct" in n) * 4
        return plan + ("growth" in n) * 2 + (bool(_NOT_PLAN.search(n)) == want_div) * 3, -len(n)
    return max(results, key=score, default=None)


def find_scheme(name: str, query: str) -> dict | None:
    """Active schemes (AMFI's daily NAV file) whose name contains every word of ``name``, best plan first. mfapi's own
    search is capped at 15 hits and includes closed plans, so it is only the fallback."""
    words = set(re.findall(r"[a-z0-9]+", name.lower()))
    try:
        hits = [{"schemeCode": s["code"], "schemeName": s["name"]} for ss in _amfi_schemes().values() for s in ss
                if words <= set(re.findall(r"[a-z0-9]+", s["name"].lower()))]
    except Exception as exc:
        logger.warning(f"AMFI scheme list unavailable, using mfapi search: {exc}")
        hits = []
    if not hits:
        hits = requests.get(f"{API}/search", params={"q": name}, timeout=15, headers={"User-Agent": "ARIA/1.0"}).json()
    return pick_scheme(hits, query)


@_ttl_cache(3600)
def _nav_history(code: int) -> dict:
    res = requests.get(f"{API}/{code}", timeout=20, headers={"User-Agent": "ARIA/1.0"})
    res.raise_for_status()
    return res.json()


@_ttl_cache(3600)
def _nifty() -> tuple[list[date], list[float]]:
    import yfinance as yf

    hist = yf.Ticker("^NSEI").history(period="max", interval="1d")["Close"].dropna()
    return [d.date() for d in hist.index], [float(v) for v in hist.values]


# A one-day NAV move outside this band is a unit restructuring (HDFC Liquid Fund, 30 Aug 2015: 28.56 -> 2,857.24 when the
# face value went from 10 to 1,000), not a return. No diversified fund moves 30% down or 40% up in a day.
_BREAK = (0.7, 1.4)


def _raw_nav(payload: dict) -> list[tuple[date, float]]:
    rows = []
    for r in payload.get("data", []):
        try:
            rows.append((datetime.strptime(r["date"], "%d-%m-%Y").date(), float(r["nav"])))
        except (KeyError, ValueError):
            continue
    return sorted({d: n for d, n in rows if n > 0}.items())


def restructurings(payload: dict) -> list[dict]:
    rows = _raw_nav(payload)
    return [{"date": rows[i][0].isoformat(), "from": rows[i - 1][1], "to": rows[i][1]} for i in range(1, len(rows))
            if not _BREAK[0] <= rows[i][1] / rows[i - 1][1] <= _BREAK[1]]


def parse_nav(payload: dict) -> tuple[list[date], list[float]]:
    """NAV series, oldest first, with NAVs before each unit restructuring rescaled so the series is continuous (the
    restructuring day counts as a zero return). Every caller -- fund, category peers, benchmark -- gets the same series."""
    rows = _raw_nav(payload)
    raw = [n for _, n in rows]
    out, factor = [0.0] * len(raw), 1.0
    for i in range(len(raw) - 1, -1, -1):
        out[i] = raw[i] * factor
        if i and not _BREAK[0] <= raw[i] / raw[i - 1] <= _BREAK[1]:
            factor *= raw[i] / raw[i - 1]
    return [d for d, _ in rows], out


def _norm_cat(s: str) -> str:
    return re.sub(r"\bschemes\b", "scheme", s.strip().lower())


def parse_amfi(text: str) -> dict[str, list[dict]]:
    """AMFI's NAVAll.txt grouped by category: {category: [{code, direct, growth}]}. Category headings look like
    "Open Ended Schemes(Equity Scheme - Flexi Cap Fund)"; scheme rows are ';'-separated with the code first."""
    out: dict[str, list[dict]] = {}
    cat = None
    for line in text.splitlines():
        if line.startswith(("Open Ended", "Close Ended", "Interval")):
            m = re.search(r"\((.*)\)", line)
            cat = _norm_cat(m.group(1)) if m else None
            continue
        p = line.split(";")
        if cat and len(p) >= 6 and p[0].strip().isdigit():
            name = " - ".join(x.strip() for x in (p[3:6] if len(p) >= 8 else p[3:4]) if x.strip())
            text_ = name.lower()
            out.setdefault(cat, []).append({"code": int(p[0]), "name": name, "direct": "direct" in text_, "growth": "growth" in text_ and not _NOT_PLAN.search(text_)})
    return out


@_ttl_cache(86400)
def _amfi_schemes() -> dict[str, list[dict]]:
    res = requests.get(AMFI_NAV, timeout=30, headers={"User-Agent": "ARIA/1.0"})
    res.raise_for_status()
    return parse_amfi(res.content.decode("utf-8", "replace"))


def category_peers(meta: dict) -> dict:
    """Point-to-point 1/3/5-year CAGRs of every scheme in the fund's AMFI category with the same plan (Direct or Regular)
    and the growth option. Returns {"peers": [...], ...} or {"skipped": reason}. Never raises."""
    cat, name = _norm_cat(meta.get("scheme_category") or ""), (meta.get("scheme_name") or "").lower()
    direct = "direct" in name
    try:
        same = [s["code"] for s in _amfi_schemes().get(cat, []) if s["direct"] == direct and s["growth"]]
    except Exception as exc:
        logger.warning(f"AMFI scheme list unavailable: {exc}")
        return {"skipped": "AMFI's scheme list could not be fetched."}
    code = int(meta.get("scheme_code") or 0)
    same += [code] if code and code not in same else []
    if len(same) > MAX_CATEGORY:
        return {"skipped": f"The category has {len(same)} comparable schemes, too many to rank on the fly."}
    if len(same) < 5:
        return {"skipped": "Fewer than five comparable schemes in the category."}

    def one(c: int) -> dict | None:
        try:
            d, v = parse_nav(_nav_history(c))
            return {n: cagr(d, v, n) for n in (1, 3, 5)} if len(d) > 30 else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        peers = [p for p in pool.map(one, same) if p]
    return {"category": meta.get("scheme_category") or "", "plan": "Direct" if direct else "Regular", "n_schemes": len(same), "peers": peers}


def rank_in_category(mine: dict[int, float | None], peers: list[dict]) -> list[dict]:
    """The fund's rank (1 = highest return) among its category for each period with at least five schemes. ``peers``
    includes the fund itself."""
    out = []
    for n, v in sorted(mine.items()):
        vals = [p[n] for p in peers if p.get(n) is not None]
        if v is None or len(vals) < 5:
            continue
        better = sum(1 for x in vals if x > v)
        out.append({"years": n, "fund": v, "rank": better + 1, "of": len(vals), "quartile": min(4, 1 + 4 * better // len(vals)),
                    "median": statistics.median(vals), "best": max(vals), "worst": min(vals)})
    return out


# ── maths (pure) ───────────────────────────────────────────────────────────
def value_at(dates: list[date], vals: list[float], d: date) -> float | None:
    i = bisect.bisect_right(dates, d) - 1
    return vals[i] if i >= 0 else None


def _years_back(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - n, day=28)


def cagr(dates: list[date], vals: list[float], years: int) -> float | None:
    end = dates[-1]
    start_d = _years_back(end, years)
    if dates[0] > start_d:
        return None
    start = value_at(dates, vals, start_d)
    return (vals[-1] / start) ** (1 / years) - 1 if start else None


def xirr(flows: list[tuple[date, float]]) -> float | None:
    if not flows or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    d0 = flows[0][0]
    f = lambda r: sum(a / (1 + r) ** ((d - d0).days / 365) for d, a in flows)  # noqa: E731
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def sip(dates: list[date], vals: list[float], years: int, amount: float = 10_000.0) -> dict | None:
    end = dates[-1]
    start = _years_back(end, years)
    if dates[0] > start:
        return None
    units, flows = 0.0, []
    for k in range(years * 12):  # exactly one instalment per month, on the first NAV of the month
        m = start.month - 1 + k
        i = bisect.bisect_left(dates, date(start.year + m // 12, m % 12 + 1, 1))
        if i >= len(dates):
            break
        units += amount / vals[i]
        flows.append((dates[i], -amount))
    value = units * vals[-1]
    flows.append((end, value))
    x = xirr(flows)
    return {"years": years, "installments": len(flows) - 1, "invested": amount * (len(flows) - 1), "value": value, "xirr": x}


def daily_returns(vals: list[float]) -> list[float]:
    return [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]


def risk_stats(dates: list[date], vals: list[float], rf: float, years: int = 3) -> dict | None:
    cut = _years_back(dates[-1], years)
    idx = [i for i, d in enumerate(dates) if d >= cut]
    if len(idx) < 200:
        return None
    r = daily_returns([vals[i] for i in idx])
    # Annualise by how often this scheme actually publishes NAV: ~250 a year for equity funds, every calendar day for
    # liquid funds. Assuming 252 understated a liquid fund's return by a third and gave it a Sharpe of -9.
    span = (dates[idx[-1]] - dates[idx[0]]).days / 365.25
    ppy = len(r) / span if span > 0 else 252
    vol = statistics.pstdev(r) * math.sqrt(ppy)
    ann = statistics.fmean(r) * ppy
    downside = math.sqrt(statistics.fmean([min(0.0, x - rf / ppy) ** 2 for x in r])) * math.sqrt(ppy)
    return {"window_years": years, "volatility": vol, "sharpe": (ann - rf) / vol if vol else None,
            "sortino": (ann - rf) / downside if downside else None}


def max_drawdown(vals: list[float]) -> float:
    peak, worst = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def calendar_years(dates: list[date], vals: list[float], n: int = 8) -> list[tuple[int, float]]:
    last: dict[int, float] = {}
    for d, v in zip(dates, vals):
        last[d.year] = v
    years = sorted(last)
    return [(y, last[y] / last[y - 1] - 1) for y in years[1:]][-n:] if len(years) > 1 else []


def rolling(dates: list[date], vals: list[float], years: int = 3) -> dict | None:
    out, seen = [], set()
    for i, end in enumerate(dates):
        key = (end.year, end.month)
        if key in seen or _years_back(end, years) < dates[0]:
            continue
        seen.add(key)
        s = value_at(dates, vals, _years_back(end, years))
        if s:
            out.append((vals[i] / s) ** (1 / years) - 1)
    if len(out) < 12:
        return None
    return {"years": years, "min": min(out), "median": statistics.median(out), "max": max(out), "n": len(out)}


def beta_alpha(fd: list[date], fv: list[float], bd: list[date], bv: list[float], rf: float, years: int = 5) -> dict | None:
    """Monthly regression of the fund on the benchmark over the last ``years``: beta and annualised Jensen's alpha."""
    end, start = fd[-1], _years_back(fd[-1], years)
    months, x, y = [], [], []
    prev_f = prev_b = None
    for yr in range(start.year, end.year + 1):
        for mo in range(1, 13):
            eom = date(yr + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
            if eom < start or eom > end:
                continue
            f, b = value_at(fd, fv, eom), value_at(bd, bv, eom)
            if f and b and prev_f and prev_b:
                y.append(f / prev_f - 1); x.append(b / prev_b - 1)
            prev_f, prev_b = f, b
    if len(x) < 24:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    var = sum((a - mx) ** 2 for a in x)
    if not var:
        return None
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / var
    alpha = ((my - rf / 12) - beta * (mx - rf / 12)) * 12
    return {"beta": beta, "alpha": alpha, "months": len(x)}


# ── report ─────────────────────────────────────────────────────────────────
def build_fund_report(payload: dict, benchmark: tuple[list[date], list[float]] | None, *, today: date | None = None,
                      bench_label: str = BENCHMARK, no_bench_reason: str | None = None, category: dict | None = None) -> dict:
    meta = payload.get("meta", {})
    dates, vals = parse_nav(payload)
    if len(dates) < 30:
        raise ValueError("not enough NAV history")
    rf = settings.FI_RISK_FREE_RATE
    bd, bv = benchmark if benchmark else ([], [])
    rets = []
    for n in (1, 3, 5, 10):
        f = cagr(dates, vals, n)
        b = cagr(bd, bv, n) if bd and bd[0] <= _years_back(dates[-1], n) else None
        if f is not None:
            rets.append({"years": n, "fund": f, "benchmark": b, "excess": (f - b) if b is not None else None})
    incep_years = (dates[-1] - dates[0]).days / 365.25
    since = (vals[-1] / vals[0]) ** (1 / incep_years) - 1 if incep_years >= 1 else None
    risk = risk_stats(dates, vals, rf) or risk_stats(dates, vals, rf, years=1)
    ba = beta_alpha(dates, vals, bd, bv, rf) if bd else None
    fund = {"scheme_code": meta.get("scheme_code"), "name": meta.get("scheme_name", ""), "fund_house": meta.get("fund_house", ""),
            "category": meta.get("scheme_category", ""), "type": meta.get("scheme_type", ""), "nav": vals[-1], "nav_date": dates[-1].isoformat(),
            "inception": dates[0].isoformat(), "history_years": incep_years, "returns": rets, "since_inception": since,
            "risk": risk, "max_drawdown": max_drawdown(vals), "beta_alpha": ba, "calendar": calendar_years(dates, vals),
            "sip": [s for n in (1, 3, 5, 10) if (s := sip(dates, vals, n))], "rolling": rolling(dates, vals), "risk_free": rf,
            "nav_adjustments": restructurings(payload), "benchmark": bench_label if bd else None, "benchmark_short": "Nifty 50 total-return proxy" if bench_label == TRI_PROXY else "Nifty 50 price index",
            "no_benchmark_reason": no_bench_reason}
    cat = category or {"skipped": "Not computed for this report."}
    fund["category_rank"] = {k: v for k, v in cat.items() if k != "peers"} | {
        "ranks": rank_in_category({n: cagr(dates, vals, n) for n in (1, 3, 5)}, cat["peers"]) if "peers" in cat else []}
    name = fund["name"]
    report = {
        "kind": "fund_analysis", "title": f"{name} - mutual fund analysis", "status": "publishable",
        "company": {"name": name, "symbol": str(fund["scheme_code"]), "sector": fund["category"], "industry": fund["fund_house"], "price": vals[-1],
                    "market_cap_cr": None, "as_of": dates[-1].isoformat(), "basis": "NAV"},
        "stance": {"rating": None, "stance": "Not rated", "fair_value": None, "low": None, "high": None, "upside_pct": None, "confidence": None,
                   "withheld": True, "price": vals[-1], "notes": ["ARIA describes fund performance; it does not rate or recommend funds."]},
        "cover": {"name": name, "symbol": str(fund["scheme_code"]), "exchange": "AMFI", "sector": fund["category"], "industry": fund["fund_house"],
                  "price": vals[-1], "market_cap_cr": None, "report_date": (today or date.today()).isoformat(), "basis": "NAV history",
                  "data_through": {"latest NAV": fund["nav_date"], "history from": fund["inception"]},
                  "ai_disclosure": "Every figure is computed by code from the NAV history; no language model writes any part of this report."},
        "fund": fund, "audit": {"status": "publishable", "checks": [], "withhold_valuation": False},
        "sources": [{"source": "mfapi.in (AMFI NAV data)", "count": len(vals)},
                    {"source": ("mfapi.in (UTI Nifty 50 Index Fund NAV, total-return proxy)" if bench_label == TRI_PROXY else "Yahoo Finance (Nifty 50 index)") if bd else "no benchmark used", "count": len(bd)},
                    *([{"source": "AMFI daily NAV file (scheme categories) and mfapi.in", "count": len(cat["peers"])}] if "peers" in cat else [])],
        "not_available": [
            {"item": "Portfolio holdings, sector weights and concentration", "reason": "Not in the public NAV data."},
            {"item": "Expense ratio, AUM, turnover, exit load and fund manager", "reason": "Not in the public NAV data; check the scheme's factsheet."},
            {"item": "Star ratings", "reason": "Fund ratings are proprietary (for example Morningstar and Value Research) and are not reproduced."},
            *([{"item": "Category ranking", "reason": cat["skipped"]}] if "skipped" in cat else []),
            *([{"item": "Total-return benchmark (TRI)", "reason": "The Nifty 50 price index used here excludes dividends, so it understates benchmark returns by roughly the dividend yield."}]
              if bd and bench_label != TRI_PROXY else [])],
        "narrative_origin": {}, "facts": [], "disclaimer": "",
    }
    report["markdown"] = fund_markdown(report)
    return report


def summary_text(f: dict) -> str:
    r = {x["years"]: x for x in f["returns"]}
    best = r.get(3) or r.get(1)
    ret = (f"{fmt(best['fund'] * 100, '%')} a year over {best['years']} years" + (f" against {fmt(best['benchmark'] * 100, '%')} for the {f.get('benchmark_short', 'benchmark')}" if best["benchmark"] is not None else "")) if best else "not enough history for a multi-year return"
    risk = f["risk"]
    ranks = {x["years"]: x for x in (f.get("category_rank") or {}).get("ranks", [])}
    rk = ranks.get(3) or ranks.get(1)
    rank = f" Over {rk['years']} year{'s' if rk['years'] > 1 else ''} it ranks {rk['rank']} of {rk['of']} in its category (quartile {rk['quartile']})." if rk else ""
    return (f"Insight: {f['name']} has returned {ret} (NAV {fmt(f['nav'], '₹')} on {f['nav_date']}).\n"
            f"Analysis: since inception {fmt(f['since_inception'] * 100, '%') if f['since_inception'] is not None else 'n/a'} a year over {f['history_years']:.1f} years"
            + (f"; volatility {fmt(risk['volatility'] * 100, '%')}, Sharpe {fmt(risk['sharpe'], '')}" if risk and risk['sharpe'] is not None else "")
            + f"; worst peak-to-trough fall {fmt(f['max_drawdown'] * 100, '%')}.{rank}\n"
            "Recommendation: this is a descriptive analysis; ARIA does not rate or recommend funds, and past returns do not predict future returns.\n"
            f"Risk: mutual fund investments are subject to market risks; a fall of {fmt(abs(f['max_drawdown']) * 100, '%')} has happened before in this fund.")


def fund_markdown(r: dict) -> str:
    f = r["fund"]
    out = [f"# {r['title']}", "", f"{f['fund_house']} · {f['category']} · NAV {fmt(f['nav'], '₹')} on {f['nav_date']} · history since {f['inception']}", "", "## Returns (CAGR)"]
    out += [f"- {x['years']}y: fund {fmt(x['fund'] * 100, '%')}" + (f", benchmark {fmt(x['benchmark'] * 100, '%')}" if x['benchmark'] is not None else "") for x in f["returns"]]
    cr = f.get("category_rank") or {}
    if cr.get("ranks"):
        out += ["", f"## Rank in category ({cr['category']}, {cr['plan']} plans)"] + [f"- {x['years']}y: {x['rank']} of {x['of']}, quartile {x['quartile']}, category median {fmt(x['median'] * 100, '%')}" for x in cr["ranks"]]
    out += ["", "## SIP of ₹10,000 a month"] + [f"- {s['years']}y: invested {fmt(s['invested'], '₹')}, value {fmt(s['value'], '₹')}, XIRR {fmt(s['xirr'] * 100, '%') if s['xirr'] is not None else 'n/a'}" for s in f["sip"]]
    return "\n".join(out)


def _yrs(n: int) -> str:
    return f"{n} year" if n == 1 else f"{n} years"


def _cal_label(year: int, nav_date: str) -> str:
    """The latest calendar year is partial until December: say so."""
    return f"{year} YTD" if year == int(nav_date[:4]) and nav_date[5:] < "12-20" else str(year)


def _pct(x) -> str:
    return "n/a" if x is None else fmt(x * 100, "%")


def render_fund_html(r: dict, *, printable: bool = False, autoprint: bool = False) -> str:
    f, c, meta = r["fund"], r["cover"], r.get("meta") or {}
    version = f'v{meta["version"]}' if meta.get("version") else "draft"
    tiles = [(_pct(x["fund"]), f"{x['years']}-year " + ("return" if x["years"] == 1 else "CAGR")) for x in f["returns"]] + [(_pct(f["since_inception"]), "Since inception (CAGR)")]
    if f["risk"]:
        tiles += [(_pct(f["risk"]["volatility"]), f"Volatility ({f['risk']['window_years']}y)"), (fmt(f["risk"]["sharpe"], ""), "Sharpe ratio")]
    tiles.append((_pct(f["max_drawdown"]), "Maximum drawdown"))
    tile_html = "".join(f'<div class="tile"><div class="v">{_e(v)}</div><div class="l">{_e(l)}</div><div class="p">{tag("calculated")}</div></div>' for v, l in tiles)
    has_bench = any(x["benchmark"] is not None for x in f["returns"])
    ret_rows = [[_yrs(x["years"]), _pct(x["fund"])] + ([_pct(x["benchmark"]), _pct(x["excess"])] if has_bench else []) for x in f["returns"]]
    cr = f.get("category_rank") or {}
    rank_rows = [[_yrs(x["years"]), _pct(x["fund"]), _pct(x["median"]), _pct(x["best"]), _pct(x["worst"]), f'{x["rank"]} of {x["of"]}', str(x["quartile"])] for x in cr.get("ranks", [])]
    bench_text = f["benchmark"] or (f"not used: {f['no_benchmark_reason']}" if f.get("no_benchmark_reason") else "unavailable")
    adj = "".join(f" NAVs before {a['date']} are rescaled for a unit restructuring that day (NAV {fmt(a['from'], '₹')} to {fmt(a['to'], '₹')}), "
                  "so returns run through it continuously." for a in f.get("nav_adjustments") or [])
    cal = f["calendar"]
    cal_chart = bars("Calendar-year returns (%)", [_cal_label(y, f["nav_date"]) for y, _ in cal], [v * 100 for _, v in cal], "%") if cal else ""
    sip_rows = [[_yrs(s["years"]), _e(fmt(s["invested"], "₹")), _e(fmt(s["value"], "₹")), _pct(s["xirr"])] for s in f["sip"]]
    ba, ro, risk = f["beta_alpha"], f["rolling"], f["risk"]
    risk_rows = ([["Volatility (annualised)", _pct(risk["volatility"])], ["Sharpe ratio", fmt(risk["sharpe"], "")], ["Sortino ratio", fmt(risk["sortino"], "")]] if risk else []) + \
        [["Maximum drawdown (full history)", _pct(f["max_drawdown"])]] + \
        ([["Beta vs Nifty 50 (monthly, 5y)", fmt(ba["beta"], "")], ["Jensen's alpha (annualised)", _pct(ba["alpha"])]] if ba else [])
    rolling_html = (f'<h3>Rolling {ro["years"]}-year returns {tag("calculated")}</h3><p>Across {ro["n"]} monthly windows the fund\'s {ro["years"]}-year CAGR ranged from '
                    f'{_pct(ro["min"])} to {_pct(ro["max"])}, median {_pct(ro["median"])}. This shows how much the answer depends on when you started.</p>') if ro else ""
    na = "".join(f'<div class="na"><b>{_e(x["item"])}.</b> {_e(x["reason"])}</div>' for x in r["not_available"])
    sections = [
        f'<section><h2><span class="n">1</span>Performance snapshot</h2><div class="tiles">{tile_html}</div>{cal_chart and f"<div class=charts>{cal_chart}</div>"}</section>',
        f'<section><h2><span class="n">2</span>Returns vs benchmark</h2>{_table(["Period", "Fund CAGR"] + (["Benchmark CAGR", "Excess"] if has_bench else []), ret_rows) if ret_rows else "<p class=muted>Not enough history.</p>"}'
        f'<p class="muted small">Point-to-point compound annual growth of NAV (growth option). Benchmark: {_e(bench_text)}.{_e(adj)}</p>{rolling_html}</section>',
        *([f'<section><h2><span class="n">0</span>Category comparison {tag("calculated")}</h2>'
           f'{_table(["Period", "Fund CAGR", "Category median", "Best", "Worst", "Rank", "Quartile"], rank_rows)}'
           f'<p class="muted small">Ranked (1 = highest return) among the {cr["plan"]} Growth schemes in AMFI\'s &ldquo;{_e(cr["category"])}&rdquo; category with enough history: '
           f'{cr["n_schemes"]} schemes listed, {len(rank_rows) and max(x["of"] for x in cr["ranks"])} with data for the period shown. Past returns only; this is not a rating.</p></section>']
          if rank_rows else []),
        f'<section><h2><span class="n">3</span>Risk {tag("calculated")}</h2>{_table(["Measure", "Value"], [[_e(a), _e(b)] for a, b in risk_rows], text=(0,))}'
        f'<p class="muted small">Risk-free rate {fmt(f["risk_free"] * 100, "%")} (configured assumption). Volatility, Sharpe and Sortino use daily NAV returns.</p></section>',
        f'<section><h2><span class="n">4</span>SIP outcomes {tag("calculated")}</h2>{_table(["Period", "Invested", "Current value", "XIRR"], sip_rows) if sip_rows else "<p class=muted>Not enough history.</p>"}'
        f'<p class="muted small">Illustration: ₹10,000 invested on the first NAV date of each month, valued at the latest NAV. Past results do not predict future results.</p></section>',
        f'<section><h2><span class="n">5</span>Not available from the configured sources</h2>{na}</section>',
    ]
    sections = _number(sections + [_disclosure({**r, "kind": "fund_analysis"})])
    disc = sections.pop()
    bar = '<div class="bar noprint"><button onclick="window.print()">Save as PDF / Print</button></div>' if printable else ""
    auto = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),400))</script>" if autoprint else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(r["title"])} — {_e(version)}</title>'
            f'<style>{CSS}</style></head><body>{bar}<div class="page"><header class="cover"><div class="small" style="opacity:.8;letter-spacing:.08em;text-transform:uppercase">Mutual fund analysis</div>'
            f'<h1>{_e(c["name"])}</h1><div class="sub">{_e(f["category"])} · {_e(f["fund_house"])} · AMFI code {_e(c["symbol"])}</div><div class="meta"><div><b>Latest NAV</b>{_e(fmt(f["nav"], "₹"))}</div>'
            f'<div><b>NAV date</b>{_e(f["nav_date"])}</div><div><b>History from</b>{_e(f["inception"])}</div><div><b>Report date</b>{_e(c["report_date"])}</div><div><b>Version</b>{_e(version)}</div></div>'
            f'<p class="small" style="opacity:.85;margin:12px 0 0">{_e(c["ai_disclosure"])} Mutual fund investments are subject to market risks. Not investment advice; see the disclosures on the last page.</p></header>'
            f'<main>{"".join(sections)}{disc}</main></div>{auto}</body></html>')


def run_fund_report(query: str, user_id: str = "default") -> dict[str, Any]:
    from modules.equity_research.intelligence.pipeline import _message, _persist

    name = fund_name_from(query)
    if not name:
        return _message(query, None, "I could not tell which mutual fund you mean.", "The request did not name a scheme.",
                        "Try: mutual fund analysis of Parag Parikh Flexi Cap.", "Only schemes listed with AMFI are covered.")
    try:
        scheme = find_scheme(name, query)
        if not scheme:
            return _message(query, name, f"I could not find a mutual fund matching '{name}'.", "The AMFI scheme search returned nothing.",
                            "Check the fund name and try again.", "No report was generated.")
        payload = _nav_history(int(scheme["schemeCode"]))
        meta = payload.get("meta", {})
        bench, label, reason = None, BENCHMARK, None
        if _DEBT.search(meta.get("scheme_category") or ""):
            reason = "an equity index is not a meaningful benchmark for a debt fund; see the category comparison"
        else:
            try:
                bench, label = parse_nav(_nav_history(TRI_PROXY_CODE)), TRI_PROXY
            except Exception as exc:
                logger.warning(f"total-return proxy unavailable, falling back to the Nifty price index: {exc}")
                try:
                    bench = _nifty()
                except Exception as exc2:
                    logger.warning(f"Nifty history unavailable for the fund benchmark: {exc2}")
        report = build_fund_report(payload, bench, bench_label=label, no_bench_reason=reason, category=category_peers(meta))
    except Exception as exc:
        logger.warning(f"fund analysis failed for {name!r}: {exc}")
        return _message(query, name, f"I could not retrieve NAV data for '{name}'.", f"The data source failed: {exc}",
                        "Try again in a moment.", "No report was generated.")
    meta = _persist(user_id, report)
    return {"domain": "equity_research", "query": query, "company": report["company"]["name"], "metric": "Mutual Fund Analysis", "value": None,
            "response": summary_text(report["fund"]), "confidence": "medium", "fund_report": True, "report_id": meta["id"] if meta else None}
