"""WP4 fundamentals: rebuild the report's scenario values from its recorded assumptions."""
import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "equity_research"))
from test_intel_report_html import report_for  # noqa: E402

from modules.equity_research.forecast.contracts import RETRO_NOTE  # noqa: E402
from modules.equity_research.forecast.fundamentals import check_fundamentals  # noqa: E402


@pytest.fixture(scope="module")
def op():
    return report_for()


@pytest.fixture(scope="module")
def bank():
    return report_for("bank")


def test_operating_reproduces_within_tolerance(op):
    fc = check_fundamentals(op, None)
    assert [c.scenario for c in fc.cases] == ["bear", "base", "bull"]
    for c in fc.cases:
        assert c.reported_value and c.reproduced_value
        assert c.abs_diff_pct < 0.5, c
        assert c.ok is True, c.issues
    assert fc.retro_accuracy_note == RETRO_NOTE
    assert any("not available" in n for n in fc.notes)  # no multiples history, no px


def test_bank_ddm_reproduces(bank):
    assert bank["scenarios"]["model"] == "DDM"
    fc = check_fundamentals(bank, None)
    for c in fc.cases:
        assert c.reproduced_value is not None and c.abs_diff_pct < 0.5 and c.ok, c


def test_ddm_without_terminal_roe_is_flagged_not_filled(bank):
    r = copy.deepcopy(bank)
    r["valuation"]["ddm"]["inputs"].pop("terminal_roe")
    c = check_fundamentals(r, None).cases[1]
    assert c.reproduced_value is None and c.ok is None
    assert any("unsupported" in i for i in c.issues)


def test_tampered_growth_is_flagged(op):
    r = copy.deepcopy(op)
    base = next(c for c in r["scenarios"]["cases"] if c["key"] == "base")
    base["detail"]["assumptions"]["g1"] += 0.05
    fc = check_fundamentals(r, None)
    c = fc.cases[1]
    assert c.ok is False and c.abs_diff_pct > 0.5
    assert any("differs from the reported" in i for i in c.issues)
    assert any("base: year-1 revenue growth" in f and "maximum" in f for f in fc.assumption_flags)


def test_tampered_reported_value_and_discounting(op):
    r = copy.deepcopy(op)
    cases = r["scenarios"]["cases"]
    cases[2]["value"] *= 1.03
    cases[0]["detail"]["discount_factor"][3] *= 0.98
    fc = check_fundamentals(r, None)
    assert fc.cases[2].ok is False
    assert fc.cases[0].ok is False and any("discount periods" in i for i in fc.cases[0].issues)
    assert fc.cases[1].ok is True


def test_units_mismatch(op):
    r = copy.deepcopy(op)
    r["cover"]["price"] = r["cover"]["price"] * 1000
    assert any(i.startswith("units") for c in check_fundamentals(r, None).cases for i in c.issues)


def test_sensitivity_notes(op):
    notes = check_fundamentals(op, None).sensitivity_notes
    assert any("WACC" in n and "+1pp" in n for n in notes)
    assert any("terminal growth" in n for n in notes)
    assert any("margin" in n for n in notes)


def test_no_scenarios_returns_explanation(op):
    r = {**op, "scenarios": None}
    fc = check_fundamentals(r, None)
    assert fc.cases == [] and "withheld" in fc.notes[0]


def test_px_peer_note_and_determinism(op):
    px = pd.DataFrame({"adj_close": [1.0, 2.0]})
    a, b = check_fundamentals(op, px), check_fundamentals(op, px)
    assert a == b
    assert any(n.startswith("Peer context") for n in a.notes)
