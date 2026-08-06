"""XGBoost risk profiler. Skipped if not yet trained -- run
`python -m modules.finance.train.train_xgb_risk` first (after
`python -m scripts.generate_synthetic_transactions`)."""
import pytest

from modules.finance import risk_model
from modules.finance.schemas import RISK_LABELS

pytestmark = pytest.mark.skipif(
    not risk_model.is_trained(),
    reason="XGBoost risk model not trained; run python -m modules.finance.train.train_xgb_risk",
)


def test_predict_returns_a_valid_label_and_confidence():
    result = risk_model.predict(
        monthly_income=95_000, age=28, dependents=0, existing_emi=8_500,
        city_tier=1, transactions=[],
    )
    assert result.label in RISK_LABELS
    assert 0.0 <= result.confidence <= 1.0


def test_zero_income_does_not_crash():
    result = risk_model.predict(
        monthly_income=0, age=30, dependents=0, existing_emi=0,
        city_tier=1, transactions=[],
    )
    assert result.label in RISK_LABELS
