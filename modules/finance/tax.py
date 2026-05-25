"""Simple mock tax calculation helpers."""

from dataclasses import dataclass


@dataclass
class TaxResult:
    annual_income: float
    taxable_income: float
    tax: float
    effective_rate: float


def compute(
    monthly_income: float = 0,
    regime: str = "new",
    deductions_80c: float = 0,
) -> TaxResult:
    annual_income = monthly_income * 12
    deduction = 50000 if regime == "new" else min(deductions_80c, 150000) + 50000
    taxable = max(0.0, annual_income - deduction)
    tax = taxable * 0.10
    effective_rate = (tax / annual_income * 100) if annual_income else 0.0
    return TaxResult(annual_income, taxable, tax, effective_rate)


def compute_tax(income: float) -> float:
    return compute(monthly_income=income / 12).tax
