"""Query understanding (shared/understand.py): typos, text-speak and Hinglish must route like the clean query. Every module
pipeline is a recording stub, so a row says WHICH module a query reaches; no model, network or microphone is used.
scripts/understand_report.py prints the same table as accuracy per intent."""
import statistics
import time
from unittest import mock

import pytest

from core import orchestrator
from core.session import clear_session, get_session
from modules.finance.pipeline import finance_intent
from shared.understand import goal, normalize, spelled, suggest

# (query, expected "domain" or "finance:<intent>")
ROWS = [
    # the 16 measured live failures
    ("wat is compund intrest", "tutor"),
    ("shud i sel my mutal funds, they r doing bad", "finance:decision"),
    ("can i bye a car worth 10 lakhs", "finance:afford"),
    ("how much did i spnd on fod last mnth", "finance:spending"),
    ("whats the stok price of tcs", "equity_research"),
    ("analyse my spneding", "finance:spending"),
    ("hw is nifty doin tdy", "market"),
    ("plz explan sip", "tutor"),
    ("i earn 1.2 lakh pr mnth and my rnt is 25k", "finance"),
    ("can i strat a sip of 15k", "finance:afford_sip"),
    ("wat is my finacial helth scor", "finance:health"),
    ("compny inteligence scor for infosis", "company_intelligence"),
    ("equty reserch report on relience", "equity_research"),
    ("tax regeme old vs new for me", "finance:tax"),
    ("mera sip band kr du kya, bahut loss ho rha hai", "finance:decision"),
    ("hello", "smalltalk"),
    # the same questions spelled correctly
    ("what is compound interest", "tutor"),
    ("should i sell my mutual funds, they are doing bad", "finance:decision"),
    ("can i buy a car worth 10 lakhs", "finance:afford"),
    ("how much did i spend on food last month", "finance:spending"),
    ("what is the stock price of tcs", "equity_research"),
    ("analyse my spending", "finance:spending"),
    ("how is nifty doing today", "market"),
    ("please explain sip", "tutor"),
    ("can i start a sip of 15k", "finance:afford_sip"),
    ("what is my financial health score", "finance:health"),
    ("company intelligence score for infosys", "company_intelligence"),
    ("equity research report on reliance", "equity_research"),
    ("tax regime old vs new for me", "finance:tax"),
    # Hinglish
    ("maine kitna kharch kiya food pe", "finance:spending"),
    ("kitna kharch hua food pe mera", "finance:spending"),
    ("mf bech du kya", "finance:decision"),
    ("mera sip band kar du kya", "finance:decision"),
    ("shares bech du kya", "finance:decision"),
    ("meri bachat kitni hai", "finance"),
    # more typos, text-speak and mixed
    ("shld i exit my stocks", "finance:decision"),
    ("should i stop my sip", "finance:decision"),
    ("can i afford a hom loan of 50 lakhs", "finance:afford"),
    ("what if i reduce my rnt by 5000", "finance:what_if"),
    ("how much did i spend on grocries", "finance:spending"),
    ("show my biggest expences", "finance:spending"),
    ("hw much did i spnd last mnth", "finance:spending"),
    ("can i retier at 50", "finance:retirement"),
    ("i earn 80k and my rent is 20k", "finance"),
    ("whats the sensex doing today", "market"),
    ("rbi repo rate and inflation", "market"),
    ("what is an expense ratio", "tutor"),
    ("quiz me on compound interest", "tutor"),
    ("qiuz me on compound interest", "tutor"),
    ("plz tell the stok price of infosys", "equity_research"),
    ("infosis equty research report", "equity_research"),
    ("valuation of relience", "equity_research"),
    ("sentimnt on tcs", "company_intelligence"),
    ("red flags in wipro", "company_intelligence"),
    ("wat r the red flags in wipro", "company_intelligence"),
    ("how much sip can i afford", "finance:sip_capacity"),
    ("wat is the diffrence between sip and lumpsum", "tutor"),
    ("whats nifty today", "market"),
    ("how much sip can i afford", "finance:sip_capacity"),
    ("wat is the diffrence between sip and lumpsum", "tutor"),
    ("whats nifty today", "market"),
    ("whats the pe ratio of L&T and HDFC Bank", "equity_research"),
    ("what is pe ratio", "tutor"),
    ("kya mujhe apna sip rok dena chahiye", "finance:decision"),
    ("whats teh differnce betwen sip and lumpsum", "tutor"),
    ("how r u", "smalltalk"),
    ("thx", "smalltalk"),
    # clarify and general stay model-free / unchanged
    ("how healthy r ur finances", "clarify"),
    ("who won the cricket match yesterday", "general"),
    ("write me a python program", "general"),
]
UNCHANGED = ["TCS", "INFY", "L&T", "50k", "1.2L", "₹10,000", "SIP", "EMI", "FOIR", "NAV", "ELSS", "a@b.com", "Reliance", "U.S. market",
             "tell me about tata motors", "can i invest 50 k", "10 L in an ELSS fund", "hello aria"]


