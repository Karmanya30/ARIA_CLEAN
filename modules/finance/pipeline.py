"""Finance pipeline: context + prompt + Groq response."""

import re
from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import finance_prompt
from modules.finance import orchestrator as m1_orchestrator
from modules.finance.schemas import UserFinancialInput
from shared import user_store
from shared.ner import extract_entities


KNOWN_FINANCE_CONCEPTS = {
    "sip": {
        "name": "SIP",
        "expansion": "Systematic Investment Plan",
        "definition": "a method of investing a fixed amount regularly, usually monthly, into a mutual fund.",
        "example": "For example, investing ₹5,000 every month through SIP builds investments gradually without trying to time the market.",
        "caveat": "SIP returns are market-linked and not guaranteed.",
    },
    "emi": {
        "name": "EMI",
        "expansion": "Equated Monthly Instalment",
        "definition": "a fixed amount paid every month to repay a loan over a set tenure.",
        "example": "For example, a home loan, car loan, or personal loan is commonly repaid through monthly EMIs.",
        "caveat": "Missing EMI payments can lead to penalties and can hurt your credit score.",
    },
    "spi": {
        "name": "SPI",
        "expansion": "ambiguous finance acronym",
        "definition": "not a standard Indian personal-finance term like SIP or EMI; in some contexts it may mean a stock price index or another domain-specific metric.",
        "example": "If you meant SIP, it means Systematic Investment Plan, a regular mutual fund investment method.",
        "caveat": "Because SPI has multiple meanings, the exact expansion depends on the context.",
    },
}


def split_questions(query: str) -> list[str]:
    parts = re.split(r"\s*(?:\?|,|\band\b)\s*(?=(?:what|how|why|when|where|which|explain|tell)\b)", query, flags=re.IGNORECASE)
    questions = [part.strip(" ?,.") for part in parts if part.strip(" ?,.")]
    return questions


def _extract_known_concepts(query: str) -> list[dict[str, str]]:
    text = query.lower()
    concepts = []
    for key, concept in KNOWN_FINANCE_CONCEPTS.items():
        if re.search(rf"\b{re.escape(key)}\b", text):
            concepts.append(concept)
    return concepts


def _build_known_concepts_response(query: str) -> str | None:
    concepts = _extract_known_concepts(query)
    if not concepts:
        return None

    insight_items = [
        f"{concept['name']} stands for {concept['expansion']} and is {concept['definition']}"
        for concept in concepts
    ]
    analysis_items = [concept["example"] for concept in concepts]
    risk_items = [concept["caveat"] for concept in concepts]

    recommendation = (
        "Use SIP for disciplined investing and review EMI affordability before taking a loan."
        if len(concepts) > 1
        else (
            "Use it only after matching it with your income, goals, time horizon, and risk comfort."
            if concepts[0]["name"] == "SIP"
            else "Clarify the exact context before relying on this acronym for a financial decision."
            if concepts[0]["name"] == "SPI"
            else "Keep EMIs within a comfortable share of monthly income and maintain an emergency buffer."
        )
    )

    return (
        f"Insight: {' '.join(insight_items)}\n"
        f"Analysis: {' '.join(analysis_items)}\n"
        f"Recommendation: {recommendation}\n"
        f"Risk: {' '.join(risk_items)}"
    )


def _parse_indian_amount(text: str, keyword: str | None = None) -> float | None:
    pattern = r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|crore|cr|k|thousand)?\b"
    search_area = text.lower()

    if keyword:
        keyword_match = re.search(
            rf"{keyword}[^0-9]{{0,40}}{pattern}|{pattern}[^a-z0-9]{{0,40}}{keyword}",
            search_area,
        )
        if not keyword_match:
            return None
        amount_text = keyword_match.group(0)
        number_match = re.search(pattern, amount_text)
    else:
        number_match = re.search(pattern, search_area)

    if not number_match:
        return None

    value = float(number_match.group(1))
    unit_text = number_match.group(0)
    if "crore" in unit_text or "cr" in unit_text:
        return value * 10_000_000
    if "lpa" in unit_text or "lakh" in unit_text or "lakhs" in unit_text or "lac" in unit_text or "lacs" in unit_text:
        return value * 100_000
    if "thousand" in unit_text or unit_text.strip().endswith("k"):
        return value * 1_000
    return value


def _parse_return_rate(query: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:per annum|pa|p\.a\.|annual|yearly)?", query.lower())
    return float(match.group(1)) if match else None


def _future_value_monthly_sip(monthly_sip: float, annual_return_pct: float, years: int) -> float:
    months = years * 12
    monthly_rate = annual_return_pct / 100 / 12
    if monthly_rate == 0:
        return monthly_sip * months
    return monthly_sip * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate)


