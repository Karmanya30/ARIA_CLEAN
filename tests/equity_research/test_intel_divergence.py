"""The intelligence score and its divergence rules, on hand-built fundamentals."""
from types import SimpleNamespace as NS

from modules.equity_research.intelligence import lenses

NAMES = ["Quality", "Valuation lenses", "Growth", "Financial safety", "Technical", "Sentiment"]
VAL = NS(synthesis=NS(upside=0.0), withheld_by_audit=False)


def fund(ratings="mixed", news=None, call=None, cash=1.0, piotroski="middling", gc=None):
    r = dict(zip(NAMES, ratings)) if isinstance(ratings, (list, tuple)) else {n: ratings for n in NAMES}
    return {"scorecard": {"pillars": [{"name": n, "rating": x} for n, x in r.items()]},  "news_signals": {"net": news},
            "concall": {"available": call is not None, "net": call}, "quality": {"cash_conversion": cash},
            "piotroski": {"verdict": piotroski}, "growth_check": gc or {}}


def ids(f, val=VAL):
    return {d["id"] for d in lenses.intelligence(f, val)["divergences"]}


def test_score_bands_and_renormalisation():
    r = lenses.intelligence(fund("strong"), NS(synthesis=NS(upside=0.3), withheld_by_audit=False))
    assert r["score"] == 100 and r["band"] == "strong" and r["coverage"] == 1.0 and not r["low_evidence"]  # with no tone sources the Sentiment pillar stands in for Tone
    assert lenses.intelligence(fund("weak"), NS(synthesis=NS(upside=-0.3), withheld_by_audit=False))["score"] == 0
    assert lenses.intelligence(fund("mixed"), VAL)["band"] == "mixed"
    ratings = ["strong", "n/a", "n/a", "n/a", "n/a", "n/a"]  # only Quality (25) and the upside (15) can be scored
    r = lenses.intelligence(fund(ratings), NS(synthesis=NS(upside=0.0), withheld_by_audit=False))
    assert r["score"] == round(100 * (25 * 1 + 15 * 0.5) / 40) and r["coverage"] == 0.4 and r["low_evidence"]


def test_withheld_valuation_drops_the_upside_component():
    r = lenses.intelligence(fund("strong"), NS(synthesis=NS(upside=0.3), withheld_by_audit=True))
    assert next(c for c in r["components"] if c["name"] == "Valuation upside")["value"] is None
    assert lenses.intelligence(fund("strong"), NS(synthesis=None, withheld_by_audit=False))["coverage"] < 0.9


def test_tone_blends_news_and_call():
    r = lenses.intelligence(fund(news=0.5, call=-0.5), VAL)
    assert next(c for c in r["components"] if c["name"] == "Tone")["value"] == 0.5


def test_each_divergence_rule_fires_and_stays_quiet():
    assert "tone_vs_cash" in ids(fund(news=0.5, cash=0.4)) and "tone_vs_cash" not in ids(fund(news=0.5, cash=0.9)) and "tone_vs_cash" not in ids(fund(news=0.1, cash=0.4))
    weak_q = ["weak"] + ["mixed"] * 5
    assert "tone_vs_quality" in ids(fund(weak_q, call=0.5)) and "tone_vs_quality" in ids(fund(news=0.5, piotroski="weak")) and "tone_vs_quality" not in ids(fund(news=0.5))
    d = lenses.intelligence(fund(news=-0.5, call=0.5), VAL)["divergences"]
    assert [x["text"] for x in d if x["id"] == "call_vs_news"] == ["Management upbeat, press negative"]
    assert "call_vs_news" not in ids(fund(news=0.5, call=0.5)) and "call_vs_news" not in ids(fund(news=-0.1, call=0.1))
    gc = {"model": 0.15, "fundamental": 0.08}
    assert "guidance_unfunded" in ids(fund(call=0.5, gc=gc)) and "guidance_unfunded" not in ids(fund(call=0.5, gc={"model": 0.10, "fundamental": 0.08})) and "guidance_unfunded" not in ids(fund(gc=gc))
    two_weak = ["weak", "mixed", "weak", "mixed", "mixed", "mixed"]
    not_business = ["mixed", "weak", "mixed", "mixed", "weak", "mixed"]  # cheap-looking and weak price action alone is not a value trap
    assert "value_trap" in ids(fund(two_weak), NS(synthesis=NS(upside=0.2), withheld_by_audit=False)) and "value_trap" not in ids(fund(two_weak)) and "value_trap" not in ids(fund(not_business), NS(synthesis=NS(upside=0.2), withheld_by_audit=False))
    assert "price_vs_fundamentals" in ids(fund(["strong", "mixed", "mixed", "mixed", "weak", "mixed"])) and "price_vs_fundamentals" in ids(fund(["weak", "mixed", "mixed", "mixed", "strong", "mixed"]))
    assert "price_vs_fundamentals" not in ids(fund("mixed"))
    assert "contrarian" in ids(fund(["strong", "mixed", "mixed", "strong", "mixed", "mixed"], news=-0.5)) and "contrarian" not in ids(fund(["strong", "mixed", "mixed", "mixed", "mixed", "mixed"], news=-0.5))


def test_report_carries_the_intelligence_score():
    from test_intel_report_html import report_for

    it = report_for()["fundamentals"]["intelligence"]
    assert 0 <= it["score"] <= 100 and it["band"] in ("strong", "mixed", "weak") and it["components"]


def test_company_intelligence_returns_the_ui_contract(monkeypatch):
    from _intel_fixtures import make_snapshot

    from modules.equity_research.intelligence import pipeline
    from modules.equity_research.intelligence.data import Target

    monkeypatch.setattr(pipeline, "gather", lambda t: make_snapshot("operating"))
    r = pipeline.company_intelligence("x", target=Target("INTELT", "INTELT.NS", "IntelT"))
    assert r["domain"] == "company_intelligence" and r["company"]["symbol"] == "INTELT.NS" and 0 <= r["intelligence"]["score"] <= 100
    assert r["scorecard"]["pillars"] and len(r["news"]) <= 5 and set(r["call"]) == {"available", "period", "net", "themes"} and "/100" in r["response"]
    monkeypatch.setattr(pipeline, "resolve_target", lambda q: None)
    assert pipeline.company_intelligence("nothing") is None
