"""Report kinds, DuPont / common-size tables, the disclosure page, kind detection and PDF/API paths."""
import re

import pytest
from _intel_fixtures import make_snapshot
from fastapi.testclient import TestClient
from test_intel_report_html import report_for
from test_intel_store_api import make_report, owner  # noqa: F401  (fixtures)

from api.main import app
from core.router import is_research_report_query
from modules.equity_research.intelligence import report_pdf
from modules.equity_research.intelligence.analysis import analyze
from modules.equity_research.intelligence.facts import Ledger
from modules.equity_research.intelligence.pipeline import report_kind
from modules.equity_research.intelligence.report_html import KINDS, render_html

client = TestClient(app)


@pytest.fixture(scope="module")
def op():
    return report_for()


@pytest.fixture(scope="module")
def bank():
    return report_for("bank")


def table(rep, prefix):
    return next(t for t in rep["financials"]["tables"] if t["title"].startswith(prefix))


def test_dupont_factors_multiply_to_roe_for_every_year(op):
    t = table(op, "DuPont")
    rows = {r["label"].split(" (")[0]: r["values"] for r in t["rows"]}
    assert {"Tax and minority burden", "Interest burden", "EBIT margin", "Asset turnover", "Equity multiplier", "Return on equity"} <= set(rows)
    for y, roe in rows["Return on equity"].items():
        prod = (rows["Tax and minority burden"][y] / 100 * rows["Interest burden"][y] / 100 * rows["EBIT margin"][y] / 100
                * rows["Asset turnover"][y] * rows["Equity multiplier"][y])
        assert prod * 100 == pytest.approx(roe, rel=1e-9)


def test_bank_uses_three_step_dupont_and_note_names_a_driver(bank, op):
    labels = [r["label"] for r in table(bank, "DuPont")["rows"]]
    assert labels[0].startswith("Net margin") and not any("Interest burden" in l for l in labels)
    assert op["dupont_note"].startswith("Return on equity moved from") and ("came mainly from" in op["dupont_note"] or "flat" in op["dupont_note"])


def test_common_size_rows_are_shares_of_the_right_denominator(op):
    inc = {r["label"]: r["values"] for r in table(op, "Common-size income")["rows"]}
    bs = {r["label"]: r["values"] for r in table(op, "Common-size balance")["rows"]}
    an = analyze(make_snapshot(), Ledger())
    last = "FY2026"
    assert inc["Operating profit (EBITDA)"][last] == pytest.approx(an.facts["opm"].value, abs=0.01)
    assert bs["Net worth (equity capital + reserves)"][last] == pytest.approx(an.series["net_worth"]["Mar 2026"] / an.series["total_assets"]["Mar 2026"] * 100)
    assert "Working-capital cycle (days)" in [t["title"] for t in op["financials"]["tables"]]


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_kind_renders_numbered_sections_and_ends_with_the_disclosure_page(op, kind):
    html = render_html(op, kind)
    nums = [int(n) for n in re.findall(r'<section[^>]*><h2><span class="n">(\d+)</span>', html)]
    assert nums == list(range(1, len(nums) + 1))
    assert KINDS[kind][0] in html and html.rindex("Important disclosures") > html.rindex("Verification, sources and methodology")
    for needle in ("not investment advice", "SEBI-registered", "No analyst certification", "Conflicts of interest", "Undervalued if fair value exceeds price by",
                   "Use of artificial intelligence", "Limitations of this report", "Risk warning"):
        assert needle.lower() in html.lower(), needle


def test_kinds_include_only_their_sections(op):
    dupont, val, model = render_html(op, "dupont"), render_html(op, "valuation"), render_html(op, "financial_model")
    assert "DuPont analysis" in dupont and "Valuation by method" not in dupont and "Bull vs bear" not in dupont
    assert "Valuation by method" in val and "Common-size" not in val and "DuPont analysis" not in val
    assert all(x in model for x in ("DuPont analysis", "Common-size statements", "Valuation by method"))
    assert "Exit-multiple cross-check" in val and "Implied terminal EV/EBITDA" in val


def test_disclosure_shows_the_real_verdict_bands():
    from modules.equity_research.intelligence.comps import VERDICT_BANDS

    html = render_html(report_for())
    assert all(f"{b * 100:.0f}%" in html for pair in VERDICT_BANDS.values() for b in pair)


