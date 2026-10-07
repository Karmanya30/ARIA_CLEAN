"""Screener documents, earnings-call transcript cleaning/fetching, and the FinBERT scorer."""
import pytest
from _intel_fixtures import operating_raw
from bs4 import BeautifulSoup

from modules.equity_research.intelligence import data, sentiment
from modules.equity_research.intelligence.data import Target, build_snapshot
from modules.equity_research.screener_adapter import Screener

HTML = """
<section id="documents">
  <div class="annual-reports"><h3>Annual reports</h3><ul>
    <li><a href="https://bseindia.com/ar2026.pdf">Annual Report 2026</a></li>
    <li><a href="https://bseindia.com/ar2025.pdf">Annual Report 2025</a></li>
  </ul></div>
  <div class="concalls"><h3>Concalls</h3><ul class="list-links">
    <li><div>Jul 2026</div> | <a href="https://x/t1.pdf">Transcript</a> | <a>AI</a> | <a href="https://x/p1.pdf">PPT</a> | <a href="https://x/r1">REC</a></li>
    <li><div>Apr 2026</div> | <a href="https://x/p2.pdf">PPT</a></li>
    <li><div>Jan 2026</div> | <a href="https://x/r3">REC</a></li>
  </ul></div>
</section>"""


def docs(html):
    return Screener._documents(BeautifulSoup(html, "html.parser"))


def test_documents_parsed():
    d = docs(HTML)
    assert d["annual_reports"][0] == {"label": "Annual Report 2026", "url": "https://bseindia.com/ar2026.pdf"}
    assert d["concalls"] == [
        {"period": "Jul 2026", "transcript": "https://x/t1.pdf", "ppt": "https://x/p1.pdf"},
        {"period": "Apr 2026", "transcript": None, "ppt": "https://x/p2.pdf"},
    ]  # the REC-only row is dropped


def test_documents_absent():
    assert docs("<html><body>nothing</body></html>") == {"concalls": [], "annual_reports": []}


S1 = "Revenue for the quarter grew by 12.5 percent to Rs. 5.8 lakh crore driven by strong execution across segments."
S2 = "The order book remains healthy and we expect margins to improve over the coming year as projects mature."
S3 = "Thank you."  # too short
LONG = "Long " + " ".join(["word"] * 90) + "."


def test_clean_transcript():
    pages = [f"ACME Ltd Q1 Earnings Call\n{body}\nPage {i} of 5\n{i}" for i, body in enumerate([
        "Ladies and gentlemen, welcome to the call. This conference call is being recorded.\n" + S1 + " " + S2,
        "Ladies and gentlemen, you are in listen-only mode. " + S3 + "\nmargin expan-\nsion continues to be our focus this year across all business units. " + LONG,
        "Plain filler page.", "More filler.", "Last page."], 1)]
    out = data._clean_transcript(pages)
    assert S1 in out and S2 in out  # "Rs. 5.8" and "12.5" did not split the sentence
    assert any("margin expansion continues" in s for s in out)  # hyphenation rejoined
    assert not any("ACME" in s or "Page" in s or "recorded" in s or "listen-only" in s for s in out)
    assert S3 not in out and LONG not in out


@pytest.fixture
def fake_pdf(monkeypatch):
    class Resp:
        headers = {"content-type": "application/pdf"}

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b"%PDF-fake"

    monkeypatch.setattr(data.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(data, "_pdf_pages", lambda content: [S1 + " " + S2])
    return Resp


def test_get_concall_ok(fake_pdf):
    d = {"concalls": [{"period": "Apr 2026", "transcript": None}, {"period": "Jan 2026", "transcript": "https://x/ok.pdf"}]}
    assert data.get_concall(d) == {"period": "Jan 2026", "url": "https://x/ok.pdf", "sentences": [S1, S2]}


def test_get_concall_failures(fake_pdf, monkeypatch):
    assert data.get_concall({"concalls": [{"period": "Jul 2026", "transcript": None}]}) is None
    assert data.get_concall({}) is None
    fake_pdf.headers = {"content-type": "text/html"}
    assert data.get_concall({"concalls": [{"period": "a", "transcript": "https://x/page"}]}) is None

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(data.requests, "get", boom)
    assert data.get_concall({"concalls": [{"period": "b", "transcript": "https://x/b.pdf"}]}) is None


def test_build_snapshot_carries_documents_and_concall():
    kw = dict(screener_raw=operating_raw(), info={}, as_of="2026-09-29")
    t = Target("TESTCO", "TESTCO.NS", "Test")
    docs_ = {"concalls": [], "annual_reports": [{"label": "AR", "url": "u"}]}
    s = build_snapshot(t, documents=docs_, concall={"period": "Jul 2026", "url": "u", "sentences": ["x"]}, **kw)
    assert s.documents == docs_ and s.concall["period"] == "Jul 2026"
    s = build_snapshot(t, **{**kw, "screener_raw": {**operating_raw(), "documents": docs_}})
    assert s.documents == docs_ and s.concall is None


def test_label_thresholds():
    assert [sentiment.label(x) for x in (0.25, 0.9, -0.25, -1, 0.24, 0)] == [
        "positive", "positive", "negative", "negative", "neutral", "neutral"]


def test_score_disabled_and_empty(monkeypatch):
    monkeypatch.setenv("ARIA_SENTIMENT", "0")
    assert sentiment.score(["Revenue grew."]) is None
    assert sentiment.score([]) == []


@pytest.mark.skipif(not (sentiment.model_dir() / "pytorch_model.bin").exists(), reason="FinBERT weights not downloaded")
def test_finbert_real(monkeypatch):
    monkeypatch.setenv("ARIA_SENTIMENT", "1")
    pos, neg = sentiment.score(["Revenue grew 25% and margins expanded to a record.",
                                "The company reported a net loss and cut its guidance."])
    assert pos["net"] > 0.5 and neg["net"] < -0.5
    for r in (pos, neg):
        assert abs(r["positive"] + r["negative"] + r["neutral"] - 1) < 1e-3


def test_tone_uses_keywords_and_never_loads_the_model(monkeypatch):
    monkeypatch.setattr(sentiment, "_model", None)
    t = sentiment.tone(["Profits surge to a record", "Company faces probe and penalty", "Board meets on Monday"])
    assert t["engine"] == "keywords" and [i["label"] for i in t["items"]] == ["positive", "negative", "neutral"] and t["label"] == "neutral"
    assert sentiment._model is None and sentiment.tone([])["items"] == []


def test_score_cache_hit_skips_the_model_and_a_busy_model_returns_none(monkeypatch):
    monkeypatch.setattr(sentiment, "enabled", lambda: True)
    monkeypatch.setitem(sentiment._cache, "cached text", {"net": 0.4})
    monkeypatch.setattr(sentiment, "_load", lambda: pytest.fail("the model must not be touched for a cached text"))
    assert sentiment.score(["cached text", "cached text"]) == [{"net": 0.4}, {"net": 0.4}]
    with sentiment._lock:
        assert sentiment.score(["not cached"], wait=0.01) is None
        assert sentiment.score(["cached text"], wait=0.01) == [{"net": 0.4}]  # a cache hit never waits for the lock
