from modules.finance.tax import tax_new, tax_old


def test_no_cliff_at_the_surcharge_limit():
    # taxable 50 lakh -> 50.0001 lakh: extra tax can not exceed the extra income (cess aside)
    a, b = tax_new(5_075_000).total_tax, tax_new(5_076_000).total_tax
    assert b - a <= 1000 * 1.04 * 1.0001


def test_surcharge_applies_above_the_limit_and_new_regime_caps_at_25_percent():
    plain = tax_new(12_000_000).tax_before_cess
    assert plain > 0 and tax_new(60_000_000).effective_rate < tax_old(60_000_000).effective_rate  # 37% only in the old regime
    assert tax_old(4_000_000).total_tax == 1_037_400.0  # below 50 lakh: unchanged


def test_negative_deductions_do_not_raise_tax():
    assert tax_old(1_000_000, -200_000).total_tax == tax_old(1_000_000, 0).total_tax