def test_print_mode_adds_the_print_button_and_autoprint(op):
    assert "window.print" not in render_html(op)
    assert "Save as PDF" in render_html(op, printable=True) and "setTimeout" in render_html(op, printable=True, autoprint=True)


@pytest.mark.parametrize("query, kind", [
    ("equity research report on TCS", "equity_research"), ("dupont analysis of Infosys", "dupont"), ("financial model of ITC", "financial_model"),
    ("DCF valuation of Wipro", "valuation"), ("valuation report on HDFC Bank", "valuation"), ("tell me about TCS", "equity_research")])
def test_report_kind_detection(query, kind):
    assert report_kind(query) == kind


def test_router_sends_the_new_report_types_but_not_concept_questions():
    assert is_research_report_query("dupont analysis of TCS", "TCS") and is_research_report_query("financial model for Infosys", "INFY")
    assert not is_research_report_query("what is dupont analysis", None) and not is_research_report_query("explain a financial model", None)


def test_api_kind_views_downloads_and_pdf(owner, make_report, monkeypatch):
    rid = make_report(owner)["report_id"]
    p = {"owner_id": owner}
    html = client.get(f"/api/research/reports/{rid}/html", params={**p, "kind": "dupont"}).text
    assert "DuPont and ratio analysis" in html and "window.print" not in html
    assert "window.print" in client.get(f"/api/research/reports/{rid}/html", params={**p, "print": "true"}).text
    assert client.get(f"/api/research/reports/{rid}/html", params={**p, "kind": "nope"}).status_code == 400
    d = client.get(f"/api/research/reports/{rid}/download", params={**p, "format": "html", "kind": "valuation"})
    assert "_valuation_v1_" in d.headers["content-disposition"] and "Save as PDF" in d.text
    monkeypatch.setattr(report_pdf, "find_browser", lambda: None)
    r = client.get(f"/api/research/reports/{rid}/download", params={**p, "format": "pdf"})
    assert r.status_code == 501 and "Chrome or Edge" in r.json()["detail"]
    monkeypatch.setattr("modules.equity_research.intelligence.report_pdf.render_pdf", lambda html: b"%PDF-1.4 fake")
    r = client.get(f"/api/research/reports/{rid}/download", params={**p, "format": "pdf"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-disposition"].endswith('.pdf"')


# ── ratios from Yahoo, ROIC, Wikipedia background ──
def test_yahoo_ratios_and_roic_become_facts_and_leave_the_gap_list():
    from _intel_fixtures import operating_info

    from modules.equity_research.intelligence.data import get_wiki_context  # noqa: F401

    snap = make_snapshot(info=operating_info(grossMargins=0.41, currentRatio=1.8, quickRatio=1.2))
    an = analyze(snap, Ledger())
    assert an.facts["gross_margin"].value == pytest.approx(41.0) and an.facts["current_ratio"].value == 1.8 and an.facts["quick_ratio"].value == 1.2
    nw, debt, cash = an.series["net_worth"]["Mar 2026"], 300.0, 200.0
    ebit = an.facts["ebit"].value
    assert an.facts["roic"].value == pytest.approx(ebit * (1 - 0.25) / (nw + debt - cash) * 100, rel=0.02)
    rep = report_for(info=operating_info(grossMargins=0.41, currentRatio=1.8, quickRatio=1.2))
    assert not {"Gross profit and gross margin", "Current and quick ratios", "ROIC"} & {x["item"] for x in rep["not_available"]}
    assert {"Gross margin", "Current ratio", "Quick ratio", "Return on invested capital (ROIC)"} <= {i["label"] for g in rep["ratio_groups"] for i in g["items"]}
    assert "Current ratio" not in {f.label for f in [f for f in analyze(make_snapshot("bank"), Ledger()).facts.values()]}


def test_wikipedia_background_is_shown_labelled_and_wrong_company_matches_are_dropped(monkeypatch):
    from modules.equity_research.intelligence import data

    pages = {"Testco": {"title": "Testco Limited", "text": "Testco is a software firm. " * 10, "url": "https://en.wikipedia.org/wiki/Testco"},
             "Software industry": {"title": "Software industry", "text": "The software industry makes programs. " * 8, "url": ""},
             "Other": {"title": "Unrelated Corp", "text": "x" * 200, "url": ""}}
    monkeypatch.setattr(data, "_wiki_summary", lambda q: pages.get(q))
    assert [w["kind"] for w in data.get_wiki_context("Testco Limited", "Software")] == ["Company", "Industry"]
    monkeypatch.setattr(data, "_wiki_summary", lambda q: pages["Software industry"] if "industry" in q else pages["Other"])
    got = data.get_wiki_context("Testco Limited", "Software")
    assert [w["kind"] for w in got] == ["Industry"]  # the unrelated company article is dropped

    def boom(q):
        raise RuntimeError("offline")

    monkeypatch.setattr(data, "_wiki_summary", boom)
    assert data.get_wiki_context("Testco Limited", "Software") == []
    snap = make_snapshot()
    snap.wiki = [{"kind": "Company", "title": "Testco Limited", "text": "Testco is a <b>software</b> firm.", "url": "https://en.wikipedia.org/wiki/Testco"},
                 {"kind": "Industry", "title": "Software industry", "text": "About software.", "url": ""}]
    from modules.equity_research.intelligence.report import build_report  # noqa: F401
    rep = report_for(); rep["wiki"] = snap.wiki
    html = render_html(rep)
    assert "Company background" in html and "Industry background" in html and "&lt;b&gt;software" in html and "Source: Wikipedia" in html
    assert 'href="https://en.wikipedia.org/wiki/Testco"' in html and "CC BY-SA 4.0" in html


def test_llm_answers_are_cached_by_prompt_but_failures_are_not(monkeypatch):
    from _intel_fixtures import FakeLLM, good_analyst

    from modules.equity_research.intelligence import agents

    snap = make_snapshot(); snap.wiki = [{"kind": "Company", "title": "Testco", "text": "Testco writes software. " * 8, "url": ""}]
    led = Ledger(); an = analyze(snap, led)
    from modules.equity_research.intelligence.valuation import value_company
    val = value_company(snap, an, led)
    llm = FakeLLM(analyst=good_analyst)
    monkeypatch.setattr(agents, "generate_response", llm)
    agents.narrate(snap, an, val, led); agents.narrate(snap, an, val, led)
    assert llm.count("analyst") == 1  # second run served from the cache
    assert "W1" in llm.calls[0][1] and 'id="W1"' in llm.calls[0][1]
    agents.clear_llm_cache()
    down = FakeLLM(analyst="Error: down")
    monkeypatch.setattr(agents, "generate_response", down)
    agents.narrate(snap, an, val, led); agents.narrate(snap, an, val, led)
    assert down.count("analyst") == 2  # errors are re-attempted, never cached


def test_dupont_note_names_drivers_and_offsets_and_shares_reconcile():
    from modules.equity_research.intelligence.analysis import Analysis, dupont_note

    out = Analysis()
    out.years = ["Mar 2021", "Mar 2026"]
    spec = [("Net margin (A)", "%", "nm"), ("Asset turnover (B)", "x", "turn"), ("Equity multiplier (C)", "x", "mult"), ("Return on equity (A x B x C)", "%", "roe")]
    out.dupont = {"spec": spec, "values": {"nm": {"Mar 2021": 10, "Mar 2026": 5}, "turn": {"Mar 2021": 1, "Mar 2026": 3}, "mult": {"Mar 2021": 2, "Mar 2026": 4},
                                           "roe": {"Mar 2021": 20, "Mar 2026": 60}, "roa": {}, "tax": {}, "int": {}, "ebit": {}}}
    note = dupont_note(out)
    assert "moved from 20.0% in FY2021 to 60.0% in FY2026" in note
    assert "came mainly from asset turnover (about 100% of it) and equity multiplier (63%)" in note and "partly offset by net margin" in note
    out.dupont["values"]["roe"] = {"Mar 2021": 20, "Mar 2026": 20.1}
    assert "essentially flat" in dupont_note(out)


def test_saved_reports_remember_their_kind(owner, make_report):
    from shared import user_store

    make_report(owner)
    assert user_store.list_research_reports(owner)[0]["kind"] == "equity_research"
