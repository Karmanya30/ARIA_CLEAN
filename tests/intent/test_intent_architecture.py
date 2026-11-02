"""Offline tests for core/intent: schema validation, the decision layer, the LangGraph workflow, and the default-off guarantee."""
import pytest

from core.intent import arch, graph, semantic, understanding
from core.intent.schema import QueryUnderstanding


def make_u(**over):
    base = dict(primary_intent="finance", secondary_intents=[], objective="x", standalone_query="can I afford a car worth 8 lakhs",
                entities=[], required_capabilities=[], sub_queries=[], context_references=[], missing_information=[], ambiguities=[],
                requires_clarification=False, clarification_question="", confidence=dict(intent=0.95, entity_extraction=0.9, context_resolution=0.9))
    base.update(over)
    return QueryUnderstanding.model_validate(base)


def test_default_architecture_is_adaptive_and_baseline_can_be_chosen(monkeypatch):
    monkeypatch.delenv("ARIA_QUERY_ARCHITECTURE", raising=False)
    assert arch.architecture() == "H"
    monkeypatch.setenv("ARIA_QUERY_ARCHITECTURE", "baseline")
    assert arch.architecture() == "A"
    from core import orchestrator
    assert orchestrator._architecture_route("anything at all", "anything at all", "s") is None


@pytest.mark.parametrize("flag,expected", [("semantic_router", "B"), ("langgraph", "C"), ("structured", "D"), ("hybrid", "E"), ("nonsense", "A")])
def test_flag_aliases(monkeypatch, flag, expected):
    monkeypatch.setenv("ARIA_QUERY_ARCHITECTURE", flag)
    assert arch.architecture() == expected


def test_schema_rejects_unknown_fields_and_labels():
    with pytest.raises(Exception):
        make_u(primary_intent="astrology")
    with pytest.raises(Exception):
        make_u(surprise="field")


def test_validation_rejects_changed_meaning():
    q = "can I afford a car worth 8 lakhs"
    understanding.validate(make_u(), q, [])
    with pytest.raises(ValueError, match="invented_number"):
        understanding.validate(make_u(standalone_query="can I afford a car worth 9 lakhs"), q, [])
    with pytest.raises(ValueError, match="dropped_negation"):
        understanding.validate(make_u(standalone_query="invest in stocks"), "do not invest in stocks", [])
    with pytest.raises(ValueError, match="clarification_without_question"):
        understanding.validate(make_u(requires_clarification=True), q, [])


def test_understand_falls_back_to_none_on_bad_model_output():
    assert understanding.understand("hello there", caller=lambda *a, **k: None)[0] is None
    assert understanding.understand("hello there", caller=lambda *a, **k: {"primary_intent": "finance"})[1]["status"] == "invalid"
    assert understanding.understand("hello there", caller=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))[0] is None


def fake_sr(label, score, margin):
    return semantic.SemanticChoice(label=label, score=score, margin=margin, ranking=[(label, score)], engine="fake")


def test_structured_decision_asks_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(semantic, "classify", lambda q: fake_sr("finance", 0.5, 0.2))
    d = arch.decide_structured("should I sell it", [], deterministic_label=None,
                               understand_fn=lambda q, h: (make_u(requires_clarification=True, clarification_question="Which holding do you mean?"), {}))
    assert d.clarify == "Which holding do you mean?" and d.label is None
    # two confident, different signals: do not run the wrong module
    monkeypatch.setattr(semantic, "classify", lambda q: fake_sr("market", 0.6, 0.2))
    d = arch.decide_structured("x", [], deterministic_label=None, understand_fn=lambda q, h: (make_u(), {}))
    assert d.clarify and d.trace["disagreement"]
    # agreement proceeds
    monkeypatch.setattr(semantic, "classify", lambda q: fake_sr("finance", 0.5, 0.2))
    d = arch.decide_structured("x", [], deterministic_label=None, understand_fn=lambda q, h: (make_u(), {}))
    assert d.label == "finance" and not d.clarify


def test_structured_decision_degrades_without_the_model(monkeypatch):
    monkeypatch.setattr(semantic, "classify", lambda q: fake_sr("market", 0.1, 0.01))
    d = arch.decide_structured("x", [], deterministic_label=None, understand_fn=lambda q, h: (None, {"status": "unavailable"}))
    assert d.label is None and d.clarify is None  # weak semantic signal and no model: baseline routing runs


