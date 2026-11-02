import time

import pytest

from core import orchestrator, session
from core.intent import graph
from modules.qa import trust


def test_data_lookup_that_finds_nothing_is_a_failed_part_not_a_general_answer(monkeypatch):
    monkeypatch.setattr(orchestrator, "_run_label", lambda label, *a: None)
    with pytest.raises(LookupError):
        orchestrator._run_part("data_lookup", "price of nosuchco", "s")


def test_failed_pipeline_in_the_architecture_layer_is_not_run_twice(monkeypatch):
    calls = []
    from core.intent import arch
    monkeypatch.setenv("ARIA_QUERY_ARCHITECTURE", "B")
    monkeypatch.setattr(arch, "decide_b", lambda q, deterministic_confident: arch.Decision(label="market", source="test"))

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("feed down")

    monkeypatch.setattr(orchestrator, "market_pipeline", boom)
    out = orchestrator._architecture_route("how is the market", "how is the market", "aw-s1")
    assert out and out["degraded"] and len(calls) == 1


def test_output_guard_is_skipped_for_a_while_after_a_timeout(monkeypatch):
    monkeypatch.setattr(orchestrator, "GUARD_TIMEOUT_S", 0.05)
    monkeypatch.setattr(orchestrator, "_guard_off_until", 0.0)
    n = []
    monkeypatch.setattr(orchestrator, "validate_output", lambda q, t: (n.append(1), time.sleep(0.3), {"available": True})[2])
    assert orchestrator._output_guard("q", "t") == {"available": False}
    assert orchestrator._output_guard("q", "t") == {"available": False} and len(n) == 1  # second call never reached the classifier


def test_merged_reply_keeps_evidence_per_part_and_only_one_card():
    two = graph.run_multi("q", [("a one two", "equity_research"), ("b one two", "market")],
                          lambda t, l: {"domain": l, "response": f"ok {t}", "report_id": f"r-{l}"})
    assert [p["report_id"] for p in two["parts"]] == ["r-equity_research", "r-market"] and "report_id" not in two
    one = graph.run_multi("q", [("a one two", "equity_research"), ("b one two", "market")],
                          lambda t, l: {"domain": l, "response": f"ok {t}", **({"report_id": "r1"} if l == "equity_research" else {})})
    assert one["report_id"] == "r1"


def test_idle_sessions_are_evicted_but_the_active_one_stays(monkeypatch):
    monkeypatch.setattr(session, "MAX_CACHED_SESSIONS", 3)
    for i in range(6):
        session._SESSIONS[f"evict-{i}"] = {}
    session._evict("evict-0")
    assert len([k for k in session._SESSIONS if k.startswith("evict-")]) <= 4 and "evict-0" in session._SESSIONS


def test_strict_grounding_flags_invented_prices_and_percentages():
    assert trust.ungrounded("The price is 2,050 rupees.", "price 1500")
    assert trust.ungrounded("ROE is 19 percent.", "roe 14")
    assert not trust.ungrounded("It rose in 2024 over 3 quarters.", "x")
