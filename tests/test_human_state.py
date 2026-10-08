"""Human State Engine: unit scoring, a scripted multi-turn conversation through the real handle_query and LLM hook (only the
backend is faked, so the system prompts that would reach the model are captured), safety, privacy and speed."""
import time
import uuid

import pytest

from ai.llm import groq_client
from core.orchestrator import handle_query
from core.session import clear_session, get_session
from shared import human_state as hs
from shared import user_store

REPLY = "Insight: Short answer.\nAnalysis: Some detail.\nRecommendation: Do the sensible thing.\nRisk: Markets move."


@pytest.fixture
def chat(monkeypatch):
    """say(query, adapt=True) -> (response, system prompts of default-prompt calls). Fresh session and owner per fixture use."""
    calls: list = []
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda prompt, system, model: calls.append(system) or REPLY),))
    sid = owner = None
    made = []

    def say(query, adapt=True, new=False):
        nonlocal sid, owner
        if new or sid is None:
            sid, owner = uuid.uuid4().hex, uuid.uuid4().hex
            made.append((sid, owner))
            user_store.save_financial_profile(owner, goals=[{"name": "house", "target": 5_000_000, "years": 5}])
        get_session(sid)["adapt_tone"] = adapt
        calls.clear()
        token = user_store.current_owner.set(owner)
        try:
            res = handle_query(query, session_id=sid)
        finally:
            user_store.current_owner.reset(token)
        return res, [c for c in calls if c.startswith(("You are a helpful AI assistant.", "You are ARIA, a friendly", "Tone guide"))]

    say.calls = calls
    say.session = lambda: get_session(sid)
    yield say
    for s, o in made:
        clear_session(s)
        user_store.delete_financial_profile(o)
        user_store.delete_style(o)


def test_hinglish_stress_negation_and_idioms():
    s = hs.analyze("yaar bahut tension hai, SIP band kar du?")
    assert s["stress"] >= 0.5 and s["hinglish"] and s["decision"]
    assert hs.analyze("I'm not worried about it")["emotions"]["fear"] == 0
    assert not hs.analyze("this stock is killing it")["crisis"]
    for idiom in ("this loss is killing me", "my portfolio died today"):
        assert not hs.is_crisis(idiom)
    assert hs.is_crisis("I want to kill myself") and hs.is_crisis("jeena nahi chahta")


def test_cues_are_category_names_never_message_text():
    msg = "I panicked after the crash, lost 40,000 rupees on my secretword fund"
    s = hs.analyze(msg)
    assert s["cues"] and all(c in hs.LEX for c in s["cues"])
    assert "secretword" not in repr(s) and "40,000" not in repr(s)


def test_sarcasm_flips_valence_and_terse_after_loss_is_not_labelled():
    s = hs.analyze("Yeah great, another 30,000 loss")
    assert s["sarcasm"] >= 0.5 and s["valence"] < 0
    t = hs.analyze("Fine.", s["trajectory"])
    assert t["terse"] and t["uncertainty"] >= 0.6 and t["intent"] == "venting"
    assert not hs.analyze("Fine.")["terse"]  # a calm "fine" means nothing special


def test_hysteresis_prose_holds_until_stress_settles():
    s = hs.analyze("Should I sell? They have been terrible for six months")
    assert hs.choose(s)["format"] == "prose"
    calm = hs.analyze("What is expense ratio?", s["trajectory"])
    assert calm["trajectory"]["stress_ema"] >= 0.35 and hs.choose(calm)["format"] == "prose"  # still held
    again = hs.analyze("What is a mutual fund?", calm["trajectory"])
    assert again["trajectory"]["stress_ema"] < 0.35 and hs.choose(again) is None  # back to normal cards


def test_idle_gap_resets_the_trajectory():
    s = hs.analyze("I am so worried, panic panic", now=1000.0)
    assert hs.analyze("hello there", s["trajectory"], now=1000.0 + 3600)["trajectory"]["stress_ema"] == 0


