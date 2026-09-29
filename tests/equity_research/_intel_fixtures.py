"""Offline fixtures for the equity-research intelligence tests.

Synthetic but internally consistent companies, built through the SAME ``build_snapshot``
path production uses. "TESTCO" is an operating company (10% revenue growth, 20% EBITDA
margin, 100 Cr shares); "TESTBANK" is a bank. No network, no LLM.
"""
from __future__ import annotations

import json
import random
import re
from datetime import date, timedelta

from modules.equity_research.intelligence.data import Peer, Snapshot, Target, build_snapshot

FYS = [f"Mar {y}" for y in range(2020, 2027)]
QUARTERS = ["Jun 2023", "Sep 2023", "Dec 2023", "Mar 2024", "Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025",
            "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"]
SHARES = 1e9  # 100 Cr shares


def _s(x: float, pct: bool = False) -> str:
    return f"{x:.0f}%" if pct else f"{x:,.0f}"


def _table(cols: list[str], rows: dict[str, list]) -> dict:
    return {"__columns__": cols, **{name: dict(zip(cols, [_s(v) if not isinstance(v, str) else v for v in vals])) for name, vals in rows.items()}}


def operating_raw(*, growth: float = 0.10, opm: float = 0.20, minority: float = 1.0, view: str = "consolidated") -> dict:
    sales = [1000 * (1 + growth) ** i for i in range(7)]
    op = [opm * x for x in sales]
    dep = [0.04 * x for x in sales]
    pbt = [o - d - 10 + 20 for o, d in zip(op, dep)]
    pat = [0.75 * p for p in pbt]
    eps = [p * minority / 100 for p in pat]
    cols = FYS + ["TTM"]
    ttm = lambda v: v[-1] * 1.05  # noqa: E731
    pl = {
        "Sales": sales + [ttm(sales)], "Expenses": [a - b for a, b in zip(sales, op)] + [ttm(sales) - ttm(op)],
        "Operating Profit": op + [ttm(op)], "OPM %": [_s(opm * 100, True)] * 8, "Other Income": [20] * 8,
        "Interest": [10] * 8, "Depreciation": dep + [ttm(dep)], "Profit before tax": pbt + [ttm(pbt)],
        "Tax %": [_s(25, True)] * 7 + [""], "Net Profit": pat + [ttm(pat)],
        "EPS in Rs": [f"{e:.2f}" for e in eps + [ttm(eps)]], "Dividend Payout %": [_s(20, True)] * 7 + [""],
    }
    reserves = [500 + 150 * i for i in range(7)]
    bs = {"Equity Capital": [100] * 7, "Reserves": reserves, "Borrowings": [300] * 7, "Other Liabilities": [400] * 7,
          "Total Liabilities": [1300 + r for r in reserves], "Fixed Assets": [800] * 7, "CWIP": [50] * 7,
          "Investments": [100] * 7, "Other Assets": [500 + r for r in reserves], "Total Assets": [1300 + r for r in reserves]}
    cfo = [1.1 * p for p in pat]
    capex = [0.08 * x for x in sales]
    cf = {"Cash from Operating Activity": cfo, "Cash from Investing Activity": [-c for c in capex], "Cash from Financing Activity": [-50] * 7,
          "Net Cash Flow": [10] * 7, "Free Cash Flow": [a - b for a, b in zip(cfo, capex)], "CFO/OP": [_s(110, True)] * 7}
    ratios = {"Debtor Days": [40] * 7, "Inventory Days": [30] * 7, "Days Payable": [33.5] * 7, "Cash Conversion Cycle": [36.5] * 7,
              "Working Capital Days": [36.5] * 7, "ROCE %": [_s(18, True)] * 7}
    q_sales = [sales[-1] / 4 * (1 + 0.02 * j) for j in range(13)]
    quarterly = {"Sales": q_sales, "Operating Profit": [0.2 * x for x in q_sales], "Net Profit": [0.1 * x for x in q_sales],
                 "EPS in Rs": [f"{0.1 * x / 100:.2f}" for x in q_sales]}
    return {"profit_loss": _table(cols, pl), "balance_sheet": _table(FYS, bs), "cash_flow": _table(FYS, cf), "ratios": _table(FYS, ratios),
            "quarterly_results": _table(QUARTERS, quarterly), "view": view}


