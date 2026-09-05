"""
shared/blocks.py

Typed structured-output contract for chat responses (Stage 13) --
replaces web/src/components/chat/ResponseCard.tsx's regex parsing of
"Insight:"/"Analysis:"/"Recommendation:"/"Risk:" labels out of raw LLM
text, which force-fit every response (a two-sentence definition and a
five-paragraph breakdown alike) into the same four colored boxes.

Design rule that matters more than the schema itself: structural blocks
(metric/table/breakdown/chart/risk/comparison/mastery) are built directly
in Python from data the pipelines already compute -- M1Response's
risk/budget/sip_plan/tax/forecast/investment_plan, the Stage 11 beginner-
screener lists, Module 2's TAXAL/mastery state. The LLM is never asked to
emit one of these as JSON; it only ever fills a `text`/`explanation`
block's `content`, or a `recommendation`'s `rationale`. Every number a
user sees traces to code, not model output -- strictly safer than the
prose narration of the same numbers this replaces.

Only the block types an actual pipeline emits today are defined here.
The original 52-type spec this is inspired by is NOT built out
speculatively -- add a new block type only when a concrete feature needs
it (see the plan file/PR history for the reasoning).
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    """Free-form prose, rendered as markdown. The default block for
    anything that doesn't have a more specific structural shape -- this is
    what most Module 3/4 narration and Module 1/2's LLM-written
    explanations become."""

    type: Literal["text"] = "text"
    content: str


class MetricBlock(BaseModel):
    """One real computed number -- e.g. the monthly SIP amount, a stock's
    current price, an effective tax rate."""

    type: Literal["metric"] = "metric"
    label: str
    value: str
    unit: str | None = None


class FormulaBlock(BaseModel):
    """Plain ASCII/Unicode notation only (x, /, ^, sqrt) -- deliberately no
    LaTeX. See the plan/PR notes: a KaTeX pipeline is disproportionate
    machinery for one-line finance formulas."""

    type: Literal["formula"] = "formula"
    expression: str
    variables: list[str] = Field(default_factory=list)


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]


class BreakdownBlock(BaseModel):
    """A whole split into named parts with amounts -- e.g. the LP budget
    allocation (housing/food/transport/.../sip)."""

    type: Literal["breakdown"] = "breakdown"
    categories: list[str]
    amounts: list[float]
    percentages: list[float] | None = None


class ChartBlock(BaseModel):
    """Real computed series -- e.g. the LSTM spend forecast with its
    lower/upper confidence band, or an index/sector snapshot."""

    type: Literal["chart"] = "chart"
    chart_type: Literal["line", "bar", "donut"]
    labels: list[str]
    data: list[float]
    series_name: str | None = None
    lower_band: list[float] | None = None
    upper_band: list[float] | None = None


class RiskFactor(BaseModel):
    name: str
    contribution: float


class RiskBlock(BaseModel):
    """The XGBoost risk model's own SHAP top-3 explanation -- real model
    output, not an LLM paraphrase of it (same reasoning
    ShapExplainer.tsx's docstring already gives for showing this
    directly)."""

    type: Literal["risk"] = "risk"
    score: float
    level: str
    factors: list[RiskFactor] = Field(default_factory=list)


class RecommendationBlock(BaseModel):
    """One ranked entry from a deterministic scorer (e.g.
    modules/finance/instrument_recommender.py) -- `rationale` is the only
    LLM-written field here; `title`/`actions` come from the computed
    ranking."""

    type: Literal["recommendation"] = "recommendation"
    title: str
    rationale: str
    actions: list[str] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    name: str
    metrics: dict[str, str]


class ComparisonBlock(BaseModel):
    """A side-by-side list -- e.g. Stage 12's ranked instrument types, or
    Stage 11's beginner-friendly/top-performer stock lists."""

    type: Literal["comparison"] = "comparison"
    title: str
    rows: list[ComparisonRow] = Field(default_factory=list)


class AlertBlock(BaseModel):
    type: Literal["alert"] = "alert"
    severity: Literal["info", "warning", "error"]
    message: str


