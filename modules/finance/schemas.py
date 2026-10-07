"""Data contracts for Module 1 — Personal Finance Assistant."""
from __future__ import annotations

from datetime import date
from typing import Literal

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


# ── Long-term financial profile (every fact optional: None = unknown) ────
class Expenses(BaseModel):
    food: float | None = Field(None, ge=0, le=1e8)
    rent: float | None = Field(None, ge=0, le=1e8)
    transport: float | None = Field(None, ge=0, le=1e8)
    utilities: float | None = Field(None, ge=0, le=1e8)
    entertainment: float | None = Field(None, ge=0, le=1e8)
    health: float | None = Field(None, ge=0, le=1e8)
    education: float | None = Field(None, ge=0, le=1e8)
    other: float | None = Field(None, ge=0, le=1e8)


class Assets(BaseModel):
    cash: float | None = Field(None, ge=0, le=1e11)
    fd: float | None = Field(None, ge=0, le=1e11)
    mf: float | None = Field(None, ge=0, le=1e11)
    stocks: float | None = Field(None, ge=0, le=1e11)
    gold: float | None = Field(None, ge=0, le=1e11)
    epf: float | None = Field(None, ge=0, le=1e11)
    ppf: float | None = Field(None, ge=0, le=1e11)
    nps: float | None = Field(None, ge=0, le=1e11)
    real_estate: float | None = Field(None, ge=0, le=1e11)


class Loan(BaseModel):
    kind: str = Field("other", max_length=30)
    emi: float = Field(ge=0, le=1e8)
    rate_pct: float | None = Field(None, ge=0, le=60)
    months_left: int | None = Field(None, ge=0, le=600)
    outstanding: float | None = Field(None, ge=0, le=1e11)


class Goal(BaseModel):
    name: str = Field(max_length=60)
    target: float = Field(gt=0, le=1e11)
    years: float = Field(gt=0, le=60)
    priority: int = Field(2, ge=1, le=3)
    saved: float = Field(0, ge=0, le=1e11)


class FinanceProfile(BaseModel):
    age: int | None = Field(None, ge=18, le=100)
    city: str | None = Field(None, max_length=60)
    city_tier: int | None = Field(None, ge=1, le=3)
    employment: Literal["salaried", "self_employed", "business", "retired", "student"] | None = None
    marital_status: str | None = Field(None, max_length=20)
    dependents: int | None = Field(None, ge=0, le=20)
    monthly_income: float | None = Field(None, ge=0, le=1e9)
    income_stability: Literal["stable", "variable"] | None = None
    expenses: Expenses | None = None
    assets: Assets | None = None
    loans: list[Loan] | None = Field(None, max_length=20)
    existing_emi: float | None = Field(None, ge=0, le=1e8)  # legacy total-EMI column; loans supersede it
    emergency_fund_months: float | None = Field(None, ge=0, le=600)  # legacy column
    credit_card_outstanding: float | None = Field(None, ge=0, le=1e9)
    term_cover: float | None = Field(None, ge=0, le=1e11)
    health_cover: float | None = Field(None, ge=0, le=1e10)
    goals: list[Goal] | None = Field(None, max_length=20)
    risk_tolerance: Literal["Conservative", "Moderate", "Aggressive"] | None = None
    horizon_years: int | None = Field(None, ge=1, le=60)
    tax_regime: Literal["old", "new"] | None = None
    used_80c: float | None = Field(None, ge=0, le=1e8)
    used_80d: float | None = Field(None, ge=0, le=1e7)
