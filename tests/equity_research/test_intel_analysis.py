"""Statement analysis, the provenance ledger, and the valuation assembled from a snapshot."""
import math

import pytest
from _intel_fixtures import bank_info, bank_raw, make_snapshot, operating_info, operating_raw

from modules.equity_research.intelligence.analysis import analyze, cagr, median_recent
from modules.equity_research.intelligence.facts import ASSUMPTION, CALCULATED, RAW, Ledger, fmt
from modules.equity_research.intelligence.valuation import value_company


def run(kind="operating", **kw):
    snap = make_snapshot(kind, **kw)
    ledger = Ledger()
    an = analyze(snap, ledger)
    return snap, ledger, an


# ── ledger / provenance ────────────────────────────────────────────────────
def test_ledger_rejects_unsourced_and_non_finite_facts():
    ledger = Ledger()
    with pytest.raises(ValueError):
        ledger.add("x", 1.0, "", "", "", RAW)
    with pytest.raises(ValueError):
        ledger.add("x", math.nan, "", "", "src", RAW)
    with pytest.raises(ValueError):
        ledger.add("x", 1.0, "", "", "src", "made-up")


def test_fmt_is_the_single_number_formatter():
    assert fmt(12.345, "%") == "12.3%" and fmt(-1.5, "x") == "-1.5x" and fmt(1234.5, "₹") == "₹1,234.50"
    assert fmt(504026, "₹ Cr") == "₹504,026 Cr" and fmt(None, "%") == "n/a" and fmt(-40, "₹ Cr") == "-₹40.0 Cr"


def test_every_fact_has_source_kind_and_calculated_facts_say_how():
    _, ledger, an = run()
    snap = make_snapshot()
    value_company(snap, an, ledger)
    assert len(ledger) > 40
    ids = [f.id for f in ledger]
    assert len(ids) == len(set(ids))
    for f in ledger:
        assert f.source and f.kind in (RAW, CALCULATED, ASSUMPTION)
        if f.kind != RAW:
            assert f.method or f.inputs, f"{f.label} does not say how it was derived"
        for i in f.inputs:
            assert ledger.get(i) is not None


# ── growth / TTM ───────────────────────────────────────────────────────────
def test_growth_is_fiscal_year_over_fiscal_year_never_ttm():
    _, ledger, an = run()
    assert an.latest == "Mar 2026" and "TTM" not in an.years
    assert an.facts["rev_growth"].value == pytest.approx(10.0, abs=0.01)
    assert an.facts["revenue_ttm"].period == "TTM" and an.facts["revenue_ttm"].value == pytest.approx(an.facts["revenue"].value * 1.05, rel=1e-3)
    assert an.facts["rev_cagr3"].value == pytest.approx(10.0, abs=0.05)


def test_cagr_and_median_helpers():
    assert cagr([100, None, 121], 2) == pytest.approx(0.10)
    assert cagr([100, 121], 2) is None and cagr([-5, 10, 12], 2) is None
    assert median_recent([1, None, 3, 100, 5], 3) == 5 and median_recent([None, None]) is None


def test_debt_to_equity_uses_net_worth_not_share_capital():
    _, _, an = run()
    net_worth = 100 + 500 + 150 * 6  # equity capital + reserves, FY2026
    assert an.series["net_worth"]["Mar 2026"] == net_worth
    assert an.facts["de"].value == pytest.approx(300 / net_worth)


def test_roe_is_scaled_to_the_shareholders_share_when_profit_includes_minorities():
    plain = run(raw=operating_raw(minority=1.0))[2]
    minority = run(raw=operating_raw(minority=0.8))[2]
    assert minority.attributable == pytest.approx(0.8, abs=0.01)
    assert minority.facts["roe"].value == pytest.approx(plain.facts["roe"].value * 0.8, rel=0.02)
    assert "attributable" in minority.facts["roe"].method


def test_margin_uses_operating_profit_over_revenue_not_the_rounded_screener_row():
    _, _, an = run(raw=operating_raw(opm=0.2345))
    assert an.facts["opm"].value == pytest.approx(23.45, abs=0.1)  # fixture rows are whole numbers; the rounded OPM % row would say 23


def test_capex_is_derived_from_operating_and_free_cash_flow():
    _, _, an = run()
    assert an.facts["capex_pct"].value == pytest.approx(8.0, abs=0.1)
    assert an.facts["cfo_pat"].value == pytest.approx(1.1, abs=0.01)


