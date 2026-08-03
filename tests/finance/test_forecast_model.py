"""LSTM spend forecaster."""
from modules.finance import forecast_model
from modules.finance.schemas import CATEGORIES


def test_empty_history_returns_zero_forecast_without_loading_the_model():
    # This path must work even before the model is trained -- a brand new
    # user with no transactions shouldn't error out.
    result = forecast_model.predict(monthly_income=50_000, transactions=[])
    assert len(result) == len(CATEGORIES)
    assert all(f.forecast == [0.0, 0.0, 0.0] for f in result)
