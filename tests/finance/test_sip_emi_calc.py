"""Closed-form SIP/EMI math -- deterministic, no ML."""
import pytest

from modules.finance.sip_emi_calc import emi, emi_total_interest, sip_future_value, sip_required


def test_sip_future_value_zero_return_is_linear():
    assert sip_future_value(5000, 2, 0.0) == pytest.approx(5000 * 24)


def test_sip_future_value_positive_return_beats_linear():
    fv = sip_future_value(5000, 5, 12.0)
    assert fv > 5000 * 60  # compounding must beat simple sum of contributions


def test_sip_required_is_inverse_of_future_value():
    target = 1_000_000
    monthly = sip_required(target, 10, 10.0)
    fv = sip_future_value(monthly, 10, 10.0)
    assert fv == pytest.approx(target, rel=1e-6)


def test_emi_reduces_to_principal_over_n_at_zero_rate():
    assert emi(120_000, 0.0, 1) == pytest.approx(10_000)


def test_emi_total_interest_positive_for_nonzero_rate():
    assert emi_total_interest(500_000, 8.5, 20) > 0


def test_zero_inputs_return_zero_not_crash():
    assert sip_future_value(0, 5, 10.0) == 0.0
    assert sip_required(0, 5, 10.0) == 0.0
    assert emi(0, 8.5, 20) == 0.0