def bank_raw(*, view: str = "consolidated") -> dict:
    rev = [1000 * 1.12 ** i for i in range(7)]
    pbt = [0.30 * x for x in rev]
    pat = [0.75 * p for p in pbt]
    cols = FYS + ["TTM"]
    ttm = lambda v: v[-1] * 1.04  # noqa: E731
    pl = {"Revenue": rev + [ttm(rev)], "Interest": [0.5 * x for x in rev + [ttm(rev)]], "Expenses": [0.3 * x for x in rev + [ttm(rev)]],
          "Financing Profit": [-0.05 * x for x in rev + [ttm(rev)]], "Other Income": [0.5 * x for x in rev + [ttm(rev)]],
          "Depreciation": [5] * 8, "Profit before tax": pbt + [ttm(pbt)], "Tax %": [_s(25, True)] * 7 + [""],
          "Net Profit": pat + [ttm(pat)], "EPS in Rs": [f"{p / 100:.2f}" for p in pat + [ttm(pat)]], "Dividend Payout %": [_s(25, True)] * 7 + [""]}
    res = [800 + 200 * i for i in range(7)]
    bs = {"Equity Capital": [100] * 7, "Reserves": res, "Deposits": [8000 + 1000 * i for i in range(7)], "Borrowing": [900] * 7,
          "Other Liabilities": [300] * 7, "Total Liabilities": [10000 + 1200 * i for i in range(7)], "Fixed Assets": [50] * 7,
          "CWIP": [0] * 7, "Investments": [2000] * 7, "Other Assets": [7000] * 7, "Total Assets": [10000 + 1200 * i for i in range(7)]}
    cf = {"Cash from Operating Activity": [500] * 7, "Cash from Investing Activity": [-20] * 7, "Cash from Financing Activity": [-100] * 7,
          "Net Cash Flow": [10] * 7, "Free Cash Flow": [480] * 7}
    q = {"Revenue": [rev[-1] / 4] * 13, "Net Profit": [pat[-1] / 4 * (1 + 0.01 * j) for j in range(13)], "Gross NPA %": ["1.20%"] * 13,
         "Net NPA %": ["0.40%"] * 13}
    return {"profit_loss": _table(cols, pl), "balance_sheet": _table(FYS, bs), "cash_flow": _table(FYS, cf),
            "ratios": {"__columns__": FYS, "ROE %": dict(zip(FYS, ["14%"] * 7))}, "quarterly_results": _table(QUARTERS, q), "view": view}


def weekly(seed: int = 1, n: int = 260, beta: float = 1.2) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    rng = random.Random(seed)
    day, stock, index = date(2021, 10, 4), 100.0, 10000.0
    s_out, i_out = [], []
    for _ in range(n):
        m = rng.gauss(0.002, 0.02)
        stock *= 1 + beta * m + rng.gauss(0, 0.004)
        index *= 1 + m
        s_out.append((day.isoformat(), stock))
        i_out.append((day.isoformat(), index))
        day += timedelta(days=7)
    return s_out, i_out


def peers(n_artifact: bool = True) -> list[Peer]:
    rows = [("AAA", 18, 3.0, 10, 12000), ("BBB", 20, 3.5, 12, 18000), ("CCC", 22, 4.0, 14, 9000),
            ("DDD", 24, 4.5, 16, 20000), ("EEE", 150, 30, 905.9 if n_artifact else 18, 15000), ("FFF", 26, 5.0, 18, 10000)]
    return [Peer(sym, sym + " Ltd", pe, pb, ev, mc) for sym, pe, pb, ev, mc in rows]


def operating_info(**over) -> dict:
    info = {
        "longName": "Testco Limited", "shortName": "TESTCO", "sector": "Technology", "industry": "Information Technology Services",
        "currentPrice": 150.0, "marketCap": 150.0 * SHARES, "sharesOutstanding": SHARES, "trailingPE": 15.0, "priceToBook": 2.5,
        "bookValue": 60.0, "trailingEps": 10.0, "enterpriseValue": 150.0 * SHARES + 100 * 1e7, "enterpriseToEbitda": 8.0,
        "totalDebt": 300 * 1e7, "totalCash": 200 * 1e7, "dividendRate": 2.0, "fiftyTwoWeekHigh": 170.0, "fiftyTwoWeekLow": 110.0,
        "targetMeanPrice": 180.0, "targetHighPrice": 210.0, "targetLowPrice": 150.0, "numberOfAnalystOpinions": 12,
        "longBusinessSummary": "Testco Limited provides software services to banks. It is headquartered in Pune.",
        "companyOfficers": [{"name": "A. Founder", "title": "Chairman"}],
    }
    return {**info, **over}


