"""Mock anomaly helpers; no ML model is used."""

from dataclasses import dataclass
from typing import Any


@dataclass
class AnomalyFlag:
    label: str
    amount: float
    reason: str


def detect_for_user(transactions: list[dict[str, Any]] | None) -> list[AnomalyFlag]:
    flags: list[AnomalyFlag] = []
    for txn in transactions or []:
        amount = float(txn.get("amount", 0) or 0)
        if amount > 50000:
            flags.append(AnomalyFlag("large_spend", amount, "Transaction is unusually large."))
    return flags


class AnomalyDetector:
    def detect(self, data: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [flag.__dict__ for flag in detect_for_user(data)]
