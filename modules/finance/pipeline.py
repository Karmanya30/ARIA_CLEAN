"""Finance pipeline: context + prompt + Groq response."""

import json
import re
from typing import Any

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import finance_prompt
from modules.finance import orchestrator as m1_orchestrator
from modules.finance.schemas import Transaction, UserFinancialInput
from shared import user_store
from shared.ner import extract_entities

# Query terms that signal the user wants a *personalized* number (risk
# profile, budget, "how much can I invest") rather than a general concept
# explanation. Gates the income-clarification short-circuit below so it
# never intercepts concept questions ("what is SIP") that don't need income.
_PERSONALIZATION_SIGNALS = (
    "risk profile", "my risk", "budget", "afford", "how much should i invest",
    "how much can i invest", "plan my", "save for", "emergency fund",
    "how much should i save", "financial plan", "how much can i save",
)


def _needs_income_clarification(query: str) -> bool:
    text = query.lower()
    return any(signal in text for signal in _PERSONALIZATION_SIGNALS)


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
    # \d[\d,]* (not just \d+) -- Conversational Mode's follow-up query
    # rewrite runs through the LLM, which formats amounts with thousands
    # separators ("₹60,000"); the old digits-only pattern matched just
    # "60" and stopped at the comma, silently truncating a real income by
    # 1000x. Found live: "what is diversification" as a follow-up after
    # stating a real income produced an "EMI (₹5) ... income (₹60)"
    # budget-infeasible error from figures that had been quietly divided
    # by 1000. Commas are stripped below before the float conversion.
    pattern = r"(\d[\d,]*(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|crore|cr|k|thousand)?\b"
    search_area = text.lower()

    if keyword:
        # \b around the keyword so "emi" doesn't match inside "premium" and
        # "earn" doesn't match inside "learn" -- found via code review: both
        # produced real false-positive extractions that silently overwrote
        # a user's saved profile with garbage.
        keyword_match = re.search(
            rf"\b{keyword}\b[^0-9]{{0,40}}{pattern}|{pattern}[^a-z0-9]{{0,40}}\b{keyword}\b",
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

    value = float(number_match.group(1).replace(",", ""))
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
    text_lower = text.lower()
    match = re.search(r"\b(\d{2})\s*(?:years?\s*old|yo|y/o)\b", text_lower)
    if match:
        return int(match.group(1))
    # Also catch bare "I am 45" / "I'm 45" / "age 45" / "age: 45" -- the
    # "years old" pattern alone missed these, silently defaulting age to 30
    # for anyone who just states their age plainly.
    match = re.search(r"\b(?:i\s*am|i'm|my\s*age\s*is|age\s*(?:is|:)?)\s*(\d{2})\b", text_lower)
    return int(match.group(1)) if match else None


def _load_transactions(user_id: str) -> list[Transaction]:
    """Real transactions entered via the Profile tab (shared/user_store.py),
    if any. Without this, the LSTM spend forecaster and Isolation Forest
    anomaly detector always see an empty list and both explicitly degrade to
    zero-signal output (forecast_model.py, anomaly.py) — real trained models
    with nothing real to run on in the live chat pipeline."""
    rows = user_store.get_transactions(user_id)
    return [Transaction(**row) for row in rows]


def _try_build_financial_profile(query: str, user_id: str) -> UserFinancialInput | None:
    """Parse structured financial fields (income, EMI, age) out of free text,
    merging with any profile already saved for this session so a follow-up
    turn doesn't need to repeat every number. Returns None if there's no
    income anywhere — the caller falls back to the freeform heuristics."""
    saved = user_store.get_financial_profile(user_id) or {}

    # `is None`, not `or` -- an explicit "I earn 0" must not be discarded in
    # favor of the "income" keyword parse (0.0 is falsy but real).
    monthly_income = _parse_indian_amount(query, "earn")
    if monthly_income is None:
        monthly_income = _parse_indian_amount(query, "income")
    existing_emi = _parse_indian_amount(query, "emi")
    age = _extract_age(query)

    # `is not None`, not truthy -- an explicit "I earn 0 now, lost my job"
    # must overwrite a stale saved income instead of silently keeping the
    # old value (0 is falsy but a real, meaningful update).
    income = monthly_income if monthly_income is not None else saved.get("monthly_income")
    if income is None:
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
    return UserFinancialInput(user_id=user_id, transactions=_load_transactions(user_id), **profile)


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
            risk_top_features=json.dumps(m1_response.risk.top_features),
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

    # Deterministic clarifying question -- fires only when the query signals
    # a personalized ask (risk profile / budget / "how much can I afford")
    # with no income known yet. Avoids both an unhelpful generic-LLM guess
    # and a full multi-turn elicitation flow -- one targeted question,
    # answerable in the user's next message, no LLM call spent on it.
    if _needs_income_clarification(query):
        return {
            "domain": "finance",
            "query": query,
            "context": build_context(query),
            "response": (
                "Insight: I can build a personalized risk profile, budget, and SIP plan, "
                "but I need a starting number first.\n"
                "Analysis: Tell me your monthly income (optionally your age, any EMI, and "
                "city tier too) and I'll compute this from real numbers, not a generic guess.\n"
                'Recommendation: Try something like "I earn 60000 a month with an EMI of 8000" '
                "and ask again.\n"
                "Risk: Without income, any budget or SIP number here would be generic, not "
                "actually computed for you."
            ),
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
