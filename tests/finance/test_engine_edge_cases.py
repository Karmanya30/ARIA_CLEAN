import math

import pytest

from modules.finance import engine, sip_emi_calc
from modules.finance.budget_optimize import optimize_budget


def test_sub_month_tenure_does_not_crash():
    assert sip_emi_calc.sip_required(1e5, 0.04, 12) > 0
    assert sip_emi_calc.sip_required(1e5, 0.04, 0) > 0
    assert sip_emi_calc.emi(1e5, 9, 0.04) > 0 and sip_emi_calc.emi(1e5, 0, 0.04) == 1e5


def test_unknown_surplus_is_reported_not_crashed():
    p = {"monthly_income": 80000, "expenses": {"rent": 20000}}
    assert engine.afford_sip(p, 5000)["verdict"] == "unknown"
    assert engine.sip_capacity(p)["verdict"] == "unknown"


def test_goal_with_no_time_left_needs_the_whole_gap():
    g = engine.goal_plan({"name": "x", "target": 1e6, "years": 0}, {})
    assert g["sip_needed"] >= 1_000_000


@pytest.mark.parametrize("args", [(100000, 0, 1, "Moderate", 3), (100000, 40000, 1, "Moderate", 8), (30000, 5000, 3, "Conservative", 2), (200000, 0, 2, "Aggressive", 8)])
def test_budget_is_a_usable_budget(args):
    income = args[0]
    b = optimize_budget(*args).model_dump()
    assert abs(sum(b.values()) - income) <= 10
    assert b["food"] <= 0.30 * income and b["housing"] > 0
    assert b["sip"] > 0


def test_budget_rejects_negative_emi_and_nan_income():
    with pytest.raises(ValueError):
        optimize_budget(100000, -5000, 1, "Moderate", 3)
    with pytest.raises(ValueError):
        optimize_budget(math.nan, 0, 1, "Moderate", 3)
