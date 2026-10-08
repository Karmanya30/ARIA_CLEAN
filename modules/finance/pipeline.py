"""Finance pipeline: context + prompt + Groq response."""

import copy
import json
import re
from typing import Any

from loguru import logger
from pydantic import ValidationError

from ai.llm.groq_client import FALLBACK_GROQ_MODEL, generate_response
from ai.llm.prompt_templates import ENGINE_NARRATION, FACT_EXTRACTION, finance_prompt
from core.session import get_session
from modules.finance import anomaly, engine, spending
from modules.finance import orchestrator as m1_orchestrator
from modules.finance.schemas import Assets, Expenses, FinanceProfile, Transaction, UserFinancialInput
from shared import user_store
from shared import human_state
from shared.human_state import soften
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


_AMOUNT = r"(\d[\d,]*(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|crores?|cr|k|l|thousand)?\b"


def _scale(match: "re.Match[str]") -> float:
    value = float(match.group(1).replace(",", ""))
    unit_text = match.group(0)
    if "crore" in unit_text or "cr" in unit_text:
        return value * 10_000_000
    if "lpa" in unit_text or "lakh" in unit_text or "lakhs" in unit_text or "lac" in unit_text or "lacs" in unit_text or unit_text.strip().endswith("l"):
        return value * 100_000
    if "thousand" in unit_text or unit_text.strip().endswith("k"):
        return value * 1_000
    return value


def _amounts(text: str) -> list[float]:
    """Every amount in the text (₹ shorthand understood), in order."""
    return [_scale(m) for m in re.finditer(_AMOUNT, text.lower())]


def _parse_indian_amount(text: str, keyword: str | None = None) -> float | None:
    # \d[\d,]* (not just \d+) -- Conversational Mode's follow-up query
    # rewrite runs through the LLM, which formats amounts with thousands
    # separators ("₹60,000"); the old digits-only pattern matched just
    # "60" and stopped at the comma, silently truncating a real income by
    # 1000x. Found live: "what is diversification" as a follow-up after
    # stating a real income produced an "EMI (₹5) ... income (₹60)"
    # budget-infeasible error from figures that had been quietly divided
    # by 1000. Commas are stripped below before the float conversion.
    pattern = _AMOUNT
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

    return _scale(number_match)


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


def build_context(query: str) -> dict[str, Any]:
    return {
        "entities": extract_entities(query),
        "question_count": len(split_questions(query)),
        "questions": split_questions(query),
        "risk_note": "Discuss uncertainty and avoid guaranteed returns.",
        "recommendation_note": "Provide practical next steps based only on the query.",
    }


def _regex_facts(query: str) -> dict[str, Any]:
    """Offline fallback fact extraction: income, EMI and age stated in plain words."""
    # `is None`, not `or` -- an explicit "I earn 0" must not be discarded in
    # favor of the "income" keyword parse (0.0 is falsy but real).
    monthly_income = _parse_indian_amount(query, "earn")
    if monthly_income is None:
        monthly_income = _parse_indian_amount(query, "income")

    # The financial models consume monthly income. Conversational queries
    # often state annual compensation explicitly, so normalize that value
    # before saving it as the user's monthly profile income.
    query_lower = query.lower()
    annual_income = bool(
        re.search(r"\b(?:a|per)\s+(?:year|annum)\b|\bannual(?:ly)?\b|\byearly\b", query_lower)
        or re.search(r"\blpa\b", query_lower)
    )
    monthly_wording = bool(re.search(r"\b(?:a|per)\s+month\b|\bmonthly\b", query_lower))
    if monthly_income is not None and annual_income and not monthly_wording:
        monthly_income /= 12
    facts = {"monthly_income": monthly_income, "existing_emi": _parse_indian_amount(query, "emi"), "age": _extract_age(query)}
    return {k: v for k, v in facts.items() if v is not None}


# ── remembering facts the user states ────────────────────────────────────
_LABELS = {"assets.mf": "mutual funds", "assets.fd": "FD", "monthly_income": "monthly income", "existing_emi": "EMI", "term_cover": "term cover", "health_cover": "health cover",
           "credit_card_outstanding": "credit card dues", "used_80c": "80C used", "used_80d": "80D used"}
