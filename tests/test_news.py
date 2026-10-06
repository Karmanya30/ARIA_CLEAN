"""shared/news.py with canned feeds: no network. Covers parsing, noise, relevance, de-duplication/corroboration, age,
the Google source suffix, and that one dead feed never breaks the rest."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from shared import news


def _rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>https://x/{i}</link><pubDate>{format_datetime(when)}</pubDate>{extra}</item>"
        for i, (t, when, extra) in enumerate(items)
    )
    return f"<rss><channel>{body}</channel></rss>".encode()


NOW = datetime.now(timezone.utc)
ago = lambda h: NOW - timedelta(hours=h)


@pytest.fixture
def feeds(monkeypatch):
    """Install fake feeds: {name: xml bytes | Exception}. Returns the dict to fill in."""
    table: dict = {}
    monkeypatch.setattr(news, "FEEDS", [("india", "markets", n, f"http://feed/{n}") for n in table] or [])
    monkeypatch.setattr(news, "_cache", {})
    monkeypatch.setattr(news.settings, "FI_NEWS_RSS", True)

    def install(**kw):
        table.update(kw)
        monkeypatch.setattr(news, "FEEDS", [("india", "markets", n, f"http://feed/{n}") for n in table])

        class R:
            def __init__(s, c): s.content = c
            def raise_for_status(s): pass

        def fake_get(url, **_):
            v = table[url.rsplit("/", 1)[1]]
            if isinstance(v, Exception):
                raise v
            return R(v)

        monkeypatch.setattr(news.requests, "get", fake_get)
    return install


def test_parse_rss_atom_and_google_source_suffix():
    rss = _rss(("Nifty ends higher - Reuters", ago(1), "<source>Reuters</source>"))
    [item] = news.parse_feed(rss, "Google News")
    assert item["title"] == "Nifty ends higher" and item["source"] == "Reuters"
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom story</title>
        <link href="http://a/1"/><updated>2026-10-06T08:00:00Z</updated></entry></feed>"""
    [a] = news.parse_feed(atom, "Atom Paper")
    assert a["url"] == "http://a/1" and a["source"] == "Atom Paper" and a["published"].year == 2026


def test_filler_and_regulator_notices_are_dropped():
    xml = _rss(("Gold Rate Today in Vijayawada 6th October", ago(1), ""), ("Kotak Bank Share Price Live Updates", ago(1), ""),
               ("Directions under Section 35A of the Banking Regulation Act", ago(1), ""), ("Sensex jumps 500 points", ago(1), ""))
    assert [i["title"] for i in news.parse_feed(xml, "x")] == ["Sensex jumps 500 points"]


def test_specific_question_returns_only_matching_recent_items(feeds):
    feeds(A=_rss(("RBI raises repo rate by 25 bps", ago(2), ""), ("Cricket: India win toss", ago(1), ""), ("RBI old story on repo rate", ago(200), "")))
    out = news.fetch_news("RBI repo rate", google=False)
    assert [i["title"] for i in out] == ["RBI raises repo rate by 25 bps"]  # off-topic and >72h items excluded


def test_same_story_from_several_publishers_is_merged_and_counted(feeds):
    feeds(A=_rss(("Rupee slips 4 paise to 96.39 against US dollar", ago(3), "")),
          B=_rss(("Rupee slips 4 paise against US dollar at 96.39", ago(2), "")),
          C=_rss(("Crude jumps on Hormuz fears", ago(1), "")))
    out = news.fetch_news(google=False)
    rupee = [i for i in out if "Rupee" in i["title"]]
    assert len(rupee) == 1 and rupee[0]["sources"] == 2
    assert any("Crude" in i["title"] for i in out)


def test_rare_words_outrank_common_ones(feeds):
    feeds(A=_rss(("Salguti Industries voting results for AGM", ago(1), ""), ("Reliance Q2 results beat estimates", ago(5), ""),
                 ("Godrej Industries shares rise", ago(1), ""), ("Bajaj Industries expands plant", ago(1), ""),
                 ("Mahindra Industries output up", ago(1), ""), ("Tata results due", ago(1), ""), ("Infosys results", ago(1), ""),
                 ("Wipro results", ago(1), ""), ("HCL results", ago(1), "")))
    assert news.fetch_news("Reliance Industries results", google=False)[0]["title"].startswith("Reliance")


def test_a_dead_feed_does_not_break_the_others_and_stale_copy_is_served(feeds, monkeypatch):
    feeds(A=_rss(("Sensex rallies", ago(1), "")), B=ConnectionError("down"))
    assert [i["title"] for i in news.fetch_news(google=False)] == ["Sensex rallies"]


def test_switch_off_returns_nothing(feeds, monkeypatch):
    feeds(A=_rss(("Sensex rallies", ago(1), "")))
    monkeypatch.setattr(news.settings, "FI_NEWS_RSS", False)
    assert news.fetch_news() == []


def test_format_headlines_shows_source_age_and_corroboration():
    line = news.format_headlines([{"title": "T", "source": "ET", "age_hours": 3.2, "sources": 4}, {"title": "U", "source": "BBC", "age_hours": 80, "sources": 1}])
    assert line == ["T (ET, 3h ago, 4 sources)", "U (BBC, 3d ago)"]


def test_scope_words_do_not_narrow_a_briefing():
    assert news._keywords("Give me the latest news from India and abroad") == []
    assert news._keywords("any top headlines this morning?") == []
    assert news._keywords("What is the latest on Reliance Industries abroad?") == ["reliance", "industries"]


def test_only_time_sensitive_questions_want_news():
    for q in ["What is the latest on gold?", "Should I buy Reliance now?", "How is the market today?", "any news on the rupee"]:
        assert news.wants_news(q), q
    for q in ["What is a mutual fund?", "I earn 60000 a month, what SIP should I start?", "Explain compound interest"]:
        assert not news.wants_news(q), q


def test_headlines_reach_every_llm_call_inside_a_module_and_only_there(feeds, monkeypatch):
    feeds(A=_rss(("Gold slips as the dollar firms", ago(1), "")))
    from ai.llm import groq_client

    prompts = []
    monkeypatch.setattr(groq_client, "_BACKENDS", (("fake", lambda prompt, system, model: prompts.append(system) or "ok."),))
    with news.news_context("What is the latest on gold?") as items:
        groq_client.generate_response("question", system_prompt="You are ARIA.")
    groq_client.generate_response("question", system_prompt="You are ARIA.")  # outside the block: untouched
    assert len(items) == 1
    assert "Gold slips as the dollar firms" in prompts[0] and prompts[0].startswith("You are ARIA.")
    assert prompts[1] == "You are ARIA."
    with news.news_context("What is a mutual fund?") as none:  # not time-sensitive: nothing fetched, nothing added
        assert none == [] and news.current_news_block() is None


def test_exchange_rate_sentences_keep_their_dollars_but_plain_amounts_still_become_rupees():
    from ai.llm.groq_client import normalize_currency

    fx = "The rupee slipped to 83.4 per dollar, weakest against the US dollar in two months."
    assert normalize_currency(fx) == fx
    assert normalize_currency("The dollar index rose.") == "The dollar index rose."
    assert normalize_currency("You could invest $5,000 or 200 dollars.") == "You could invest ₹5,000 or 200 rupees."
