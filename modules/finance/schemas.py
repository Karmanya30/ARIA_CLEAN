"""Data contracts for Module 1 — Personal Finance Assistant."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

# 8 categories — matches config.model_config.LSTM_N_CATS
CATEGORIES = [
    "housing",
    "food",
    "transport",
    "utilities",
    "emi",
    "entertainment",
    "medical",
    "other",
]

# Matches config.settings.RISK_LABELS / config.model_config.XGB_RISK_CLASSES
RISK_LABELS = ["Conservative", "Moderate", "Aggressive"]


class Transaction(BaseModel):
    date: date
    category: str  # one of CATEGORIES
    amount: float  # positive = expense (₹)
    merchant: str | None = None
    channel: str | None = None  # upi | card | cash | netbanking


class UserFinancialInput(BaseModel):
    user_id: str
    monthly_income: float
    age: int = 30
    dependents: int = 0
    existing_emi: float = 0.0
    emergency_fund_months: float = 0.0
    city_tier: int = 1  # 1 / 2 / 3
    tax_regime: str = "new"  # "old" | "new"
    transactions: list[Transaction] = Field(default_factory=list)


class RiskProfile(BaseModel):
    label: str
    confidence: float
    top_features: list[tuple[str, float]] = Field(default_factory=list)


class CategoryForecast(BaseModel):
    category: str
    forecast: list[float]  # next N months, P50
    lower_ci: list[float]  # P10
    upper_ci: list[float]  # P90


class AnomalyFlag(BaseModel):
    transaction: Transaction
    score: float
    reason: str


class BudgetAllocation(BaseModel):
    housing: float
    food: float
    transport: float
    utilities: float
    emi: float
    sip: float
    entertainment: float
    emergency_fund_add: float


class SipPlan(BaseModel):
    monthly_sip: float
    equity_pct: float
    debt_pct: float
    tax_saver_amount: float


class TaxResult(BaseModel):
    annual_income: float
    taxable_income: float
    tax_before_cess: float
    cess: float
    total_tax: float
    effective_rate: float
    regime: str


class M1Response(BaseModel):
    risk: RiskProfile
    forecast: list[CategoryForecast]
    anomalies: list[AnomalyFlag]
    budget: BudgetAllocation
    sip_plan: SipPlan
    tax: TaxResult
    natural_language: str
