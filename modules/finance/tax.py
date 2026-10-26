"""
Indian income tax computation — deterministic, no ML.

Normal-income slabs checked against the Income Tax Department's
"Computation of Tax for Individual" (Finance Act 2026), 2026-10-16:
https://www.incometaxindia.gov.in/w/computation-of-tax-for-individual-1
Uses the published AY 2026-27 schedule. Tax law changes every budget
cycle — this module is intentionally small and isolated so the constants
below are the only thing that ever needs revisiting; it is not a
certified tax-filing tool, only a demo-grade estimate.
"""
from __future__ import annotations

from modules.finance.schemas import TaxResult

CESS_RATE = 0.04  # Health & Education Cess, both regimes

# ── New regime (default since FY 2023-24; these are the FY 2025-26 slabs) ──
NEW_REGIME_SLABS = [
    (400_000, 0.00),
    (800_000, 0.05),
    (1_200_000, 0.10),
    (1_600_000, 0.15),
    (2_000_000, 0.20),
    (2_400_000, 0.25),
    (float("inf"), 0.30),
]
NEW_REGIME_STD_DEDUCTION = 75_000
NEW_REGIME_REBATE_THRESHOLD = 1_200_000  # taxable income at/below this -> zero tax
NEW_REGIME_REBATE_CAP = 60_000

# ── Old regime (unchanged for years) ────────────────────────────────────
OLD_REGIME_SLABS = [
    (250_000, 0.00),
    (500_000, 0.05),
    (1_000_000, 0.20),
    (float("inf"), 0.30),
]
OLD_REGIME_STD_DEDUCTION = 50_000
OLD_REGIME_REBATE_THRESHOLD = 500_000
OLD_REGIME_REBATE_CAP = 12_500
OLD_REGIME_80C_CAP = 150_000
OLD_REGIME_80D_CAP_SELF = 25_000
OLD_REGIME_80D_CAP_SENIOR = 50_000


def _slab_tax(taxable: float, slabs: list[tuple[float, float]]) -> float:
    tax, prev = 0.0, 0.0
    for slab, rate in slabs:
        if taxable <= slab:
            tax += (taxable - prev) * rate
            break
        tax += (slab - prev) * rate
        prev = slab
    return tax


def _apply_rebate_and_marginal_relief(
    taxable: float, tax_before_rebate: float, threshold: float, rebate_cap: float
) -> float:
    """Section 87A rebate, plus marginal relief just above the threshold so
    tax never jumps by more than the excess income over the threshold."""
    if taxable <= threshold:
        return max(0.0, tax_before_rebate - min(tax_before_rebate, rebate_cap))
    excess = taxable - threshold
    if tax_before_rebate > excess:
        # Marginal relief: cap tax at (taxable - threshold) to smooth the cliff.
        return excess
    return tax_before_rebate


def tax_new(annual_income: float, std_deduction: bool = True) -> TaxResult:
    deduction = NEW_REGIME_STD_DEDUCTION if std_deduction else 0.0
    taxable = max(0.0, annual_income - deduction)
    tax_before = _slab_tax(taxable, NEW_REGIME_SLABS)
    tax = _apply_rebate_and_marginal_relief(
        taxable, tax_before, NEW_REGIME_REBATE_THRESHOLD, NEW_REGIME_REBATE_CAP
    )
    cess = tax * CESS_RATE
    total = tax + cess
    return TaxResult(
        annual_income=annual_income,
        taxable_income=taxable,
        tax_before_cess=round(tax, 2),
        cess=round(cess, 2),
        total_tax=round(total, 2),
        effective_rate=round((total / annual_income * 100) if annual_income else 0.0, 2),
        regime="new",
    )


def tax_old(
    annual_income: float,
    deductions_80c: float = 0.0,
    deductions_80d: float = 0.0,
    is_senior: bool = False,
    *,
    age: int | None = None,
) -> TaxResult:
    is_senior = is_senior or (age is not None and age >= 60)
    cap_80d = OLD_REGIME_80D_CAP_SENIOR if is_senior else OLD_REGIME_80D_CAP_SELF
    deduction = (
        OLD_REGIME_STD_DEDUCTION
        + min(deductions_80c, OLD_REGIME_80C_CAP)
        + min(deductions_80d, cap_80d)
    )
    taxable = max(0.0, annual_income - deduction)
    exemption = 500_000 if age is not None and age >= 80 else 300_000 if is_senior else 250_000
    slabs = [(exemption, 0.0), *OLD_REGIME_SLABS[1:]]
    tax_before = _slab_tax(taxable, slabs)
    # The old regime has an 87A rebate, but no income-cliff marginal relief.
    tax = max(0.0, tax_before - OLD_REGIME_REBATE_CAP) if taxable <= OLD_REGIME_REBATE_THRESHOLD else tax_before
    cess = tax * CESS_RATE
    total = tax + cess
    return TaxResult(
        annual_income=annual_income,
        taxable_income=taxable,
        tax_before_cess=round(tax, 2),
        cess=round(cess, 2),
        total_tax=round(total, 2),
        effective_rate=round((total / annual_income * 100) if annual_income else 0.0, 2),
        regime="old",
    )


def compute(
    monthly_income: float = 0.0,
    regime: str = "new",
    deductions_80c: float = 0.0,
    deductions_80d: float = 0.0,
    is_senior: bool = False,
) -> TaxResult:
    annual_income = monthly_income * 12
    if regime == "old":
        return tax_old(annual_income, deductions_80c, deductions_80d, is_senior)
    return tax_new(annual_income)


def compute_tax(income: float, regime: str = "new") -> float:
    """Convenience wrapper returning just the total payable tax on an
    annual income."""
    return compute(monthly_income=income / 12, regime=regime).total_tax