_PLAIN = {"age", "dependents", "horizon_years", "city_tier"}  # numbers shown as-is, not as rupees
_SELL = re.compile(r"\b(sell|exit|redeem|withdraw|stop|pause|switch|book profit|bech|nikaal|nikal)\b")
_HOLDING = re.compile(r"\b(mutual funds?|mfs?|stocks?|shares|sips?|fds?|fixed deposits?|investments?|portfolio|funds?)\b")
_WEIGHING = re.compile(r"\b(should (?:i|we)|shall i|thinking (?:of|about)|want to|planning to|kya|du|dun|doon|karu)\b")
_FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|ive|my|me|we|our)\b")
_FACT_WORDS = re.compile(r"\b(salary|earn|income|rent|emi|loan|fd|ppf|epf|nps|cover|insurance|married|single|kids?|children|wife|husband|goal|live in|stay in|mutual funds?|cash|savings|stocks|spend)\b|\b(?:i am|i'm)\s*\d{2}\b")
# questions / what-ifs / purchase asks describe a plan, not a fact about the user
_HYPOTHETICAL = re.compile(r"\b(can i|could i|should i|would i|will i|what if|if i|how (?:much|can|do|should)|afford|buy|purchase|reduce|cut|increase|raise|decrease|lower|start a? ?sip)\b")


_QUESTION = re.compile(r"\?|\b(can|should|what|how|which|why|will|would|could|tell|explain)\b")


def finance_statement(query: str) -> bool:
    """A first-person statement of personal-finance facts ("I earn 1.2 lakh and my rent is 25000"), not a question."""
    t = query.lower()
    return bool(_FIRST_PERSON.search(t) and _FACT_WORDS.search(t) and not _QUESTION.search(t) and not _HYPOTHETICAL.search(t))


