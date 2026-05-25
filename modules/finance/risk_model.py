"""Mock risk helpers; no ML model is used."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskPrediction:
    score: float = 0.5
    label: str = "medium"
    confidence: float = 0.75
    top_features: list[tuple[str, float]] = field(
        default_factory=lambda: [("income_stability", 0.4), ("emi_ratio", 0.3)]
    )


def predict(data: Any) -> RiskPrediction:
    income = float(getattr(data, "monthly_income", 0) or 0)
    emi = float(getattr(data, "existing_emi", 0) or 0)
    ratio = emi / income if income else 0

    if ratio > 0.4:
        return RiskPrediction(score=0.7, label="high", confidence=0.72)
    if ratio < 0.2:
        return RiskPrediction(score=0.3, label="low", confidence=0.72)
    return RiskPrediction()


class RiskModel:
    def predict(self, data: Any) -> dict[str, Any]:
        result = predict(data)
        return {"score": result.score, "label": result.label}
