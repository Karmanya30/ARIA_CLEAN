"""LP budget allocator -- feasibility across personas + clear infeasible error."""
import pytest

from modules.finance.budget_optimize import optimize_budget

_PERSONAS = [
    ("young_it_pro", 134_760, 5_000, 1, "Aggressive"),
    ("midcareer_family", 164_150, 45_000, 1, "Moderate"),
    ("early_grad", 35_397, 0, 2, "Moderate"),
    ("near_retirement", 177_791, 8_000, 1, "Conservative"),
    ("self_employed", 93_365, 12_000, 3, "Moderate"),
]


@pytest.mark.parametrize("name,income,emi,city_tier,risk", _PERSONAS)
def test_feasible_for_every_persona(name, income, emi, city_tier, risk):
    budget = optimize_budget(
        income=income, existing_emi=emi, city_tier=city_tier,
        risk_label=risk, emergency_fund_months=2.0,
    )
    total = (
        budget.housing + budget.food + budget.transport + budget.utilities
        + budget.emi + budget.sip + budget.entertainment + budget.emergency_fund_add
    )
    assert total == pytest.approx(income, abs=2.0)
    assert budget.emi == emi
    assert budget.sip >= 0


def test_infeasible_budget_raises_clear_error():
    with pytest.raises(ValueError, match="infeasible"):
        optimize_budget(
            income=20_000, existing_emi=18_000, city_tier=1,
            risk_label="Moderate", emergency_fund_months=0,
        )


def test_zero_income_raises_instead_of_crashing():
    with pytest.raises(ValueError):
        optimize_budget(
            income=0, existing_emi=0, city_tier=1,
            risk_label="Moderate", emergency_fund_months=0,
        )