# ── Tutor (Module 2) ────────────────────────────────────────────────────
class ExplanationBlock(BaseModel):
    """One TAXAL section's worth of prose (Cognitive/Functional/Causal),
    tagged so the frontend can label it distinctly from a generic `text`
    block without re-parsing labels out of a combined string."""

    type: Literal["explanation"] = "explanation"
    label: str  # "Cognitive" | "Functional" | "Causal"
    content: str


class DefinitionBlock(BaseModel):
    type: Literal["definition"] = "definition"
    term: str
    definition: str


class MCQBlock(BaseModel):
    """Field-for-field the same shape modules/tutor/quiz.py's QuizItem
    already produces (correct_answer/wrong_answers kept separate, not
    pre-combined) -- so the frontend's existing QuizWidget.tsx, which
    shuffles and grades from exactly this shape, can be handed this
    block's fields unchanged rather than being rebuilt for a new one."""

    type: Literal["mcq"] = "mcq"
    question: str
    correct_answer: str
    wrong_answers: list[str]
    explanation: str
    concept_id: str


class HintBlock(BaseModel):
    type: Literal["hint"] = "hint"
    level: int = 1
    content: str


class MasteryBlock(BaseModel):
    """Wraps the same shape modules/tutor -- Module 2's mastery vector
    already produces (ProgressItem) -- reuses ProgressTab.tsx's existing
    progress-bar rendering via this block rather than a new component."""

    type: Literal["mastery"] = "mastery"
    topic: str
    concept_id: str
    score: float  # 0.0-1.0


Block = Union[
    TextBlock,
    MetricBlock,
    FormulaBlock,
    TableBlock,
    BreakdownBlock,
    ChartBlock,
    RiskBlock,
    RecommendationBlock,
    ComparisonBlock,
    AlertBlock,
    ExplanationBlock,
    DefinitionBlock,
    MCQBlock,
    HintBlock,
    MasteryBlock,
]


def dump_blocks(blocks: list[BaseModel]) -> list[dict]:
    """Serialize a list of block models for inclusion in a pipeline's
    response dict -- plain dicts, JSON-serializable, `type` field intact
    for the frontend's BlockRenderer to dispatch on."""
    return [block.model_dump() for block in blocks]


def build_audio_summary(blocks: list[dict]) -> str:
    """Compact, spoken-friendly summary built from a response's terse
    structural fields (metric labels/values, risk level, a recommendation's
    title+rationale) rather than a `text` block's full assembled prose.

    Stage 14: ai/llm/audio_script.py's shortening LLM call used to compress
    the entire narration string every time -- this gives it a much smaller,
    already-terse starting point instead, so it lands under the length cap
    more reliably. Falls back to the first `text` block's raw content only
    if no structural block is present at all (e.g. a plain tutor
    explanation or smalltalk reply, which are just a single text block) --
    saying nothing would be worse than the LLM having more to compress.
    """
    parts: list[str] = []
    fallback_text: str | None = None

    for block in blocks:
        block_type = block.get("type")
        if block_type == "metric":
            unit = f" {block['unit']}" if block.get("unit") else ""
            parts.append(f"{block['label']}: {block['value']}{unit}")
        elif block_type == "risk":
            parts.append(f"Risk level: {block['level']} ({round(block['score'] * 100)}% confidence)")
        elif block_type == "recommendation":
            parts.append(f"{block['title']}: {block['rationale']}")
        elif block_type == "alert":
            parts.append(block["message"])
        elif block_type == "text" and fallback_text is None:
            fallback_text = block["content"]

    if parts:
        return " ".join(parts)
    return fallback_text or ""


def text_or_error_blocks(text: str) -> list[dict]:
    """Minimal, uniform block wrapping for any pipeline response path that
    doesn't have richer structured data behind it (a plain LLM narration,
    a deterministic clarifying question, etc.) -- keeps `response["blocks"]`
    present on every return path across all 4 pipelines, not just the ones
    with rich structured data to build from."""
    if text.startswith("Error"):
        return dump_blocks(
            [
                AlertBlock(
                    severity="error",
                    message="ARIA's language model is temporarily unavailable (both Groq and Gemini failed to respond).",
                )
            ]
        )
    return dump_blocks([TextBlock(content=text)])
