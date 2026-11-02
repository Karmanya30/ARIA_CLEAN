"""modules/finance/instrument_recommender.py -- deterministic, no ML, no
LLM. Same numbers-in/numbers-out discipline as sip_emi_calc.py and
budget_optimize.py: same inputs always produce the same ranking."""
from modules.finance.instrument_recommender import recommend


def test_returns_all_recommendable_instruments_ranked_by_score():
    results = recommend("Moderate", horizon_years=5, tax_regime="new", emergency_fund_months=6)
    assert len(results) == 7  # the 7 concepts.json entries flagged is_recommendable_instrument
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_aggressive_long_horizon_favors_equity_instruments():
    results = recommend("Aggressive", horizon_years=20, tax_regime="old", emergency_fund_months=6)
    by_id = {r.instrument_id: r for r in results}
    assert by_id["direct_equity"].fit == "strong_fit"
    assert by_id["index_fund"].fit == "strong_fit"
    assert by_id["ppf"].score < by_id["direct_equity"].score


def test_conservative_short_horizon_favors_fd_over_equity():
    results = recommend("Conservative", horizon_years=1, tax_regime="new", emergency_fund_months=6)
    by_id = {r.instrument_id: r for r in results}
    assert by_id["fd"].fit == "strong_fit"
    assert by_id["direct_equity"].fit == "not_a_fit"
    assert by_id["fd"].score > by_id["direct_equity"].score


def test_short_horizon_flags_long_lock_in_instruments_against():
    results = recommend("Aggressive", horizon_years=1, tax_regime="old", emergency_fund_months=6)
    by_id = {r.instrument_id: r for r in results}
    assert any("horizon" in reason.lower() for reason in by_id["ppf"].reasons_against)


def test_no_emergency_fund_flags_illiquid_instruments_against():
    results = recommend("Aggressive", horizon_years=20, tax_regime="old", emergency_fund_months=0)
    by_id = {r.instrument_id: r for r in results}
    assert any("emergency fund" in reason.lower() for reason in by_id["elss"].reasons_against)
    # FD has no lock-in -- shouldn't be penalized for a missing emergency fund.
    assert not any("emergency fund" in reason.lower() for reason in by_id["fd"].reasons_against)


def test_old_regime_credits_80c_eligible_instruments():
    old = {r.instrument_id: r for r in recommend("Moderate", tax_regime="old", emergency_fund_months=6)}
    new = {r.instrument_id: r for r in recommend("Moderate", tax_regime="new", emergency_fund_months=6)}
    assert old["ppf"].score > new["ppf"].score
    assert any("80c" in reason.lower() for reason in old["ppf"].reasons_for)
    assert any("80c" in reason.lower() or "tax regime" in reason.lower() for reason in new["ppf"].reasons_against)


def test_no_horizon_given_skips_horizon_adjustment_entirely():
    results = recommend("Moderate", horizon_years=None, tax_regime="new", emergency_fund_months=6)
    for r in results:
        assert not any("horizon" in reason.lower() for reason in r.reasons_for + r.reasons_against)


def test_unknown_risk_label_falls_back_to_moderate_without_crashing():
    results = recommend("SomeUnknownLabel", horizon_years=5, tax_regime="new", emergency_fund_months=6)
    assert len(results) == 7


def test_scores_are_bounded_0_to_100():
    for risk in ("Conservative", "Moderate", "Aggressive"):
        for horizon in (None, 0, 1, 5, 20, 40):
            for regime in ("old", "new"):
                for emergency in (0, 3, 6, 12):
                    for r in recommend(risk, horizon, regime, emergency):
                        assert 0.0 <= r.score <= 100.0
