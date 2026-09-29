"""
ARIA Domain Intelligence & Query Guard.

Why this module exists: narrowing ARIA's own RAG/training data to finance
content does NOT stop the underlying LLM from answering totally unrelated
questions (cricket scores, coding help, capital cities, ...) -- the model's
own pretrained general knowledge is still there regardless of what ARIA's
knowledge base contains. RAG limitation != LLM limitation. The fix has to
be an explicit domain gate in front of the LLM, not a hope that narrow
retrieval alone will narrow its answers.

Architecture (see core/orchestrator.py for where this plugs in):

    User Query
        |
        v
    Domain Classifier (classify_domain) -- cheap/small model, not the main
        |                                   narration model
        v
    +---------------------+---------------------------+
    | confidently in-scope| confidently OUT of scope   |
    | or ambiguous         | (allowed=False AND         |
    | (confidence < 0.80   |  confidence >= 0.80)       |
    | either way)           |                            |
    +----------+-----------+-------------+---------------+
               |                         |
               v                         v
      existing module routing      polite refusal
      (core/orchestrator.py's       (build_refusal_response) --
      precise equity/market/        the main LLM is never called
      finance/tutor dispatch,       at all for these, saving cost
      unchanged) -- genuinely
      ambiguous queries land in
      that dispatch's own
      "general" fallback, whose
      prompt (ai/llm/prompt_
      templates.py's tutor_prompt)
      already answers while
      pivoting toward a finance/
      business/company/management
      angle instead of hard-
      refusing every borderline
      question.
               |
               v
      Output Guard (validate_output) -- reuses the same classifier on the
      generated answer as a non-blocking safety-net check, attached to the
      response as metadata for transparency/demo purposes rather than
      silently rewriting an already-generated answer.

Fails open by design: if the classifier call errors, times out, or the
model doesn't return parseable JSON (e.g. in tests, where the mocked LLM
returns a canned non-JSON string), classify_domain() returns an
"unavailable" result (`available: False`) and the caller (core/
orchestrator.py) falls through to its pre-existing keyword-based routing
untouched -- this guard only ever *adds* a gate, it never becomes a single
point of failure for the whole app.
"""
from __future__ import annotations

import json
import os
import re
from typing import TypedDict

from loguru import logger

# Deliberately broad, not "finance only" -- a narrower boundary would reject
# perfectly reasonable company/management/strategy/economics questions.
# Flat set of labels the classifier is instructed to choose from.
ALLOWED_DOMAINS = {
    "finance",
    "personal_finance",
    "investment",
    "economics",
    "accounting",
    "company",
    "business",
    "management",
    "strategy",
    "financial_markets",
    "corporate_finance",
    "risk_management",
    "portfolio_management",
    "fintech",
    "real_estate_finance",
    "entrepreneurship",
    "mergers_and_acquisitions",
    "corporate_governance",
    "business_valuation",
    "financial_modelling",
}

CONFIDENCE_THRESHOLD = float(os.environ.get("DOMAIN_GUARD_CONFIDENCE_THRESHOLD", "0.80"))

# Cheaper/smaller than the main narration model (config.settings.MODEL_NAME
# / DEFAULT_MODEL_NAME == "openai/gpt-oss-120b") -- a classification call
# doesn't need that much reasoning weight. Checked live against this
# account's client.models.list() on 2026-08-23; "llama-3.1-8b-instant" (an
# earlier obvious pick) is no longer in the catalog.
DEFAULT_CLASSIFIER_MODEL = "openai/gpt-oss-20b"
CLASSIFIER_MODEL = os.environ.get("DOMAIN_GUARD_MODEL", DEFAULT_CLASSIFIER_MODEL)