def _build_sip_planning_response(query: str) -> str | None:
    text = query.lower()
    if not re.search(r"\bsip\b", text):
        return None

    planning_terms = ("save", "invest", "return", "risk", "suggest", "top", "break down", "breakdown")
    if not any(term in text for term in planning_terms):
        return None

    annual_income = _parse_indian_amount(text, "income")
    annual_saving = (
        _parse_indian_amount(text, "save")
        or _parse_indian_amount(text, "saving")
        or _parse_indian_amount(text, "invest")
    )
    target_return = _parse_return_rate(text)

    if annual_saving is None:
        return None

    monthly_sip = annual_saving / 12
    realistic_return = min(target_return or 12.0, 12.0)
    requested_return_text = f"{target_return:.0f}%" if target_return is not None else "the requested return"
    income_text = f" on annual income of ₹{annual_income:,.0f}" if annual_income else ""

    projections = []
    for years in (1, 3, 5):
        invested = monthly_sip * 12 * years
        target_value = _future_value_monthly_sip(monthly_sip, target_return or realistic_return, years)
        cautious_value = _future_value_monthly_sip(monthly_sip, realistic_return, years)
        projections.append(
            f"{years} year: invest ₹{invested:,.0f}; at {requested_return_text} approx ₹{target_value:,.0f}; "
            f"at a more cautious {realistic_return:.0f}% approx ₹{cautious_value:,.0f}"
        )

    risk_note = (
        f"A {requested_return_text} annual target does not match a lowest-risk SIP profile; it usually needs high equity exposure."
        if target_return and target_return >= 14
        else "The return target should still be treated as market-linked, not guaranteed."
    )

    return (
        f"Insight: To save ₹{annual_saving:,.0f} per year{income_text}, your required SIP is about ₹{monthly_sip:,.0f} per month. {risk_note}\n"
        "Analysis: For lower risk, use a staggered mix instead of putting everything into aggressive equity. "
        "A practical split is 40% large-cap index or large-cap fund, 35% balanced advantage or aggressive hybrid fund, "
        "and 25% short-duration debt or conservative hybrid fund. "
        + " ".join(projections)
        + "\n"
        "Recommendation: For your top 3 SIP buckets, consider: 1. Large-cap index fund for lower-cost equity exposure; "
        "2. Balanced advantage/aggressive hybrid fund to reduce volatility; "
        "3. Short-duration debt or conservative hybrid fund for stability. Review direct plans, expense ratio, rolling returns, downside capture, and fund manager consistency before selecting exact scheme names.\n"
        "Risk: Returns from SIPs are not guaranteed. Chasing 14% with least risk is unrealistic, so either lower the return expectation to around 10-12% or accept higher equity volatility and a longer time horizon."
    )


def _extract_age(text: str) -> int | None:
    match = re.search(r"\b(\d{2})\s*(?:years?\s*old|yo|y/o)\b", text.lower())
    return int(match.group(1)) if match else None


def _try_build_financial_profile(query: str, user_id: str) -> UserFinancialInput | None:
    """Parse structured financial fields (income, EMI, age) out of free text,
    merging with any profile already saved for this session so a follow-up
    turn doesn't need to repeat every number. Returns None if there's no
    income anywhere — the caller falls back to the freeform heuristics."""
    saved = user_store.get_financial_profile(user_id) or {}

    monthly_income = _parse_indian_amount(query, "earn") or _parse_indian_amount(query, "income")
    existing_emi = _parse_indian_amount(query, "emi")
    age = _extract_age(query)

    income = monthly_income or saved.get("monthly_income")
    if not income:
        return None

    profile = {
        "monthly_income": income,
        "age": age or saved.get("age") or 30,
        "dependents": saved.get("dependents") or 0,
        "existing_emi": existing_emi if existing_emi is not None else (saved.get("existing_emi") or 0.0),
        "emergency_fund_months": saved.get("emergency_fund_months") or 0.0,
        "city_tier": saved.get("city_tier") or 1,
        "tax_regime": saved.get("tax_regime") or "new",
    }
    user_store.save_financial_profile(user_id, **profile)
    return UserFinancialInput(user_id=user_id, transactions=[], **profile)


def build_context(query: str) -> dict[str, Any]:
    return {
        "entities": extract_entities(query),
        "question_count": len(split_questions(query)),
        "questions": split_questions(query),
        "risk_note": "Discuss uncertainty and avoid guaranteed returns.",
        "recommendation_note": "Provide practical next steps based only on the query.",
    }


def run_pipeline(query: str, user_id: str = "default") -> dict[str, Any]:
    """
    Finance pipeline entry point (Module 1 — Personal Finance).

    Company-specific queries never reach here: core/orchestrator.py routes
    those to modules.equity_research.pipeline (Module 4) first.

    Priority order:
    1. Income (this turn or a previously saved profile) -> full Module 1
       structured pipeline: XGBoost risk, LSTM forecast, Isolation Forest
       anomalies, LP budget, real tax, SIP plan, narrated by the LLM.
    2. Freeform heuristics (SIP planning math, known-concept glossary).
    3. Generic LLM prompt.
    """
    profile = _try_build_financial_profile(query, user_id)
    if profile is not None:
        m1_response = m1_orchestrator.run(profile)
        user_store.save_financial_profile(
            user_id,
            risk_label=m1_response.risk.label,
            risk_confidence=m1_response.risk.confidence,
        )
        return {
            "domain": "finance",
            "query": query,
            "response": m1_response.natural_language,
            "risk": m1_response.risk.model_dump(),
            "sip_plan": m1_response.sip_plan.model_dump(),
            "budget": m1_response.budget.model_dump(),
            "tax": m1_response.tax.model_dump(),
            "anomalies": [a.model_dump() for a in m1_response.anomalies],
            "forecast": [f.model_dump() for f in m1_response.forecast],
        }

    sip_planning_response = _build_sip_planning_response(query)
    if sip_planning_response:
        return {
            "domain": "finance",
            "query": query,
            "context": build_context(query),
            "response": sip_planning_response,
        }

    known_concepts_response = _build_known_concepts_response(query)
    if known_concepts_response:
        return {
            "domain": "finance",
            "query": query,
            "context": build_context(query),
            "response": known_concepts_response,
        }

    # Generic path: no company detected, use LLM with context
    context = build_context(query)
    prompt = finance_prompt(query, context)
    answer = generate_response(prompt)
    return {
        "domain": "finance",
        "query": query,
        "context": context,
        "response": answer,
    }


def run(query: str, user_id: str = "default", *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_pipeline(query, user_id=user_id)


def build_narration_prompt(query: str, result: dict[str, Any] | None = None) -> str:
    return finance_prompt(query, (result or {}).get("context"))