def test_semantic_router_only_acts_on_what_the_rules_could_not_place(monkeypatch):
    monkeypatch.setattr(semantic, "classify", lambda q: fake_sr("tutor", 0.5, 0.2))
    assert arch.decide_b("x", deterministic_confident=True).label is None
    assert arch.decide_b("x", deterministic_confident=False).label == "tutor"
    monkeypatch.setattr(semantic, "classify", lambda q: fake_sr("tutor", 0.1, 0.2))
    assert arch.decide_b("x", deterministic_confident=False).label is None  # below the score threshold


def test_graph_runs_parts_in_parallel_verifies_each_and_never_drops_a_failure():
    def handler(text, label):
        if label == "market":
            raise RuntimeError("market feed down")
        return {"domain": label, "response": f"answer for {text}"}

    out = graph.run_multi("what is SIP and how is the market", [("what is SIP", "tutor"), ("how is the market", "market")], handler)
    assert out["multi_part"] and [p["ok"] for p in out["parts"]] == [True, False]
    assert "answer for what is SIP" in out["response"] and "couldn't complete this part" in out["response"]
    assert out["grounding"]["passed"] is False and out["grounding"]["unavailable"] == ["how is the market"]
    assert {n["node"] for n in out["intent_graph"]["nodes"]} == {"plan", "execute", "verify", "synthesise"}


def test_graph_all_parts_ok():
    out = graph.run_multi("q", [("a one two", "tutor"), ("b one two", "finance")], lambda t, l: {"domain": l, "response": f"ok {t}"})
    assert out["grounding"]["passed"] and out["domain"] == "tutor" and len(out["parts"]) == 2


def test_rule_split_needs_two_real_clauses_in_different_modules():
    label_of = lambda t: "tutor" if "what is" in t else "finance" if "afford" in t else None
    assert graph.split_by_rules("what is a SIP and how much SIP can I afford", label_of) == [("what is a SIP", "tutor"), ("how much SIP can I afford", "finance")]
    assert graph.split_by_rules("compare the old and new tax regime", label_of) == []  # one question that merely contains 'and'
    assert graph.split_by_rules("what is a SIP and what is a bond", label_of) == []  # same module twice: no split


def test_graph_parallel_mode_matches_sequential_mode():
    h = lambda t, l: {"domain": l, "response": f"ok {t}"}
    plan = [("a one two", "tutor"), ("b one two", "finance"), ("c one two", "market")]
    seq = graph.run_multi("q", plan, h)
    par = graph.run_multi("q", plan, h, parallel=True)
    assert seq["response"] == par["response"] and [p["label"] for p in seq["parts"]] == ["tutor", "finance", "market"]


def test_parts_that_need_the_session_do_not_deadlock():
    """Regression: parts used to run in worker threads and block on the conversation lock the waiting turn holds."""
    from core.session import get_session, session_lock

    def handler(text, label):
        get_session("__graph_lock_test")  # what every real pipeline does
        return {"domain": label, "response": "ok"}

    with session_lock("__graph_lock_test"):  # the turn holds this lock while the graph runs
        out = graph.run_multi("q", [("one two three", "tutor"), ("four five six", "finance")], handler)
    assert out["grounding"]["passed"]


def test_calibrated_thresholds_are_the_per_variant_defaults(monkeypatch):
    monkeypatch.delenv("ARIA_INTENT_SR_VETO", raising=False)
    for flag, expected in (("baseline", 0.45), ("semantic_router", 0.45), ("structured", 0.7), ("hybrid", 0.55)):
        monkeypatch.setenv("ARIA_QUERY_ARCHITECTURE", flag)
        assert arch.threshold("sr_veto") == expected
    monkeypatch.setenv("ARIA_INTENT_SR_VETO", "0.9")
    assert arch.threshold("sr_veto") == 0.9


def test_rule_label_keeps_personal_questions_in_finance_and_concepts_in_tutor():
    from core import orchestrator
    assert orchestrator._rule_label("what is a SIP") == "tutor"
    assert orchestrator._rule_label("what is my SIP amount worth") == "finance"
    assert orchestrator._rule_label("tell me a joke") is None


def test_graph_when_every_part_fails_numbers_are_not_reported_as_checked():
    def boom(text, label):
        raise RuntimeError("down")

    out = graph.run_multi("q", [("a one two", "tutor"), ("b one two", "market")], boom)
    assert out["grounding"]["numbers_checked"] is False and out["grounding"]["fallback"] is True
