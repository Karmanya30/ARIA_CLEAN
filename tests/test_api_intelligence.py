"""Company intelligence: chat routing, the two research endpoints, and that a market query never loads the model."""
import subprocess
import sys

import core.orchestrator as orch
from fastapi.testclient import TestClient

from api.main import app
from core.session import clear_session
from modules.equity_research.intelligence import pipeline

client = TestClient(app)
RESULT = {"domain": "company_intelligence", "company": {"name": "TCS", "symbol": "TCS.NS"}, "response": "TCS scores 64/100 (mixed).",
          "intelligence": {"score": 64}, "scorecard": {}, "news": [], "call": {"available": False}}


def test_chat_routes_company_sentiment_questions_to_company_intelligence(monkeypatch):
    monkeypatch.setattr(orch, "resolve_company", lambda q: "TCS")
    monkeypatch.setattr(orch, "company_intelligence", lambda q: dict(RESULT))
    clear_session("__pytest_intel__")
    assert orch.handle_query("what is the sentiment on TCS", session_id="__pytest_intel__")["domain"] == "company_intelligence"


def test_intelligence_endpoint(monkeypatch):
    monkeypatch.setattr(pipeline, "company_intelligence", lambda q: dict(RESULT) if q == "tcs" else None)
    ok = client.get("/api/research/intelligence", params={"q": "tcs"})
    assert ok.status_code == 200 and ok.json()["intelligence"]["score"] == 64
    assert client.get("/api/research/intelligence", params={"q": "zzz"}).status_code == 404


def test_sentiment_endpoint_scores_with_keywords_and_limits_input():
    r = client.post("/api/research/sentiment", json={"texts": ["Profits surge to a record", "x" * 5000]})
    body = r.json()
    assert r.status_code == 200 and body["engine"] == "keywords" and body["items"][0]["label"] == "positive" and len(body["items"][1]["text"]) == 1000
    assert client.post("/api/research/sentiment", json={"texts": ["a"] * 51}).status_code == 422


def test_market_news_tone_does_not_load_torch():
    code = ("import sys\nfrom modules.market import analyzer\n"
            "analyzer.fetch_news = lambda q, limit=12: [{'title': 'Sensex surges', 'source': 's', 'age_hours': 1, 'sources': 1}]\n"
            "r = analyzer.get_market_news_with_tone('nifty')\nassert r[1]['engine'] == 'keywords', r\nassert 'torch' not in sys.modules\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**__import__("os").environ, "ARIA_SENTIMENT": "0"})
    assert out.returncode == 0, out.stderr[-500:]