def _flat(facts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in facts.items():
        if isinstance(value, dict):
            out.update({f"{key}.{sub}": v for sub, v in value.items()})
        else:
            out[key] = value
    return out


def _nest(flat: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in flat.items():
        key, _, sub = path.partition(".")
        if sub:
            out.setdefault(key, {})[sub] = value
        else:
            out[key] = value
    return out


def _stored(saved: dict[str, Any], path: str) -> Any:
    key, _, sub = path.partition(".")
    return (saved.get(key) or {}).get(sub) if sub else saved.get(key)


def _show(path: str, value: Any) -> str:
    if path == "loans":
        return f"EMI {engine.inr(sum(l.get('emi', 0) for l in value))}"
    if path == "goals":
        return ", ".join(g["name"] for g in value)
    if isinstance(value, (int, float)) and path not in _PLAIN:
        return engine.inr(value)
    return str(value)


def _label(path: str) -> str:
    return _LABELS.get(path, path.split(".")[-1].replace("_", " "))


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 0.5
    return a == b


def _nums(value: Any, key: str = ""):
    if isinstance(value, bool) or key == "priority":
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _nums(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _nums(v)


def _llm_facts(query: str) -> dict[str, Any]:
    """One cheap LLM call turns first-person statements into validated profile facts. Anything that is not
    clearly stated is dropped: every number must appear in the message (or be its /12 or x12)."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n", query) if s.strip() and not _HYPOTHETICAL.search(s.lower())]
    text = " ".join(sentences)
    low = text.lower()
    if not (_FIRST_PERSON.search(low) and (re.search(r"\d", low) or _FACT_WORDS.search(low))):
        return {}
    try:
        raw = generate_response(FACT_EXTRACTION.format(message=text), system_prompt="You extract facts. Output ONLY JSON.",
                                groq_model=FALLBACK_GROQ_MODEL)
        items = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])["facts"]
        assert isinstance(items, list)
    except Exception as exc:
        logger.debug(f"fact extraction skipped: {type(exc).__name__}")  # never log the user's words or amounts
        return {}
    amounts = _amounts(text)
    flat: dict[str, Any] = {}
    for item in items:
        try:
            path, value = item["field"], item["value"]
            key, _, sub = path.partition(".")
            if key not in FinanceProfile.model_fields or value is None or (sub and (key not in ("expenses", "assets") or sub not in Expenses.model_fields | Assets.model_fields)):
                continue
            if any(not any(abs(n - a * m) <= max(1.0, 0.005 * a * m) for a in amounts for m in (1, 1 / 12, 12)) for n in _nums(value)):
                continue  # a number the user never said
            if item.get("period") == "year" and isinstance(value, (int, float)) and (key == "monthly_income" or sub):
                value = value / 12
            flat[path] = FinanceProfile(**_nest({path: value})).model_dump(exclude_none=True)[key]
            if sub:
                flat[path] = flat[path][sub]
        except Exception:
            continue
    return flat


def _apply_facts(uid: str, sid: str, flat: dict[str, Any]) -> list[str]:
    """Save facts that are new; for a value that differs from what is stored, ask before overwriting."""
    valid = {}
    for path, value in flat.items():
        try:
            FinanceProfile(**_nest({path: value}))
            valid[path] = value
        except ValidationError:
            pass
    saved = user_store.get_financial_profile(uid) or {}
    new = {p: v for p, v in valid.items() if _stored(saved, p) is None}
    diff = {p: v for p, v in valid.items() if _stored(saved, p) is not None and not _same(_stored(saved, p), v)}
    notes = []
    if new:
        user_store.save_financial_profile(uid, **_nest(new))
        notes.append("Noted: " + ", ".join(f"{_label(p)} {_show(p, v)}" for p, v in new.items()) + " (edit in Profile → What ARIA remembers).")
    if diff:
        path = next(iter(diff))
        get_session(sid)["finance_pending"] = {"field": path, "query": None, "confirm": _nest(diff)}
        notes.append(f"Update {_label(path)} from {_show(path, _stored(saved, path))} to {_show(path, diff[path])}? Say yes to confirm.")
    return notes


def _remember(query: str, uid: str, sid: str, stated: dict | None = None) -> list[str]:
    flat = {**_regex_facts(query), **_llm_facts(query)}
    if stated is not None:
        stated.update(flat)  # the caller overlays these on the saved profile for this answer
    return _apply_facts(uid, sid, flat)


def _try_build_financial_profile(query: str, user_id: str, sid: str | None = None) -> UserFinancialInput | None:
    """Parse structured financial fields (income, EMI, age) out of free text,
    merging with any profile already saved for this owner so a follow-up
    turn doesn't need to repeat every number. Returns None if there's no
    income anywhere — the caller falls back to the freeform heuristics.
    Only what the user actually said is saved; defaults live in memory."""
    saved = user_store.get_financial_profile(user_id) or {}
    stated = _regex_facts(query)
    # a stated value (even 0) wins for this turn; saving it still goes through the confirm-before-overwrite check
    income = stated.get("monthly_income", saved.get("monthly_income"))
    if income is None:
        return None
    _apply_facts(user_id, sid or user_id, stated)
    profile = {
        "monthly_income": income,
        "age": stated.get("age") or saved.get("age") or 30,
        "dependents": saved.get("dependents") or 0,
        "existing_emi": stated.get("existing_emi", engine.total_emi(saved) or 0.0),
        "emergency_fund_months": engine.snapshot(saved)["emergency_months"] or 0.0,
        "city_tier": saved.get("city_tier") or 1,
        "tax_regime": saved.get("tax_regime") or "new",
    }
    return UserFinancialInput(user_id=user_id, transactions=_load_transactions(user_id), **profile)


# ── intent tools (deterministic engine, no XGBoost/LSTM) ─────────────────
_ASK = {  # field -> (question, how a bare reply becomes facts); None = no numeric reply expected
    "monthly_income": ("What is your monthly take-home income?", lambda v: {"monthly_income": v}),
    "expenses": ("Roughly how much do you spend per month in total?", lambda v: {"expenses": {"other": v}}),
    "loans": ("Do you pay any EMIs? Give the total monthly EMI, or say none.", lambda v: {"loans": [{"kind": "other", "emi": v}] if v else []}),
    "cash": ("About how much do you hold in savings or FDs?", lambda v: {"assets": {"cash": v}}),
    "age": ("How old are you?", lambda v: {"age": int(v)}),
    "risk_tolerance": ("Would you call your investing style conservative, moderate or aggressive?", lambda v: {"risk_tolerance": v}),
    "expenses_reset": ("Roughly how much do you spend per month now?", lambda v: {"expenses": {**{k: None for k in Expenses.model_fields}, "other": v}}),
    "goals": ("Which goal are you saving for, how much, and in how many years? Add it in Profile, or tell me like 'goal: 50 lakh in 10 years'.", None),
}
_NEEDS = {"afford": ["monthly_income", "expenses", "loans", "cash"], "afford_sip": ["monthly_income", "expenses"], "sip_capacity": ["monthly_income", "expenses"],
          "what_if": ["monthly_income", "expenses"], "retirement": ["age", "expenses", "monthly_income", "risk_tolerance"],
          "goal": ["goals"], "tax": ["monthly_income"], "health": ["monthly_income"]}
_USED = {"sip_capacity": ["income", "expenses", "emi", "surplus", "emergency"], "afford": ["income", "emi", "liquid", "emergency"], "afford_sip": ["income", "expenses", "surplus"],
         "what_if": ["income", "expenses", "surplus"], "retirement": ["age", "expenses", "risk"], "goal": ["income", "surplus"],
         "tax": ["income"], "health": ["income", "expenses", "emi", "emergency"]}
_WHAT_IF_TARGET = (("expenses.entertainment", r"entertainment|subscription|dining|movies"), ("expenses.food", r"food|grocer"),
                   ("expenses.rent", r"\brent\b"), ("expenses.transport", r"transport|commute|fuel|petrol"),
                   ("expenses.utilities", r"utilit|bills"), ("expenses.health", r"medical"), ("expenses.education", r"school|tuition"),
                   ("monthly_income", r"income|salary|pay\b"), ("expenses.other", r"spend|expense"))


def _ask_spec(field: str):
    if field.startswith("expenses."):
        cat = field.split(".", 1)[1]
        return (f"Roughly how much do you spend on {cat} per month?", lambda v: {"expenses": {cat: v}})
    return _ASK[field]


def _known(p: dict, field: str) -> bool:
    if field.startswith("expenses."):
        return field.split(".", 1)[1] in (p.get("expenses") or {})
    if field == "expenses":
        return engine.total_expenses(p) is not None  # rent alone is not total spending
    if field == "loans":
        return p.get("loans") is not None or p.get("existing_emi") is not None
    if field == "cash":
        return any(k in (p.get("assets") or {}) for k in ("cash", "fd"))
    return p.get(field) is not None


_SPEND_KINDS = (  # (kind, pattern, needs first person); concept questions ("what is a budget") match none
    ("unusual", r"\b(unusual|suspicious|odd|strange|weird|fraud\w*)\b.*\b(transactions?|charges?|payments?|spend\w*)", False),
    ("top", r"\b(top|biggest|largest|highest)\b.*\b(expenses?|merchants?|spend\w*|payments?|purchases)", False),
    ("trend", r"\bmonthly (spend\w*|expenses?)|\bspending (trend|by month)|month[- ]by[- ]month", False),
    ("recurring", r"\bsubscriptions?\b|\brecurring (payments?|charges?|expenses?|bills?)", True),
    ("cut", r"\b(cut|save|saving|reduce|trim|lower)\b.*\b(spend\w*|expenses?|costs?)\b|\bwhere (can|could|do) (i|we) (cut|save|reduce)", True),
    ("analyse", r"\b(analy[sz]e|summari[sz]e|break ?down|overview|review)\b.*\b(spend\w*|expenses?|transactions?)", True),
    ("spent", r"\bhow much\b.*\b(spen[dt]|spending)\b|\b(spen[dt]|spending)\b.*\b(on|at)\b", True),
)


def _spending_kind(t: str) -> str | None:
    fp = bool(_FIRST_PERSON.search(t))
    return next((k for k, pat, need in _SPEND_KINDS if (fp or not need) and re.search(pat, t)), None)


_AMT = r"(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?\s*(?:lakhs?|lacs?|crores?|cr|k|l|thousand)?)(?!\s*(?:years?|yrs?|y)\b)"


def _sip_amount(t: str) -> float | None:
    m = (re.search(rf"\bsips?\s+(?:of|for|worth)?\s*{_AMT}", t) or re.search(rf"{_AMT}\s*(?:(?:a|per|/)\s*month|monthly)?\s*(?:monthly\s+)?sips?\b", t)
         or re.search(rf"\binvest\w*\s+{_AMT}[^.?,]{{0,24}}\bsips?\b", t))
    return (_amounts(m.group(1)) or [None])[0] if m else None


def finance_intent(query: str) -> tuple[str, dict] | None:
    t = query.lower()
    if kind := _spending_kind(t):
        if not (_amounts(t) and (kind == "cut" or re.search(r"\bwhat if\b", t))):  # "cut my food spending by 5000" stays a what-if
            return "spending", {"kind": kind, "text": t}
    if _SELL.search(t) and _HOLDING.search(t) and _WEIGHING.search(t):  # "should I sell my funds?" is coaching, never a plan builder
        return "decision", {}
    if not _FIRST_PERSON.search(t):  # "what is a SIP" is a concept question; personal tools need "I/my/me"
        return None
    nums = _amounts(t)
    years = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", t)
    if nums and (re.search(r"\bwhat if\b", t) or re.search(r"\b(reduce|cut|increase|raise|decrease|lower)\b", t)):
        for path, pat in _WHAT_IF_TARGET:
            if re.search(pat, t):
                sign = -1 if re.search(r"reduce|cut|decrease|lower|drop|less|fall", t) else 1
                return "what_if", {"changes": {path: sign * nums[0]}}
    if re.search(r"\b(start|begin|do|invest|put|should|can|how much)\b.*\bsips?\b|\bsip of\b|\d\s*(?:k|l)?\s*(?:monthly )?sip\b", t):
        amount = _sip_amount(t)  # only a number tied to the SIP words; income/EMI figures are never the SIP
        return ("afford_sip", {"amount": amount}) if amount else ("sip_capacity", {})
    if nums and re.search(r"\b(afford|buy|buying|purchase)\b|\b(take|get)\b.*\bloan\b", t):
        kind = "car" if re.search(r"\b(car|bike|scooter|vehicle)\b", t) else "home" if re.search(r"\b(house|home|flat|apartment|property)\b", t) else "personal"
        return "afford", {"price": max(nums), "kind": kind}
    if re.search(r"\bretire|\bfire\b|financial independence", t):
        return "retirement", {}
    if re.search(r"\bregime\b|old vs new|new vs old|old or new", t):
        return "tax", {}
    if re.search(r"\bgoals?\b", t):
        return "goal", {"goal": {"name": "your goal", "target": nums[0], "years": float(years.group(1))} if nums and years else None}
    if re.search(r"health score|financial health|net ?worth|\bmy score\b|savings rate", t) and not re.search(r"credit score|cibil", t):
        return "health", {}
    return None


def _parse_reply(field: str, text: str) -> Any:
    if field == "risk_tolerance":
        m = re.search(r"conservative|moderate|aggressive", text)
        return m.group(0).capitalize() if m else None
    if field == "loans" and re.match(r"\s*(no|none|nil|nothing|zero|nope)\b", text):
        return 0.0
    return _parse_indian_amount(text)


def _ask(query: str, sid: str, field: str, p: dict, question: str | None = None) -> dict[str, Any]:
    question, saver = (question, _ask_spec(field)[1]) if question else _ask_spec(field)
    have = [t for t in (f"income {engine.inr(p['monthly_income'])}" if field != "monthly_income" and p.get("monthly_income") is not None else None,
                        f"EMI {engine.inr(engine.total_emi(p))}" if engine.total_emi(p) is not None and field != "loans" else None,
                        f"age {p['age']}" if p.get("age") is not None and field != "age" else None) if t]
    if have and not question.startswith("Using"):
        question = f"I have your {', '.join(have)}. {question}"
    if saver:
        get_session(sid)["finance_pending"] = {"field": field, "query": query}
    return {"domain": "finance", "query": query, "response": question, "missing_field": field, "ui_action": "open_profile"}


_INTENT_WORDS = re.compile(r"\b(is|do|does|sips?|buy|afford|retire\w*|goals?|invest\w*|tax|car|house|home|plan|budget|risk)\b")


def _followup(query: str, uid: str, sid: str, pend: dict) -> dict[str, Any] | None:
    """The reply to a question we asked (a missing fact, or 'update X?'). None = it was something else."""
    session, text = get_session(sid), query.strip().lower()
    session.pop("finance_pending", None)
    if pend.get("confirm"):
        if re.match(r"(yes|yeah|yep|y|ok|okay|sure|confirm|correct|please do)\b", text):
            user_store.save_financial_profile(uid, **pend["confirm"])
            return {"domain": "finance", "query": query, "response": f"Updated {_label(pend['field'])}."}
        if re.match(r"(no|nope|nah|keep)\b", text):
            return {"domain": "finance", "query": query, "response": "Okay, I will keep what I have."}
        return None
    if _QUESTION.search(text) or _INTENT_WORDS.search(text) or len(text.split()) > 5:  # a new question, not the answer
        return None
    value = _parse_reply(pend["field"], text)
    saver = _ask_spec(pend["field"])[1] if pend["field"] in _ASK or pend["field"].startswith("expenses.") else None
    if value is None or saver is None:
        return None
    user_store.save_financial_profile(uid, **saver(value))
    if not pend.get("query"):  # the answer to a "Next: ..." question after stated facts: note it and ask the next one
        return _acknowledge(query, uid, [f"Noted: {_label(pend['field'])} {_inr(value) if isinstance(value, (int, float)) else value}."], sid)
    return run_pipeline(pend["query"], user_id=sid)


def _inr(x: Any) -> str:
    return engine.inr(x)


def _template(tool: str, r: Any) -> str:
    """Deterministic answer from the engine numbers, used when the LLM is unavailable."""
    if tool in ("afford", "afford_sip"):
        n = r["numbers"]
        head = (f"a loan of {_inr(n['loan'])} would mean an EMI of about {_inr(n['emi'])}" if tool == "afford"
                else f"a SIP of {_inr(n['amount'])}/month would grow to about {_inr(n['future_value'])} in {n['years']} years at {n['rate_pct']:.0f}%")
        return (f"Insight: Verdict: {r['verdict']}; {head}.\nAnalysis: " + "; ".join(r["reasons"]) + ".\n"
                "Recommendation: Keep EMIs under 40% of income and 6+ months of emergency cover before committing.\n"
                "Risk: Projections are estimates, not guarantees.")
    if tool == "sip_capacity":
        t = r["tiers"]
        lines = ", ".join(f"{x['name']} {_inr(x['amount'])}/month (about {_inr(x['future_value_10y'])} in 10y, {_inr(x['future_value_20y'])} in 20y)" for x in t)
        fund = (f" First build your emergency fund: you are about {r['emergency_shortfall_months']} months short (roughly {_inr(r['emergency_shortfall_amount'])})."
                if r["first_build_emergency_fund"] else "")
        return (f"Insight: Your monthly surplus is {_inr(r['surplus'])}; a SIP of {lines}.\nAnalysis: Tiers are 30/50/70% of surplus at {r['rate_pct']:.0f}% a year, and {r['buffer_rule']}.{fund}\n"
                "Recommendation: Start with the conservative or balanced tier and step up as income grows.\nRisk: Returns are not guaranteed.")
    if tool == "what_if":
        b, a = r["before"], r["after"]
        return (f"Insight: Your monthly surplus would change by {_inr(r['monthly_surplus_change'])} (health score {r['score_before']} to {r['score_after']}).\n"
                f"Analysis: Surplus goes from {_inr(b['monthly_surplus'] or 0)} to {_inr(a['monthly_surplus'] or 0)}; invested for {r['years']} years that is about {_inr(r['sip_future_value'])}.\n"
                "Recommendation: Put the freed-up money into a SIP so it compounds.\nRisk: Market returns are not guaranteed.")
    if tool == "retirement":
        return (f"Insight: You would need about {_inr(r['corpus'])} by age {r['retirement_age']} ({r['assumptions']}).\n"
                f"Analysis: Your investments could grow to {_inr(r['current_investments_fv'])}, leaving a gap of {_inr(r['gap'])}.\n"
                f"Recommendation: A SIP of about {_inr(r['sip_needed'])}/month closes the gap.\nRisk: Inflation and returns can differ from these assumptions.")
    if tool == "goal":
        lines = "; ".join(f"{g['name']}: {_inr(g['future_target'])} needed in {g['years']:g} years, SIP {_inr(g['sip_needed'])}/month" for g in r)
        return f"Insight: {lines}.\nAnalysis: Targets are inflated at 6% a year (8% for education).\nRecommendation: Start the SIPs in priority order.\nRisk: Returns are not guaranteed."
    if tool == "tax":
        return (f"Insight: The {r['better']} regime is cheaper by {_inr(r['saving'])} a year (new {_inr(r['new_tax'])} vs old {_inr(r['old_tax'])}).\n"
                "Analysis: Old-regime tax assumes your 80C/80D usage on file.\nRecommendation: Choose the cheaper regime at filing.\nRisk: Tax rules change every Budget.")
    h, s = r["health"], r["snapshot"]
    weak = min((b for b in h["breakdown"] if b["sub"] is not None), key=lambda b: b["sub"], default=None)
    prov = f" (provisional: only {h.get('coverage', 1):.0%} of the factors could be measured)" if h.get("coverage", 1) < 0.6 else ""
    return (f"Insight: Your financial health score is {h['score']}/100{prov}.\n"
            f"Analysis: Net worth {_inr(s['net_worth']) if s['net_worth'] is not None else 'unknown'}, monthly surplus {_inr(s['monthly_surplus']) if s['monthly_surplus'] is not None else 'unknown'}"
            + (f"; weakest area: {weak['name']} ({weak['reason']})." if weak else ".") +
            "\nRecommendation: Fill in the unknown areas in Profile for a sharper score.\nRisk: The score is a guide, not advice.")



def _run_spending(query: str, uid: str, kind: str, text: str) -> dict[str, Any]:
    txns = user_store.get_transactions(uid)
    if not txns:
        return {"domain": "finance", "query": query, "missing_field": "transactions", "ui_action": "open_profile",
                "response": "I don't have any transactions yet. Upload a bank statement (PDF, Excel or CSV) in Profile -> Your Transactions and I can answer this"}
    args = spending.parse_spend_query(text, txns) if kind == "spent" else {}
    res = spending.chat_result(kind, args, txns, user_store.get_financial_profile(uid), user_store.get_transactions(uid, kind="income"))
    reply = generate_response(ENGINE_NARRATION.format(query=query, result=json.dumps(res, default=str)))
    if not reply or reply.lower().startswith("error"):
        reply = soften(spending.chat_template(res))
    return {"domain": "finance", "query": query, "response": reply, "intent": f"spending_{kind}", "engine": res,
            "data_basis": spending.basis(txns)}


def _decision_template(r: dict, prose: bool) -> str:
    goal = (f"Your {r['goals'][0]['name']} is {r['goals'][0]['years']:g} years away, so what matters is that date more than the last few months."
            if r.get("goals") else "I don't have your goal or time horizon yet, and that is what should decide this.")
    em = " Your emergency cover is below 6 months, so keep that money safe first." if "emergency fund below 6 months" in r["flags"] else ""
    when = "Selling can make sense if the goal date is near, you need the money for an emergency, or the fund itself has changed, not just because recent returns are weak."
    if prose:
        return f"There is no action needed today. {goal}{em} {when} {r['ask']}"
    return (f"Insight: {goal}\nAnalysis: {when}{em}\nRecommendation: Pause before acting and check your holdings against your goal date. {r['ask']}\n"
            "Risk: ARIA does not know your actual returns, so this is a way to think, not a verdict.")


def _run_decision(query: str, uid: str) -> dict[str, Any]:
    """Sell/stop/switch questions: a slow-down, never a verdict. Facts come only from the stored profile."""
    p = user_store.get_financial_profile(uid) or {}
    snap, a = engine.snapshot(p), p.get("assets") or {}
    tot = sum(v for v in a.values() if v)
    share = lambda keys: round(100 * sum(a.get(k) or 0 for k in keys) / tot) if tot else None
    goals = [{"name": g["name"], "years": g["years"]} for g in p.get("goals") or []]
    em = snap["emergency_months"]
    res = {"goals": goals, "horizon_years": p.get("horizon_years"), "risk_tolerance": p.get("risk_tolerance"), "emergency_months": em,
           "equity_share_pct": share(("stocks", "mf")), "debt_share_pct": share(("fd", "ppf", "epf")), "cash_share_pct": share(("cash",)),
           "monthly_surplus": snap["monthly_surplus"], "foir": snap["foir"]}
    res = {k: v for k, v in res.items() if v not in (None, [])}
    yrs = min((g["years"] for g in goals), default=p.get("horizon_years"))
    res["flags"] = ([f"goal is {yrs:g} years away"] if yrs else []) + (["emergency fund below 6 months"] if em is not None and em < 6 else []) + ["portfolio performance is not on file (ARIA does not know the actual returns)"]
    res["ask"] = ("Roughly how far down is it since you bought?" if goals else "What is this money for, and when will you need it?")
    prose = bool((plan := human_state.current_plan()) and plan["format"] == "prose")
    rules = ("Do NOT recommend selling or holding. Slow the user down, anchor on their own goal and horizon, say what would justify selling "
             "(goal date near, emergency need, fundamentals changed, not just recent returns), then ask the one question in 'ask'. Use only figures in this result."
             + (" No section labels; plain short paragraphs; say no action is needed today." if prose else ""))
    reply = generate_response(ENGINE_NARRATION.format(query=query, result=json.dumps({**res, "instructions": rules}, default=str)))
    if not reply or reply.lower().startswith("error"):
        reply = _decision_template(res, prose)
    out = {"domain": "finance", "query": query, "response": reply, "intent": "decision", "engine": res}
    if p:
        out["profile_basis"] = engine.basis_line(p, ["income", "emergency"])
    else:
        out["ui_action"] = "open_profile"
    return out


def _overlay(p: dict, stated: dict[str, Any]) -> dict:
    """The saved profile with the figures stated in this message laid over it (a scenario for this answer)."""
    q = copy.deepcopy(p)
    for path, value in stated.items():
        key, _, sub = path.partition(".")
        if sub:
            q.setdefault(key, {})[sub] = value
        else:
            q[key] = value
    if "existing_emi" in stated:
        q.pop("loans", None)  # a stated total EMI supersedes a saved loan list
    return q


def _run_tool(query: str, uid: str, sid: str, tool: str, args: dict, stated: dict | None = None) -> dict[str, Any]:
    if tool == "decision":
        return _run_decision(query, uid)
    if tool == "spending":
        return _run_spending(query, uid, args["kind"], args["text"])
    saved = user_store.get_financial_profile(uid) or {}
    p, stated = _overlay(saved, stated or {}), stated or {}
    diffs = {k: v for k, v in stated.items() if _stored(saved, k) is not None and not _same(_stored(saved, k), v)}
    using = ""
    if diffs:
        using = ("Using the " + " and ".join(f"{_show(k, v)} {_label(k)}" for k, v in diffs.items()) + " you just mentioned (your saved "
                 + ", ".join(f"{_label(k)} is {_show(k, _stored(saved, k))}" for k in diffs) + "; say yes to update it).")
        if not any(k.startswith("expenses") for k in stated) and engine.snapshot(p)["monthly_surplus"] is not None and engine.snapshot(p)["monthly_surplus"] <= 0:
            spend = engine.total_expenses(p)
            return {**_ask(query, sid, "expenses_reset", p, f"{using} Your saved spending of {_inr(spend)} a month would leave {engine.inr(engine.snapshot(p)['monthly_surplus'])} short, so it looks out of date. Roughly how much do you spend per month now?"),
                    "missing_field": "expenses"}
    need = [] if tool == "goal" and args.get("goal") else _NEEDS[tool]
    if tool == "what_if":
        path = next(iter(args["changes"]))
        need = ["monthly_income"] if path == "monthly_income" else ["monthly_income", path if path != "expenses.other" else "expenses"]
    if (miss := next((f for f in need if not _known(p, f)), None)):
        return _ask(query, sid, miss, p)
    if tool == "afford":
        res = engine.afford_purchase(p, args["price"], args["kind"])
    elif tool == "afford_sip":
        res = engine.afford_sip(p, args["amount"])
    elif tool == "sip_capacity":
        res = engine.sip_capacity(p)
    elif tool == "what_if":
        res = engine.what_if(p, args["changes"])
    elif tool == "retirement":
        res = engine.retirement(p)
    elif tool == "goal":
        res = [engine.goal_plan(args["goal"], p)] if args.get("goal") else engine.goals(p)
    elif tool == "tax":
        res = engine.tax_compare(p)
    else:
        res = {"health": engine.health_score(p, len(anomaly.detect_for_user(_load_transactions(uid)))), "snapshot": engine.snapshot(p)}
    reply = generate_response(ENGINE_NARRATION.format(query=query, result=json.dumps(res, default=str)))
    if not reply or reply.lower().startswith("error"):
        reply = soften(_template(tool, res))
    if using:
        reply += "\n\n" + using
    return {"domain": "finance", "query": query, "response": reply, "intent": tool, "engine": res,
            "profile_basis": engine.basis_line(p, _USED[tool])}


def _legacy(query: str, user_id: str, sid: str) -> dict[str, Any]:
    profile = _try_build_financial_profile(query, user_id, sid)
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
    return _freeform(query)


def _acknowledge(query: str, uid: str, notes: list[str], sid: str | None = None) -> dict[str, Any]:
    """Just thank the user for the facts (no lecture), and ask for the one most useful fact still missing."""
    p = user_store.get_financial_profile(uid) or {}
    field = next((f for f in ("monthly_income", "expenses", "loans", "cash", "age") if not _known(p, f)), None)
    nxt = _ask_spec(field)[0] if field else None
    if field and sid and _ask_spec(field)[1]:
        get_session(sid)["finance_pending"] = {"field": field, "query": None}  # so a bare "about 70k" is taken as the answer to this question
    return {"domain": "finance", "query": query, "response": " ".join(notes) + (f"\n\nNext: {nxt[0].lower() + nxt[1:]}" if nxt else "")}


def run_pipeline(query: str, user_id: str = "default") -> dict[str, Any]:
    """
    Finance pipeline entry point (Module 1 — Personal Finance).

    Company-specific queries never reach here: core/orchestrator.py routes
    those to modules.equity_research.pipeline (Module 4) first.

    `user_id` is the chat session; facts are stored under the device-level
    owner (shared.user_store.current_owner) so they outlive the tab.

    Priority order:
    0. The reply to a question we just asked (finance_pending).
    1. Facts the user states are remembered (LLM extraction, regex fallback).
    2. Intent tools (afford / SIP / what-if / retirement / goal / tax / health):
       deterministic engine over the stored profile, one question if a fact is missing.
    3. Income (this turn or saved) -> full Module 1 structured pipeline:
       XGBoost risk, LSTM forecast, Isolation Forest anomalies, LP budget,
       real tax, SIP plan, narrated by the LLM.
    4. Freeform heuristics (SIP planning math, known-concept glossary), then generic LLM.
    """
    uid, sid = user_store.current_owner.get() or user_id, user_id
    if pend := get_session(sid).get("finance_pending"):
        if (out := _followup(query, uid, sid, pend)) is not None:
            return out
    stated: dict[str, Any] = {}
    notes = _remember(query, uid, sid, stated)
    hit = finance_intent(query)
    ack = not hit and notes and finance_statement(query)
    if ack:
        result, notes = _acknowledge(query, uid, notes, sid), []
    else:
        result = _run_tool(query, uid, sid, *hit, stated=stated) if hit else _legacy(query, uid, sid)
    if notes and isinstance(result.get("response"), str):
        result["response"] += "\n\n" + " ".join(notes)
    if "profile_basis" not in result and (p := user_store.get_financial_profile(uid)):
        result["profile_basis"] = engine.basis_line(p, ["income", "expenses", "emi", "emergency"])
    return result


def _freeform(query: str) -> dict[str, Any]:
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
