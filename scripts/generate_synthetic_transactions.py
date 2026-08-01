"""
scripts/generate_synthetic_transactions.py

Generates synthetic Indian household transaction histories for training
Module 1's XGBoost risk classifier and LSTM spend forecaster. Real consumer
transaction data isn't available at BTP scale or legally obtainable, so
this follows standard practice in personal-finance-ML research: persona-
conditioned synthetic data with realistic seasonality (festival spend
spikes), not random noise.

Usage:
    python -m scripts.generate_synthetic_transactions
"""
from __future__ import annotations

import datetime as dt
import random

import numpy as np
import pandas as pd

from config.paths import TRANSACTIONS_DIR
from modules.finance.schemas import CATEGORIES

RANDOM_STATE = 42
N_USERS_PER_PERSONA = 30
N_MONTHS = 15  # 12 months context + 3 months held out for forecast eval

# category ratio-of-income (mean, std) per persona — drives monthly spend
PERSONAS: dict[str, dict] = {
    "young_it_pro": {
        "risk_label": "Aggressive",
        "income_range": (90_000, 160_000),
        "age_range": (24, 30),
        "dependents_range": (0, 0),
        "emi_ratio_range": (0.0, 0.10),
        "city_tier_weights": {1: 0.7, 2: 0.25, 3: 0.05},
        "category_ratio": {
            "housing": (0.28, 0.04), "food": (0.14, 0.03), "transport": (0.06, 0.02),
            "utilities": (0.04, 0.01), "emi": (0.03, 0.03), "entertainment": (0.09, 0.03),
            "medical": (0.02, 0.01), "other": (0.06, 0.02),
        },
    },
    "midcareer_family": {
        "risk_label": "Moderate",
        "income_range": (150_000, 280_000),
        "age_range": (34, 45),
        "dependents_range": (1, 3),
        "emi_ratio_range": (0.25, 0.38),
        "city_tier_weights": {1: 0.5, 2: 0.35, 3: 0.15},
        "category_ratio": {
            "housing": (0.10, 0.03), "food": (0.13, 0.02), "transport": (0.05, 0.01),
            "utilities": (0.05, 0.01), "emi": (0.30, 0.05), "entertainment": (0.04, 0.02),
            "medical": (0.04, 0.02), "other": (0.05, 0.02),
        },
    },
    "early_grad": {
        "risk_label": "Moderate",
        "income_range": (30_000, 65_000),
        "age_range": (22, 26),
        "dependents_range": (0, 0),
        "emi_ratio_range": (0.0, 0.05),
        "city_tier_weights": {1: 0.4, 2: 0.4, 3: 0.2},
        "category_ratio": {
            "housing": (0.32, 0.05), "food": (0.16, 0.03), "transport": (0.07, 0.02),
            "utilities": (0.05, 0.01), "emi": (0.02, 0.02), "entertainment": (0.07, 0.03),
            "medical": (0.02, 0.01), "other": (0.06, 0.02),
        },
    },
    "near_retirement": {
        "risk_label": "Conservative",
        "income_range": (80_000, 180_000),
        "age_range": (52, 60),
        "dependents_range": (0, 2),
        "emi_ratio_range": (0.0, 0.08),
        "city_tier_weights": {1: 0.55, 2: 0.3, 3: 0.15},
        "category_ratio": {
            "housing": (0.06, 0.02), "food": (0.13, 0.02), "transport": (0.04, 0.01),
            "utilities": (0.04, 0.01), "emi": (0.03, 0.03), "entertainment": (0.03, 0.01),
            "medical": (0.06, 0.03), "other": (0.05, 0.02),
        },
    },
    "self_employed": {
        "risk_label": "Moderate",
        "income_range": (60_000, 200_000),
        "income_volatility": 0.30,
        "age_range": (28, 50),
        "dependents_range": (0, 3),
        "emi_ratio_range": (0.10, 0.22),
        "city_tier_weights": {1: 0.4, 2: 0.35, 3: 0.25},
        "category_ratio": {
            "housing": (0.16, 0.04), "food": (0.14, 0.03), "transport": (0.06, 0.02),
            "utilities": (0.04, 0.01), "emi": (0.15, 0.05), "entertainment": (0.05, 0.02),
            "medical": (0.03, 0.02), "other": (0.06, 0.02),
        },
    },
}

# month (1-12) -> multiplier applied to food/entertainment/other spend
FESTIVE_MULTIPLIERS = {10: 1.3, 11: 1.8, 3: 1.2, 12: 1.15}
FESTIVE_CATEGORIES = {"food", "entertainment", "other"}

# roughly how many individual transactions make up one category's monthly total
TXN_COUNT_RANGE = {
    "housing": (1, 1), "emi": (1, 1), "utilities": (2, 4), "food": (14, 26),
    "transport": (6, 14), "entertainment": (2, 6), "medical": (0, 3), "other": (3, 8),
}

