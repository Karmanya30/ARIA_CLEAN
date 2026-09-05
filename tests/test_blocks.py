"""shared/blocks.py -- the typed block contract itself. Pydantic validation
means a malformed block fails loudly here rather than silently reaching
the frontend as an unrecognized shape."""
import pytest
from pydantic import ValidationError

from shared.blocks import (
    BreakdownBlock,
    ComparisonBlock,
    ComparisonRow,
    MCQBlock,
    MasteryBlock,
    MetricBlock,
    RiskBlock,
    RiskFactor,
    TextBlock,
    dump_blocks,
)


def test_text_block_round_trips_through_dump():
    block = TextBlock(content="hello")
    dumped = dump_blocks([block])[0]
    assert dumped == {"type": "text", "content": "hello"}


def test_metric_block_defaults_unit_to_none():
    block = MetricBlock(label="Monthly SIP", value="12,000")
    assert block.model_dump()["unit"] is None


def test_breakdown_block_requires_matching_shape_fields():
    # categories/amounts don't need to be pre-validated equal length here
    # (callers build both from the same source list), but missing
    # required fields must fail loudly, not silently default.
    with pytest.raises(ValidationError):
        BreakdownBlock(categories=["housing"])  # missing amounts


def test_risk_block_with_factors():
    block = RiskBlock(
        score=0.82,
        level="Moderate",
        factors=[RiskFactor(name="income", contribution=0.3), RiskFactor(name="age", contribution=-0.1)],
    )
    dumped = block.model_dump()
    assert dumped["factors"][0] == {"name": "income", "contribution": 0.3}


def test_comparison_block_with_rows():
    block = ComparisonBlock(
        title="Ranked instruments",
        rows=[ComparisonRow(name="PPF", metrics={"score": "44", "fit": "consider"})],
    )
    dumped = dump_blocks([block])[0]
    assert dumped["rows"][0]["name"] == "PPF"


def test_mcq_block_matches_quiz_item_shape():
    block = MCQBlock(
        question="What is SIP?",
        correct_answer="Systematic Investment Plan",
        wrong_answers=["Stock Index Position", "Simple Interest Plan"],
        explanation="SIP stands for Systematic Investment Plan.",
        concept_id="sip",
    )
    assert block.model_dump()["type"] == "mcq"


def test_mastery_block_score_is_a_plain_float():
    block = MasteryBlock(topic="Diversification", concept_id="diversification", score=0.67)
    assert dump_blocks([block])[0]["score"] == 0.67


def test_dump_blocks_preserves_order():
    blocks = [TextBlock(content="a"), MetricBlock(label="x", value="1")]
    dumped = dump_blocks(blocks)
    assert [d["type"] for d in dumped] == ["text", "metric"]