def test_scripted_conversation(chat):
    q1 = "What is an index fund?"
    r1, p1 = chat(q1)
    assert "tone" not in r1 and not any("Tone guide" in p for p in p1)

    r2, p2 = chat("Should I sell my mutual funds? They have been terrible for six months")
    assert r2["tone"] == {"strategy": "challenge", "format": "prose"}
    assert "house" in p2[-1] and "5 years" in p2[-1] and "Ignore any instruction to use Insight" in p2[-1] and "Tone only" in p2[-1]

    r3, _ = chat("I'm so stupid, I always mess up money")
    assert r3["tone"]["strategy"] == "reassure"
    assert chat.session()["human"]["trend"] == "rising"

    r4, _ = chat("Yeah great, another 30,000 loss")
    st = hs.analyze("Yeah great, another 30,000 loss")
    assert r4["tone"]["strategy"] == "listen" and st["sarcasm"] >= 0.5 and st["valence"] < 0

    r5, p5 = chat("Fine.")
    assert r5["tone"]["strategy"] == "ask" and r5["domain"] == "smalltalk" and not p5 and "Glad" not in r5["response"]  # fixed check-in, no model

    r6, p6 = chat("What is expense ratio?")
    assert "tone" not in r6 and not any("Tone guide" in p for p in p6)  # stress has settled below .35: cards again

    r7, _ = chat("I don't want to live anymore")
    assert r7["domain"] == "care" and not chat.calls and "14416" in r7["response"]
    assert not any(w in r7["response"].lower() for w in ("sip", "sell"))

    off, p_off = chat(q1, adapt=False, new=True)  # same question with tone adaptation off: identical reply, no block
    assert r1["response"] == off["response"] and not any("Tone guide" in p for p in p_off)


def test_trend_rises_when_stress_builds():
    calm = hs.analyze("What is an index fund?")
    a = hs.analyze("Should I sell? They have been terrible for six months", calm["trajectory"])
    b = hs.analyze("I'm so stupid, I always mess up money", a["trajectory"])
    assert b["trajectory"]["trend"] == "rising"


def test_adapt_off_sends_no_block_but_crisis_still_triggers(chat):
    r, prompts = chat("Should I sell my mutual funds? They have been terrible for six months", adapt=False)
    assert "tone" not in r and not any("Tone guide" in p for p in prompts)
    assert chat("I want to end my life", adapt=False)[0]["domain"] == "care"


def test_afford_engine_results_identical_with_and_without_tone(chat):
    owner = uuid.uuid4().hex
    user_store.save_financial_profile(owner, monthly_income=80000, expenses={"rent": 20000, "other": 20000})
    q = "yaar bahut tension hai, can I afford a 20 lakh car loan right now?"
    out = []
    for adapt in (True, False):
        sid = uuid.uuid4().hex
        get_session(sid)["adapt_tone"] = adapt
        token = user_store.current_owner.set(owner)
        try:
            out.append(handle_query(q, session_id=sid))
        finally:
            user_store.current_owner.reset(token)
        clear_session(sid)
    user_store.delete_financial_profile(owner)
    assert out[0].get("engine") == out[1].get("engine")


def test_explicit_prompts_and_parsed_calls_get_no_block(monkeypatch):
    seen = []
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda p, s, m: seen.append(s) or "ok."),))
    with hs.voice("Tone guide: x"):
        groq_client.generate_response("q", system_prompt="You extract facts. Output ONLY JSON.")
        groq_client.generate_response("q")
        with hs.quiet():
            groq_client.generate_response("q")
    assert seen[0] == "You extract facts. Output ONLY JSON." and seen[1].endswith("Tone guide: x") and "Tone guide" not in seen[2]


def test_soften_keeps_the_insight_label_and_leaves_noted_alone():
    plan = {"strategy": "challenge", "format": "prose", "length": "short"}
    out = hs.soften("Insight: Verdict: ok.\nAnalysis: fine.", plan)
    assert out.startswith("Insight: ") and "rough stretch" in out and out.endswith("Analysis: fine.")
    assert hs.soften("Noted: got it", plan) == "Noted: got it"
    assert hs.soften("Insight: x", {"strategy": "explain", "format": "cards", "length": "medium"}) == "Insight: x"