def route_label(query: str, correct: bool = True) -> tuple[str, dict]:
    """Run handle_query with every module pipeline replaced by a stub; the label is the module reached."""
    def stub(name):
        return lambda *a, **k: {"domain": name, "response": "stub"}

    sid = "__understand_route__"
    clear_session(sid)
    get_session(sid)["adapt_tone"] = False
    with mock.patch.multiple(orchestrator, company_intelligence=stub("company_intelligence"), equity_research_pipeline=stub("equity_research"),
                             market_pipeline=stub("market"), finance_pipeline=stub("finance"), tutor_pipeline=stub("tutor"),
                             classify_domain=lambda q: {"available": False}, validate_output=lambda *a: {"available": False},
                             _smalltalk_reply=lambda q: {"domain": "smalltalk", "query": q, "response": "hi"}):
        response = orchestrator.handle_query(query, session_id=sid, correct=correct)
    clear_session(sid)
    label = response["domain"]
    if label == "finance" and (hit := finance_intent(normalize(query)[0] if correct else query)):
        label += ":" + hit[0]
    return label, response


@pytest.mark.parametrize("query,expected", ROWS)
def test_routes_like_the_clean_query(query, expected):
    assert route_label(query)[0] == expected


@pytest.mark.parametrize("text", UNCHANGED)
def test_names_amounts_and_acronyms_are_never_rewritten(text):
    assert normalize(text) == (text, [])


def test_mera_sip_routes_as_before():
    assert route_label("mera sip")[0] == route_label("mera sip", correct=False)[0] == "finance"


def test_normalize_is_idempotent_and_keeps_numbers():
    for query, _ in ROWS:
        once = normalize(query)[0]
        assert normalize(once)[0] == once
        assert [c for c in query if c.isdigit()] == [c for c in once if c.isdigit()]


def test_latency_p95_under_20ms_after_warm_up():
    normalize("warm up")
    times = []
    for query, _ in ROWS * 3:
        t = time.perf_counter()
        normalize(query)
        times.append(time.perf_counter() - t)
    assert statistics.quantiles(times, n=20)[-1] < 0.020


def test_display_keeps_the_original_and_response_carries_corrected_query():
    query = "wat is compund intrest"
    label, response = route_label(query)
    assert (label, response["query"], response["corrected_query"]) == ("tutor", query, "what is compound interest")


def test_text_speak_alone_is_not_announced_as_a_correction():
    _, response = route_label("how r u")
    assert "corrected_query" not in response and not spelled([("r", "are")])


def test_correct_false_routes_the_text_as_typed():
    label, response = route_label("wat is compund intrest", correct=False)
    assert label != "tutor" and "corrected_query" not in response


def test_clarify_suggests_without_a_model_call(mock_llm):
    response = orchestrator.handle_query("how healthy r ur finances", session_id="__understand_clarify__")
    assert response["domain"] == "clarify" and "how healthy are my finances" in response["suggestions"]
    assert mock_llm.calls == []
    clear_session("__understand_clarify__")


def test_history_stores_the_original_text():
    sid = "__understand_history__"
    clear_session(sid)
    route_label_session = orchestrator.get_session(sid)
    route_label_session["adapt_tone"] = False
    with mock.patch.object(orchestrator, "tutor_pipeline", lambda *a, **k: {"domain": "tutor", "response": "x"}):
        orchestrator.handle_query("wat is compund intrest", session_id=sid)
    assert orchestrator.get_session(sid)["history"][-1]["query"] == "wat is compund intrest"
    clear_session(sid)


def test_goal_and_suggest():
    assert goal("should i sell my funds", finance_intent("should i sell my funds")) == "decide"
    assert goal("can i buy a car worth 10 lakhs", finance_intent("can i buy a car worth 10 lakhs")) == "afford"
    assert goal("analyse my spending", finance_intent("analyse my spending")) == "track"
    assert goal("what is sip") == "learn" and goal("sip vs ppf") == "compare" and goal("do it right now") == "urgent"
    assert goal("hmm", None, "venting") == "vent" and goal("hmm") == "ask"
    assert suggest("what is the capital of france") == [] and suggest("analyse my spendin")


@pytest.mark.parametrize("query,fixed", [
    ("whats teh differnce betwen sip and lumpsum", "whats the difference between sip and lumpsum"),
    ("expln mutalfund", "explain mutual fund"),
    ("mutualfund", "mutual fund"),
    ("zxqv blorp wibble", "zxqv blorp wibble"),
    ("kya mujhe apna sip rok dena chahiye", "kya me apna sip stop dena chahiye"),
    ("lumpsum vs sip for 10 L", "lumpsum vs sip for 10 L"),
])
def test_exact_corrections(query, fixed):
    assert normalize(query)[0] == fixed


def test_corrected_query_only_for_english_spelling_fixes():
    assert "corrected_query" not in route_label("kya mujhe apna sip rok dena chahiye")[1]
    assert "corrected_query" not in route_label("mera sip band kr du kya, bahut loss ho rha hai")[1]
    assert "corrected_query" not in route_label("zxqv blorp wibble")[1]
    assert route_label("whats teh differnce betwen sip and lumpsum")[1]["corrected_query"] == "whats the difference between sip and lumpsum"
    assert not spelled(normalize("kya mujhe apna sip rok dena chahiye")[1])
    assert "corrected_query" not in route_label("how healthy r ur finances")[1]  # clarify
