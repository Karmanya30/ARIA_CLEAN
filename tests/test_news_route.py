from core import orchestrator


def test_news_requests_return_the_headlines_not_one_canned_snapshot(monkeypatch):
    items = [{"title": "RBI holds rates", "source": "Test Wire", "age_hours": 2.0, "sources": 1}]
    monkeypatch.setattr("shared.news.fetch_news", lambda query, limit=8, **k: items)
    monkeypatch.setattr(orchestrator, "save_turn", lambda *a, **k: None)
    a = orchestrator._handle("rbi news", "__news_a__")
    assert "RBI holds rates" in a["response"] and "about rbi" in a["response"]
    monkeypatch.setattr("shared.news.fetch_news", lambda query, limit=8, **k: [])
    b = orchestrator._handle("latest news", "__news_b__")
    assert "couldn't find fresh headlines" in b["response"]
