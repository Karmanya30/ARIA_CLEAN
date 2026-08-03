"""Real FY2025-26 tax slabs -- deterministic, no ML, no LLM."""
from modules.finance.tax import compute, tax_new, tax_old


def test_new_regime_zero_tax_at_12_75_lakh():
    # Well-known reference point: gross 12.75L (with std deduction) is
    # advertised as tax-free under the new regime.
    result = tax_new(1_275_000)
    assert result.taxable_income == 1_200_000
    assert result.total_tax == 0.0


def test_new_regime_marginal_relief_above_threshold():
    # Just above the rebate cliff -- marginal relief should cap tax at the
    # excess over the threshold, not let it jump to the full slab tax.
    result = tax_new(1_300_000)
    assert result.tax_before_cess == 25_000.0
    assert result.total_tax == 26_000.0  # + 4% cess


def test_new_regime_high_income_no_relief():
    result = tax_new(2_000_000)
    assert result.total_tax == 192_400.0
    assert round(result.effective_rate, 2) == 9.62


def test_old_regime_with_deductions():
    result = tax_old(1_000_000, deductions_80c=150_000, deductions_80d=25_000)
    assert result.taxable_income == 775_000
    assert result.total_tax == 70_200.0


def test_compute_wrapper_matches_annualized_new_regime():
    result = compute(monthly_income=95_000, regime="new")
    assert result.annual_income == 1_140_000
    assert result.regime == "new"


def test_zero_income_does_not_crash():
    result = tax_new(0)
    assert result.total_tax == 0.0
    assert result.effective_rate == 0.0