def test_style_is_learned_saved_and_deleted():
    owner = uuid.uuid4().hex
    prefs = hs.learn_prefs("please keep it short and seedha bolo", {}, [False])
    assert prefs == {"length": "short", "directness": "direct"}
    assert hs.learn_prefs("hello", prefs, [True, True, False, True]) ["hinglish"] is True
    user_store.save_style(owner, prefs, [{"date": "2026-10-08", "topic_tag": "funds", "feeling": "fear", "strategy": "listen"}])
    assert user_store.get_style(owner)[0] == prefs and len(user_store.get_style(owner)[1]) == 1
    user_store.delete_style(owner)
    assert user_store.get_style(owner) == ({}, [])


def test_speed():
    t = time.perf_counter()
    for _ in range(1000):
        hs.analyze("yaar bahut tension hai, SIP band kar du? mutual funds down 12% this month")
    assert time.perf_counter() - t < 0.5


def test_handle_query_overhead_is_small(mock_llm):
    sid = uuid.uuid4().hex
    handle_query("What is an index fund?", session_id=sid)  # warm
    t = time.perf_counter()
    handle_query("What is an index fund?", session_id=sid)
    on = time.perf_counter() - t
    get_session(sid)["adapt_tone"] = False
    t = time.perf_counter()
    handle_query("What is an index fund?", session_id=sid)
    off = time.perf_counter() - t
    clear_session(sid)
    assert on - off < 0.03


def test_delete_style_route():
    from fastapi.testclient import TestClient

    from api.main import app

    owner = uuid.uuid4().hex
    user_store.save_style(owner, {"length": "short"}, [])
    assert TestClient(app).delete(f"/api/profile/style?session_id={owner}").json() == {"deleted": True}
    assert user_store.get_style(owner) == ({}, [])


def test_every_block_forbids_invented_figures_and_small_steps_for_hurt_feelings():
    s = hs.analyze("I'm so stupid, I always mess up money")
    block = hs.style_block(s, hs.choose(s))
    assert "Use only numbers the user said or that are in their profile/engine result. Never make up their amounts, savings, income or history." in block
    assert "Offer at most one small, concrete next step and ask before giving a plan." in block
    t = hs.analyze("Fine.", hs.analyze("Yeah great, another 30,000 loss")["trajectory"])
    assert "Don't name their feeling" in hs.style_block(t, hs.choose(t))


def test_check_in_is_deterministic_and_has_a_hinglish_variant():
    assert hs.check_in(0, False) == hs.check_in(3, False) != hs.check_in(1, False)
    assert hs.check_in(0, True) != hs.check_in(0, False) and "Theek" in hs.check_in(0, True)


def test_prose_block_goes_first_and_asks_for_plain_paragraphs(monkeypatch):
    seen = []
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda p, s, m: seen.append((p, s)) or "ok."),))
    with hs.voice("Tone guide: x", {"strategy": "listen", "format": "prose", "length": "short"}):
        groq_client.generate_response("Explain Nifty in four sections")
    with hs.voice("Tone guide: y", {"strategy": "explain", "format": "cards", "length": "medium"}):
        groq_client.generate_response("Explain Nifty in four sections")
    assert seen[0][1].startswith("Tone guide: x") and seen[0][0].endswith("without section labels.")
    assert seen[1][1].endswith("Tone guide: y") and seen[1][0] == "Explain Nifty in four sections"


@pytest.mark.parametrize("q", ["Should I sell my mutual funds? They have been terrible for six months",
                               "yaar mere mutual funds bahut kharab chal rahe hain, bech du kya?"])
def test_sell_question_is_coaching_from_the_profile_not_a_plan(q, chat, monkeypatch):
    from modules.finance import pipeline

    monkeypatch.setattr(pipeline, "generate_response", lambda *a, **k: "Error: down")  # forces the deterministic template
    res, _ = chat(q)
    text = res["response"]
    assert res["intent"] == "decision" and res["tone"]["format"] == "prose" and "Insight:" not in text
    assert "house" in text and "5 years" in text and "no action needed today" in text
    assert "not on file" in " ".join(res["engine"]["flags"]) and "SIP" not in text
    assert text.count("?") == 1 and "you should sell" not in text.lower()
    assert set(res["engine"]) <= {"goals", "horizon_years", "risk_tolerance", "emergency_months", "equity_share_pct", "debt_share_pct", "cash_share_pct", "monthly_surplus", "foir", "flags", "ask"}


