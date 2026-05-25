"""Mock spend forecast helpers; no ML model is used."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpendForecast:
    categories: dict[str, float] = field(default_factory=dict)

    def total_next_month(self) -> float:
        return sum(self.categories.values())


def predict(data: Any) -> SpendForecast:
    income = float(getattr(data, "monthly_income", 50000) or 50000)
    return SpendForecast(
        categories={
            "housing": income * 0.25,
            "food": income * 0.12,
            "utilities": income * 0.06,
            "transport": income * 0.05,
        }
    )


class ForecastModel:
    def predict(self, data: Any) -> dict[str, Any]:
        forecast = predict(data)
        return {"forecast": forecast.categories, "total": forecast.total_next_month()}