def bank_info(**over) -> dict:
    return {**operating_info(), "longName": "Testbank Limited", "sector": "Financial Services", "industry": "Banks - Regional",
            "bookValue": 120.0, "trailingEps": 11.0, "priceToBook": 1.5, "currentPrice": 180.0, "marketCap": 180.0 * SHARES,
            "enterpriseToEbitda": None, **over}


def make_snapshot(kind: str = "operating", *, raw: dict | None = None, info: dict | None = None, peer_list: list[Peer] | None = None,
                  news: list[dict] | None = None, beta: float = 1.2, nci_cr: float | None = 50.0, warnings: list[str] | None = None) -> Snapshot:
    stock, index = weekly(beta=beta)
    is_bank = kind == "bank"
    return build_snapshot(
        Target("TESTBANK" if is_bank else "TESTCO", "TESTBANK.NS" if is_bank else "TESTCO.NS", "Test"),
        screener_raw=raw if raw is not None else (bank_raw() if is_bank else operating_raw()),
        info=info if info is not None else (bank_info() if is_bank else operating_info()),
        nci_cr=nci_cr, stock_weekly=stock, index_weekly=index,
        peers=peer_list if peer_list is not None else peers(), news=news if news is not None else [
            {"title": "Testco wins a large banking contract", "source": "Wire", "date": "2026-09-20"},
            {"title": "Testco announces a share buyback", "source": "Wire", "date": "2026-09-25"}],
        warnings=warnings, as_of="2026-09-29")


# ── a fake LLM that answers by role and cites real evidence ids ────────────
def evidence_id(prompt: str, label: str) -> str:
    m = re.search(rf"^(E\d+): {re.escape(label)}(?= \[| =)", prompt, re.M)
    assert m, f"no evidence line for {label!r}"
    return m.group(1)


def find_id(prompt: str, label: str) -> str | None:
    m = re.search(rf"^(E\d+): {re.escape(label)}(?= \[| =)", prompt, re.M)
    return m.group(1) if m else None


def first_id(prompt: str) -> str:
    return re.search(r"^(E\d+):", prompt, re.M).group(1)


def role_of(system: str) -> str:
    if "chair the investment committee" in system:
        return "judge"
    if "long-side PM" in system:
        return "bull"
    if "short-side PM" in system:
        return "bear"
    return "analyst"


class FakeLLM:
    """Set ``analyst`` / ``bull`` / ``bear`` / ``judge`` to a dict, a str, or a callable(prompt) -> dict/str."""

    def __init__(self, **roles):
        self.roles = roles
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt, system_prompt=None, model=None):
        role = role_of(system_prompt or "")
        self.calls.append((role, prompt))
        reply = self.roles.get(role)
        reply = reply(prompt) if callable(reply) else reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    def count(self, role: str) -> int:
        return sum(1 for r, _ in self.calls if r == role)


def good_analyst(prompt: str) -> dict:
    rev, opm, gr = find_id(prompt, "Revenue"), find_id(prompt, "EBITDA margin"), find_id(prompt, "Revenue growth (YoY)")
    fin = " ".join(x for x in (f"Revenue was {{{{{rev}}}}}." if rev else "", f"Growth was {{{{{gr}}}}}." if gr else "",
                               f"The EBITDA margin was {{{{{opm}}}}}." if opm else "", f"The first figure was {{{{{first_id(prompt)}}}}}.") if x)
    return {
        "business_overview": "Testco provides software services to banks and is headquartered in Pune [S1].",
        "financial_analysis": fin,
        "valuation_view": "The valuation rests on the cost of capital and terminal growth assumptions.",
        "thesis": ["Steady compounding of revenue at a stable margin."],
        "risks": [{"category": "business", "text": "Client concentration in banking could hurt demand [S1]."}],
        "catalysts": ["A large banking contract win could lift revenue [N1]."],
    }


def good_side(label: str):
    def build(prompt: str) -> dict:
        return {"arguments": [{"claim": f"The {label.lower()} supports this view.", "evidence_ids": [find_id(prompt, label) or first_id(prompt)]}]}
    return build


GOOD_JUDGE = {"call": "HOLD", "conviction": 0.5, "swing_factor": "Whether the growth assumption holds.", "change_my_mind": "A sharp margin decline."}


def good_llm() -> FakeLLM:
    return FakeLLM(analyst=good_analyst, bull=good_side("EBITDA margin"), bear=good_side("Debt / equity"), judge=GOOD_JUDGE)