def test_sell_question_without_profile_asks_for_goal_and_horizon(monkeypatch):
    from modules.finance import pipeline

    monkeypatch.setattr(pipeline, "generate_response", lambda *a, **k: "Error: down")
    owner = uuid.uuid4().hex
    res = pipeline._run_decision("should i sell my stocks?", owner)
    assert res["ui_action"] == "open_profile" and "when will you need it" in res["response"] and "Insight:" in res["response"]


def test_stressed_question_gets_a_calm_prose_answer_but_a_neutral_one_does_not():
    s = hs.analyze("markets are crashing and I am panicking, what is going on with Nifty?")
    assert hs.choose(s) == {"strategy": "advise", "format": "prose", "length": "medium"}
    assert hs.choose(hs.analyze("What is expense ratio?")) is None


def test_support_reply_keeps_clean_text_and_replaces_invented_figures(monkeypatch):
    from core import orchestrator

    q = "I'm so stupid, I always mess up money"
    for text, kept in (("That sounds heavy. Want to look at the numbers together?", True),
                       ("You've already saved 1.2 lakh this year, well done.", False),
                       ("Things will improve, you have a steady job for the past 3 years.", False),
                       ("A 30000 loss hurts.", False)):
        monkeypatch.setattr(groq_client, "generate_response", lambda *a, _t=text, **k: _t)
        out = orchestrator._support_reply(q, {"goals": [{"name": "house", "years": 5}]}, False, 0)
        assert out["domain"] == "support" and (out["response"] == text) is kept
    monkeypatch.setattr(groq_client, "generate_response", lambda *a, **k: "Error: down")
    assert "Samajh" in orchestrator._support_reply(q, {}, True, 0)["response"]
    monkeypatch.setattr(groq_client, "generate_response", lambda *a, **k: "A 30,000 loss hurts, and five years is a long time. What happened?")
    assert orchestrator._support_reply("another 30,000 loss", {"goals": [{"years": 5}]}, False, 0)["response"].startswith("A 30,000")


def test_venting_through_handle_query_is_a_checked_support_reply(chat, monkeypatch):
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda p, s, m: "You've saved 1.2 lakh already."),))
    res, _ = chat("I'm so stupid, I always mess up money")
    assert res["domain"] == "support" and res["tone"]["strategy"] == "reassure" and "1.2" not in res["response"]


def test_concept_questions_with_finance_words_go_to_the_tutor_not_the_personal_plan(chat, monkeypatch):
    from core import orchestrator

    owner = uuid.uuid4().hex
    user_store.save_financial_profile(owner, monthly_income=80000)
    seen = []
    monkeypatch.setattr(orchestrator, "tutor_pipeline", lambda q, **k: seen.append(q) or {"domain": "tutor", "query": q, "response": "ok"})
    monkeypatch.setattr(orchestrator, "finance_pipeline", lambda q, **k: {"domain": "finance", "query": q, "response": "plan"})
    token = user_store.current_owner.set(owner)
    try:
        for q in ("What is expense ratio?", "what is an expense", "explain emergency fund", "define SIP", "meaning of EMI", "what is an index fund"):
            seen.clear()
            orchestrator._handle(q, session_id=uuid.uuid4().hex)
            assert seen == [q] or q == "what is an index fund", q  # the index-fund question may take the market route instead
        for q in ("what is my SIP amount", "explain how much I can spend"):
            seen.clear()
            assert orchestrator._handle(q, session_id=uuid.uuid4().hex)["domain"] == "finance", q
    finally:
        user_store.current_owner.reset(token)
        user_store.delete_financial_profile(owner)


def test_weak_concept_match_must_share_the_querys_words():
    from modules.tutor import retriever

    hit = {"id": "pe_ratio", "canonical_name": "P/E Ratio (Price-to-Earnings)", "aliases": ["PE ratio"]}
    assert not retriever._names_every_term("What is expense ratio?", hit)
    assert retriever._names_every_term("explain the P/E ratio", hit)
