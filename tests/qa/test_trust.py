"""modules/qa/trust.py: the number check, the redaction of unverifiable sentences, and the disclaimer / caveat rules."""
from modules.qa import trust


def test_rounding_scaling_and_calendar_numbers_are_allowed_invented_ones_are_not():
    src = "price 1166.7 change -0.31 market cap 15790000000000 as of 2026-10-12"
    assert trust.ungrounded("It trades at ₹1,166.7, down 0.31% on 2026-10-12.", src) == []
    assert trust.ungrounded("Market cap is about 15.79 trillion.", src) == []
    assert trust.ungrounded("The target is ₹1,500.", src) == [1500.0]
    assert trust.ungrounded("P/E is 15.8", "pe 15.91", lenient=True) == [] and trust.ungrounded("P/E is 15.8", "pe 15.91") == [15.8]


def test_unverifiable_sentences_are_dropped_labels_and_grounded_text_stay_and_the_reader_is_told():
    text = "Insight:\n- Infosys trades at a P/E of **15.91**. Analysts see 40 percent upside.\n\nAnalysis:\n- Sector average is 18.5."
    fixed, removed = trust._redact(text, "pe_ratio 15.91", True)
    assert removed == [40.0, 18.5]
    assert "15.91" in fixed and "40 percent" not in fixed and "18.5" not in fixed
    assert fixed.startswith("Insight:") and "Analysis:" in fixed
    assert "2 statement(s)" in fixed
    assert trust._redact("All good, 15.91.", "pe 15.91", True) == ("All good, 15.91.", [])


def test_a_raw_provider_error_is_a_failure_and_never_a_grounded_answer():
    assert trust.failed("Error: all backends down") and trust.failed("") and trust.failed(None) and not trust.failed("Fine.")
    g = trust.enforce({"domain": "market", "response": "Error: nope", "context": {"x": 1}})
    assert g["fallback"] and not g["passed"]


def test_disclaimer_and_accuracy_caveat_are_added_once_where_advice_is_possible():
    r = trust.finalize({"domain": "equity_research", "response": "The fair value estimate of the company is above the price today." + " x" * 20})
    assert r["response"].count(trust.DISCLAIMER_LINE) == 1 and trust.ACCURACY_CAVEAT in r["response"]
    again = trust.finalize(dict(r))
    assert again["response"].count(trust.DISCLAIMER_LINE) == 1 and again["response"].count(trust.ACCURACY_CAVEAT) == 1
    chat = trust.finalize({"domain": "smalltalk", "response": "Hello there, how can I help you today with your money?" * 2})
    assert trust.DISCLAIMER_LINE not in chat["response"] and chat["trust"]["disclaimer"] == trust.DISCLAIMER_LINE
    ask = trust.finalize({"domain": "finance", "response": "Which month does your rent start? " * 3, "missing_field": "rent"})
    assert trust.DISCLAIMER_LINE not in ask["response"]  # a clarifying question is not advice


def test_market_context_has_todays_move_so_every_channel_answers_is_nifty_up_today_the_same_way(monkeypatch):
    import pandas as pd

    from modules.market import analyzer

    class T:
        def __init__(self, sym):
            pass

        def history(self, period, interval):
            return pd.DataFrame({"Close": [22600.0, 22700.0, 22900.0, 22889.0, 22811.35]}, index=pd.date_range("2026-10-15", periods=5))

    monkeypatch.setattr(analyzer.yf, "Ticker", T)
    snap = analyzer.get_index_snapshot.__wrapped__("nifty") if hasattr(analyzer.get_index_snapshot, "__wrapped__") else analyzer.get_index_snapshot("nifty")
    assert snap["five_day_trend"] == "up" and snap["today_trend"] == "down"  # up over five days, down today
    assert snap["previous_close"] == 22889.0 and snap["today_change_pct"] == -0.34 and snap["as_of"] == "2026-10-19"


def test_index_names_with_numbers_are_not_figures():
    assert trust.ungrounded("The Nifty 50 and Sensex 30 fell.", "level 22811.35", True) == []
