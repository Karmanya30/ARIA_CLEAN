"""
Linear Programming budget allocator — deterministic, no training needed.

The 50-30-20 rule is a starting point, not the answer: this handles the
cases where a fixed rule is infeasible, e.g. someone whose EMI obligation
alone already exceeds 30% of income.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

from modules.finance.schemas import BudgetAllocation

# Decision variables (₹/month), in this fixed order:
#   [housing, food, transport, utilities, emi, sip, entertainment, emergency]
_VARS = ["housing", "food", "transport", "utilities", "emi", "sip", "entertainment", "emergency"]

# Minimum viable monthly spend by city tier (1 = metro, 3 = smaller city)
FLOORS = {
    1: {"food": 10_000, "utilities": 4_000, "transport": 3_000},
    2: {"food": 7_500, "utilities": 3_000, "transport": 2_500},
    3: {"food": 5_000, "utilities": 2_000, "transport": 2_000},
}

# Max SIP as a fraction of income, by risk class
SIP_CAP = {"Conservative": 0.15, "Moderate": 0.25, "Aggressive": 0.35}


def optimize_budget(
    income: float,
    existing_emi: float,
    city_tier: int,
    risk_label: str,
    emergency_fund_months: float,
) -> BudgetAllocation:
    """Maximise SIP contribution subject to realistic floors/caps.

    Raises ValueError with a human-readable reason if the constraints are
    infeasible (e.g. EMI + mandatory floors already exceed income) instead
    of crashing — callers should surface this directly to the user.
    """
    if income <= 0:
        raise ValueError("Cannot optimize a budget for zero or negative income.")

    floor = FLOORS.get(city_tier, FLOORS[1])
    sip_cap_ratio = SIP_CAP.get(risk_label, SIP_CAP["Moderate"])

    # minimize -sip == maximize sip
    c = np.zeros(len(_VARS))
    c[_VARS.index("sip")] = -1.0

    a_eq = np.ones((1, len(_VARS)))
    b_eq = np.array([income])

    emergency_floor = 0.05 * income if emergency_fund_months < 6 else 0.0
    sip_max = sip_cap_ratio * income

    bounds = [
        (0, 0.35 * income),  # housing
        (floor["food"], None),  # food
        (floor["transport"], None),  # transport
        (floor["utilities"], None),  # utilities
        (existing_emi, existing_emi),  # emi — fixed, not optimized
        (0, max(sip_max, 0.0)),  # sip
        (0, 0.15 * income),  # entertainment
        (emergency_floor, None),  # emergency fund top-up
    ]

    result = linprog(c, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")

    if not result.success:
        mandatory_floor = (
            existing_emi
            + floor["food"]
            + floor["transport"]
            + floor["utilities"]
            + emergency_floor
        )
        if mandatory_floor > income:
            raise ValueError(
                f"Budget is infeasible: fixed EMI (₹{existing_emi:,.0f}) plus minimum "
                f"living costs (₹{mandatory_floor - existing_emi:,.0f}) already exceed "
                f"monthly income (₹{income:,.0f})."
            )
        raise ValueError(f"Budget optimizer could not find a feasible allocation: {result.message}")

    x = result.x
    values = {name: round(float(val), 0) for name, val in zip(_VARS, x)}
    return BudgetAllocation(
        housing=values["housing"],
        food=values["food"],
        transport=values["transport"],
        utilities=values["utilities"],
        emi=values["emi"],
        sip=values["sip"],
        entertainment=values["entertainment"],
        emergency_fund_add=values["emergency"],
    )
