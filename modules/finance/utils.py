"""Small finance utility functions."""

from dataclasses import dataclass
from typing import Any

from modules.finance.risk_model import RiskPrediction


@dataclass
class BudgetAllocation:
    housing: float
    food: float
    utilities: float
    transport: float
    emergency_fund_add: float
    sip: float


@dataclass
class SipPlan:
    monthly_sip: float
    equity_fraction: float
    debt_fraction: float
    tax_saver_amount: float


def optimize_budget(
    income: float,
    existing_emi: float,
    city_tier: str,
    risk: RiskPrediction,
    emergency_months_covered: float = 0,
) -> BudgetAllocation:
    housing_rate = 0.25 if city_tier == "tier_1" else 0.20
    emergency_rate = 0.08 if emergency_months_covered < 6 else 0.03
    sip_rate = 0.12 if risk.label == "low" else 0.08 if risk.label == "medium" else 0.05
    return BudgetAllocation(
        housing=income * housing_rate + existing_emi,
        food=income * 0.12,
        utilities=income * 0.06,
        transport=income * 0.05,
        emergency_fund_add=income * emergency_rate,
        sip=income * sip_rate,
    )


def build_sip_plan(sip_amount: float, risk: RiskPrediction, tax_regime: str) -> SipPlan:
    equity = 0.7 if risk.label == "low" else 0.6 if risk.label == "medium" else 0.45
    tax_saver = min(sip_amount, 12500.0) if tax_regime == "old" else 0.0
    return SipPlan(
        monthly_sip=sip_amount,
        equity_fraction=equity,
        debt_fraction=1 - equity,
        tax_saver_amount=tax_saver,
    )


def load_finance_data(path: str) -> list[dict[str, Any]]:
    return []
