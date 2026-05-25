"""Static data helpers used by placeholder pipelines."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FinancialProfile:
    user_id: str = "demo"
    monthly_income: float = 75000.0
    existing_emi: float = 15000.0
    age: int = 30
    city_tier: str = "tier_1"
    tax_regime: str = "new"
    emergency_fund: float = 3.0
    transactions: list[dict[str, Any]] = field(default_factory=list)


def load_mock_data(domain: str = "general") -> dict[str, Any]:
    return {
        "domain": domain,
        "source": "mock",
        "items": [],
    }


def load_csv(path: str) -> list[dict[str, Any]]:
    return []