# Set DOMAIN_GUARD_ENABLED=false to disable the whole guard (falls back to
# the pre-guard behavior everywhere) without touching code -- useful if the
# extra classification call's latency/cost is unwanted during grading/demo.
ENABLED = os.environ.get("DOMAIN_GUARD_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}

# Set DOMAIN_GUARD_OUTPUT_CHECK=false to skip the post-answer output guard
# specifically (keeps the pre-check) -- it roughly doubles the LLM calls per
# turn, so this is a knob for latency-sensitive demos.
OUTPUT_CHECK_ENABLED = os.environ.get("DOMAIN_GUARD_OUTPUT_CHECK", "true").strip().lower() not in {
    "0", "false", "no", "off",
}

CLASSIFIER_SYSTEM_PROMPT = f"""\
You are ARIA's domain classifier. ARIA is a financial intelligence \
assistant whose in-scope domains are: {", ".join(sorted(ALLOWED_DOMAINS))}, \
and closely adjacent topics (e.g. a named company's business, management, \
or financial performance).

Classify the user's query and respond with ONLY a single JSON object, no \
other text, in exactly this shape:
{{"domain": "<one label from the list above, or \\"non_finance\\" if none fit>", \
"intent": "<short snake_case description of what the user wants>", \
"allowed": <true or false>, "confidence": <0.0-1.0>}}

Rules:
- "allowed" is true only if "domain" is one of ARIA's in-scope domains above.
- A query about a named company (financial performance, strategy, \
management, valuation, M&A) is in-scope even without an explicit finance \
keyword.
- Pure general trivia, coding help, entertainment, sports, weather, or \
politics unrelated to economics/markets/policy are NOT in scope: \
"domain": "non_finance", "allowed": false.
- If you are unsure, lower "confidence" rather than guessing "allowed": true.
- Output ONLY the JSON object. No markdown, no explanation, no code fence.
"""


class DomainClassification(TypedDict):
    domain: str | None
    intent: str | None
    allowed: bool | None
    confidence: float | None
    available: bool  # False = classifier call failed/unparseable -- caller should fail open


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _unavailable() -> DomainClassification:
    return {"domain": None, "intent": None, "allowed": None, "confidence": None, "available": False}


def classify_domain(query: str) -> DomainClassification:
    """Cheap pre-check: is this query in ARIA's finance/business/company/
    management scope? Never raises -- on any failure (disabled, LLM error,
    unparseable output) returns an "unavailable" result so the caller can
    fail open and defer to its own existing routing."""
    if not ENABLED or not query or not query.strip():
        return _unavailable()

    from ai.llm.groq_client import generate_response

    try:
        raw = generate_response(query, system_prompt=CLASSIFIER_SYSTEM_PROMPT, model=CLASSIFIER_MODEL)
    except Exception as exc:
        logger.warning(f"Domain guard classifier call failed: {exc}")
        return _unavailable()

    return _parse_classification(raw)


def _parse_classification(raw: str) -> DomainClassification:
    match = _JSON_RE.search(raw or "")
    if not match:
        return _unavailable()

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _unavailable()

    domain = data.get("domain")
    intent = data.get("intent")
    allowed = data.get("allowed")
    confidence = data.get("confidence")

    if not isinstance(domain, str) or not isinstance(allowed, bool):
        return _unavailable()
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        return _unavailable()

    # Don't just trust the model's own "allowed" flag -- cross-check against
    # our own whitelist too (classifier + explicit domain constraint, not
    # the classifier's self-reported flag alone).
    allowed = allowed and domain in ALLOWED_DOMAINS

    return {
        "domain": domain,
        "intent": intent if isinstance(intent, str) else None,
        "allowed": allowed,
        "confidence": confidence,
        "available": True,
    }


def validate_output(query: str, response_text: str) -> DomainClassification:
    """Output Guard: does the generated answer still look in-scope? Reuses
    the same classifier on a query+answer blob. Non-blocking by design (see
    module docstring) -- callers attach the result as response metadata for
    transparency rather than rewriting or discarding an already-generated
    answer, since a corrective second LLM call to "fix" the text would add
    another full round-trip's cost/latency to every single turn."""
    if not OUTPUT_CHECK_ENABLED:
        return _unavailable()
    snippet = f"User asked: {query}\nAssistant answered: {(response_text or '')[:800]}"
    return classify_domain(snippet)


REFUSAL_TEMPLATE = (
    "I'm ARIA, a financial intelligence assistant — I focus on finance, "
    "investing, economics, accounting, companies, business, and management "
    "topics. That question is outside my scope, so I can't answer it "
    "properly. Ask me something about your finances, a company, the "
    "markets, or a business/finance concept instead!"
)


def build_refusal_response(query: str, classification: DomainClassification) -> dict:
    return {
        "domain": "refused",
        "query": query,
        "response": REFUSAL_TEMPLATE,
        "domain_guard": classification,
    }