CHANNELS = ["upi", "card", "cash", "netbanking"]


def _sample_range(rng: random.Random, low: float, high: float) -> float:
    return low + rng.random() * (high - low)


def _split_monthly_into_transactions(
    rng: random.Random, category: str, total: float, year: int, month: int
) -> list[dict]:
    if total <= 0:
        return []
    lo, hi = TXN_COUNT_RANGE[category]
    n = rng.randint(lo, hi) if hi > 0 else 0
    if n == 0:
        return [{"category": category, "amount": round(total, 2), "day": 1}]

    # Dirichlet split so amounts vary realistically instead of being equal
    weights = np.random.dirichlet(np.ones(n) * 1.5)
    days_in_month = 28 if month == 2 else (30 if month in (4, 6, 9, 11) else 31)
    rows = []
    for w in weights:
        amount = max(10.0, total * w)
        day = rng.randint(1, days_in_month)
        rows.append({"category": category, "amount": round(amount, 2), "day": day})
    return rows


def generate_user(persona_name: str, user_idx: int, rng: random.Random) -> tuple[dict, pd.DataFrame]:
    persona = PERSONAS[persona_name]
    base_income = _sample_range(rng, *persona["income_range"])
    age = rng.randint(*persona["age_range"])
    dependents = rng.randint(*persona["dependents_range"])
    emi_ratio = _sample_range(rng, *persona["emi_ratio_range"])
    city_tier = rng.choices(
        list(persona["city_tier_weights"].keys()),
        weights=list(persona["city_tier_weights"].values()),
    )[0]
    income_volatility = persona.get("income_volatility", 0.05)

    today = dt.date.today().replace(day=1)
    months = [
        (today.year - ((today.month - 1 - m) < 0), ((today.month - 1 - m) % 12) + 1)
        for m in range(N_MONTHS - 1, -1, -1)
    ]

    rows: list[dict] = []
    for year, month in months:
        month_income = max(10_000.0, base_income * (1 + rng.gauss(0, income_volatility)))
        festive_mult = FESTIVE_MULTIPLIERS.get(month, 1.0)

        for category in CATEGORIES:
            mean_ratio, std_ratio = persona["category_ratio"][category]
            if category == "emi":
                cat_ratio = emi_ratio
            else:
                cat_ratio = max(0.0, rng.gauss(mean_ratio, std_ratio))
            monthly_total = month_income * cat_ratio
            if category in FESTIVE_CATEGORIES:
                monthly_total *= festive_mult

            for txn in _split_monthly_into_transactions(rng, category, monthly_total, year, month):
                rows.append(
                    {
                        "date": dt.date(year, month, min(txn["day"], 28)),
                        "category": txn["category"],
                        "amount": txn["amount"],
                        "channel": rng.choice(CHANNELS),
                    }
                )

    # Inject a rare anomalous large transaction for ~8% of users, so
    # fraud_detect.py has something real to catch during evaluation.
    if rng.random() < 0.08 and rows:
        anomaly_month = months[rng.randint(0, len(months) - 1)]
        rows.append(
            {
                "date": dt.date(anomaly_month[0], anomaly_month[1], 15),
                "category": rng.choice(["other", "entertainment", "transport"]),
                "amount": round(base_income * rng.uniform(0.8, 2.5), 2),
                "channel": rng.choice(CHANNELS),
            }
        )

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    meta = {
        "user_id": f"{persona_name}_{user_idx:03d}",
        "persona": persona_name,
        "risk_label": persona["risk_label"],
        "monthly_income": round(base_income, 2),
        "age": age,
        "dependents": dependents,
        "existing_emi": round(base_income * emi_ratio, 2),
        "city_tier": city_tier,
    }
    return meta, df


def main() -> None:
    rng = random.Random(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)
    TRANSACTIONS_DIR.mkdir(parents=True, exist_ok=True)

    metadata_rows = []
    for persona_name in PERSONAS:
        for user_idx in range(N_USERS_PER_PERSONA):
            meta, df = generate_user(persona_name, user_idx, rng)
            out_path = TRANSACTIONS_DIR / f"{meta['user_id']}.parquet"
            df.to_parquet(out_path, index=False)
            metadata_rows.append(meta)

    metadata_df = pd.DataFrame(metadata_rows)
    metadata_df.to_csv(TRANSACTIONS_DIR / "_metadata.csv", index=False)
    print(
        f"Generated {len(metadata_df)} synthetic users "
        f"({N_USERS_PER_PERSONA} per persona x {len(PERSONAS)} personas) "
        f"-> {TRANSACTIONS_DIR}"
    )


if __name__ == "__main__":
    main()
