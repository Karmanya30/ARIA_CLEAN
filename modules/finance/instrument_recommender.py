"""
modules/finance/instrument_recommender.py

Deterministic, rule-based scorer ranking investment instrument *types*
(Direct Equity, Index Fund, ETF, ELSS, FD, PPF, NPS) against a user's real
computed risk profile, stated horizon, tax regime, and emergency-fund
status -- never an LLM guess. Same discipline as budget_optimize.py's LP:
compute the real answer in code, let the LLM only narrate it.

Deliberately category-level, never brand/scheme names -- see
ai/llm/prompt_templates.py's INSTRUMENT_RECOMMENDATION_NARRATION for the
line this enforces downstream.

Catalog is sourced from data/raw/concepts_kb/concepts.json (the same KB
Module 2's tutor uses) so instrument facts have one source of truth rather
than a second hardcoded copy -- see scripts/build_concept_kb.py's ingestion
and the "is_recommendable_instrument"/"risk_level"/etc. fields added there
for Stage 12.
"""
from __future__ import annotations

import json
from functools import lru_cache

from config.paths import CONCEPTS_KB_FILE
from modules.finance.schemas import InstrumentRecommendation

# Maps XGBoost's 3-class risk label onto the same 1-8 scale
# concepts_kb.json's risk_level uses (ai/llm/prompt_templates.py's
# TAXAL_LEVEL_HINTS keys) -- lets instrument fit be scored as a simple
# distance rather than a lookup table per (risk_label, instrument) pair.
_RISK_LABEL_TO_SCALE = {"Conservative": 2, "Moderate": 5, "Aggressive": 8}

_STRONG_FIT_THRESHOLD = 70.0
_CONSIDER_THRESHOLD = 40.0

# Below this, an instrument's typical lock-in/volatility profile is
# considered a liquidity risk if the emergency fund isn't built yet.
_EMERGENCY_FUND_MONTHS_TARGET = 6.0


@lru_cache(maxsize=1)
def _load_catalog() -> list[dict]:
    concepts = json.loads(CONCEPTS_KB_FILE.read_text(encoding="utf-8"))
    return [c for c in concepts if c.get("is_recommendable_instrument")]


def _is_illiquid(instrument: dict) -> bool:
    lock_in = instrument.get("lock_in_years")
    return bool(lock_in) and lock_in > 0


def _score_instrument(
    instrument: dict,
    risk_label: str,
    horizon_years: float | None,
    tax_regime: str,
    emergency_fund_months: float,
) -> InstrumentRecommendation:
    reasons_for: list[str] = []
    reasons_against: list[str] = []

    risk_scale = _RISK_LABEL_TO_SCALE.get(risk_label, _RISK_LABEL_TO_SCALE["Moderate"])
    instrument_risk = instrument["risk_level"]
    score = 100.0 - abs(risk_scale - instrument_risk) * 8.0

    if abs(risk_scale - instrument_risk) <= 1:
        reasons_for.append(f"Its typical risk level matches your {risk_label.lower()} risk profile well.")
    elif instrument_risk - risk_scale >= 3:
        reasons_against.append(
            f"It's typically more volatile/higher-risk than fits a {risk_label.lower()} profile."
        )
    elif risk_scale - instrument_risk >= 3:
        reasons_against.append(
            f"It's typically more conservative than your {risk_label.lower()} risk tolerance calls for -- fine as a stabilizer, not your main growth engine."
        )

    min_horizon = instrument.get("min_horizon_years")
    if horizon_years is not None and min_horizon:
        if horizon_years < min_horizon:
            score -= 30.0
            reasons_against.append(
                f"Your {horizon_years:.0f}-year horizon is shorter than the ~{min_horizon:.0f} years this instrument "
                "typically needs, given its lock-in and/or volatility."
            )
        else:
            score += 10.0
            reasons_for.append(
                f"Your {horizon_years:.0f}-year horizon comfortably covers its typical ~{min_horizon:.0f}-year minimum."
            )

    if emergency_fund_months < _EMERGENCY_FUND_MONTHS_TARGET and _is_illiquid(instrument):
        score -= 25.0
        reasons_against.append(
            "You don't have a full emergency fund yet (aim for 6 months of expenses) -- locking money away now "
            "could leave you short if something urgent comes up."
        )
    elif emergency_fund_months >= _EMERGENCY_FUND_MONTHS_TARGET and not _is_illiquid(instrument):
        reasons_for.append("Your emergency fund is already solid, and this instrument stays liquid too.")

    tax_treatment = instrument.get("tax_treatment", "")
    mentions_80c = "80c" in tax_treatment.lower() or "80ccd" in tax_treatment.lower()
    if mentions_80c:
        if tax_regime == "old":
            score += 15.0
            reasons_for.append("Under your old tax regime, this qualifies for a Section 80C-family deduction.")
        else:
            score -= 10.0
            reasons_against.append(
                "You're on the new tax regime, so this instrument's main tax-saving benefit doesn't apply to you."
            )

    score = max(0.0, min(100.0, score))
    if score >= _STRONG_FIT_THRESHOLD:
        fit = "strong_fit"
    elif score >= _CONSIDER_THRESHOLD:
        fit = "consider"
    else:
        fit = "not_a_fit"

    return InstrumentRecommendation(
        instrument_id=instrument["id"],
        instrument_name=instrument["canonical_name"],
        score=round(score, 1),
        fit=fit,
        reasons_for=reasons_for,
        reasons_against=reasons_against,
    )


def recommend(
    risk_label: str,
    horizon_years: float | None = None,
    tax_regime: str = "new",
    emergency_fund_months: float = 0.0,
) -> list[InstrumentRecommendation]:
    """Ranked list of instrument-type recommendations, highest score
    first. Deterministic -- same inputs always produce the same ranking
    and reasons, no LLM call involved."""
    catalog = _load_catalog()
    ranked = [
        _score_instrument(instrument, risk_label, horizon_years, tax_regime, emergency_fund_months)
        for instrument in catalog
    ]
    ranked.sort(key=lambda rec: rec.score, reverse=True)
    return ranked