# ── banks ──────────────────────────────────────────────────────────────────
def test_bank_branch_uses_pre_tax_profit_and_asset_quality():
    snap, ledger, an = run("bank")
    assert snap.is_financial
    assert an.facts["ebitda"].label == "Profit before tax" and an.facts["opm"].value == pytest.approx(30.0, abs=0.1)
    assert an.facts["net_npa"].value == pytest.approx(0.40) and an.facts["gross_npa"].value == pytest.approx(1.20)
    assert "de" not in an.facts and "leverage" in an.facts
    assert "EV / EBITDA" not in {f.label for f in ledger}


# ── missing / degraded data ────────────────────────────────────────────────
def test_no_statements_degrades_without_crashing():
    snap, ledger, an = run(raw={"error": "screener down"}, warnings=["boom"])
    assert an.latest is None and "Financial statements" in ledger.missing
    assert "screener down" in " ".join(snap.warnings)
    assert an.facts["price"].value == 150.0  # market facts still there


def test_missing_fields_are_recorded_as_missing_not_invented():
    info = {k: v for k, v in operating_info().items() if k not in ("trailingPE", "targetMeanPrice")}
    _, ledger, an = run(info=info)
    assert "pe" not in an.facts and "target_mean" not in an.facts
    assert "P/E (trailing)" in ledger.missing


def test_standalone_basis_is_warned():
    snap, _, _ = run(raw=operating_raw(view="standalone"))
    assert any("standalone" in w for w in snap.warnings)


# ── the valuation built from this snapshot ─────────────────────────────────
def test_operating_company_gets_dcf_and_peer_methods_with_inputs_registered():
    snap, ledger, an = run()
    val = value_company(snap, an, ledger)
    assert {m.key for m in val.methods} == {"dcf", "comps_pe", "comps_ev_ebitda"}
    assert val.synthesis is not None and val.synthesis.rating in ("BUY", "HOLD", "SELL")
    inputs = {f.label for f in ledger if f.tag == "model_input"}
    assert {"Risk-free rate", "Equity risk premium", "Beta (used)", "WACC", "Terminal growth", "Forecast EBITDA margin", "Net debt"} <= inputs
    # the EV/EBITDA artifact (905.9x) never reaches a median
    assert 905.9 not in [v for st in [val.comps["medians"]] for v in st.values()]
    assert any(d["value"] == 905.9 for d in val.comps["excluded"]["ev_ebitda"])


def test_bank_gets_ddm_justified_pb_and_peer_multiples():
    snap, ledger, an = run("bank")
    val = value_company(snap, an, ledger)
    assert {m.key for m in val.methods} == {"ddm", "justified_pb", "comps_pe", "comps_pb"}
    assert all(m.low <= m.mid <= m.high for m in val.methods)


def test_incomparable_peer_set_is_skipped_with_a_reason():
    from modules.equity_research.intelligence.data import Peer

    tiny = [Peer(s, s, 10, 2, 8, 500.0) for s in "ABCDE"]  # subject is 30x larger
    snap, ledger, an = run(peer_list=tiny)
    val = value_company(snap, an, ledger)
    assert {m.key for m in val.methods} == {"dcf"}
    assert "not comparable" in val.skipped["comps_pe"]


def test_too_few_peers_and_no_statements_fall_back_gracefully():
    snap, ledger, an = run(raw={"error": "x"}, peer_list=[])
    val = value_company(snap, an, ledger)
    assert val.synthesis is None and val.skipped
    priceless = make_snapshot(info={"sector": "Technology"})
    priceless.closes = []
    assert value_company(priceless, an, Ledger()).skipped["all"] == "no share price available"


def test_negative_margin_company_skips_dcf_with_reason():
    snap, ledger, an = run(raw=operating_raw(opm=-0.05))
    val = value_company(snap, an, ledger)
    assert "dcf" in val.skipped and "margin" in val.skipped["dcf"]


def test_macro_assumptions_are_configurable(monkeypatch):
    from config import settings

    snap, ledger, an = run()
    base = value_company(snap, an, ledger).dcf_result.per_share
    monkeypatch.setattr(settings, "FI_EQUITY_RISK_PREMIUM", 0.09)
    snap2, ledger2, an2 = run()
    assert value_company(snap2, an2, ledger2).dcf_result.per_share < base
