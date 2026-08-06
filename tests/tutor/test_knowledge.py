"""DKT mastery tracker. Skipped if not yet trained -- run
`python -m scripts.generate_kt_sequences` then
`python -m modules.tutor.train.train_lstm_kt` first."""
import pytest

from modules.tutor.knowledge import is_trained, mastery_vector

pytestmark = pytest.mark.skipif(
    not is_trained(),
    reason="DKT model not trained; run python -m modules.tutor.train.train_lstm_kt",
)


def test_cold_start_is_zero():
    mastery = mastery_vector([])
    assert all(v == 0.0 for v in mastery.values())


def test_mastery_rises_with_repeated_correct_answers():
    history = [{"concept_id": "compound_interest", "is_correct": True} for _ in range(5)]
    mastery = mastery_vector(history)
    assert mastery["compound_interest"] > 0.5


def test_mastery_stays_low_with_wrong_answers():
    history = [{"concept_id": "sharpe_ratio", "is_correct": False} for _ in range(4)]
    mastery = mastery_vector(history)
    assert mastery["sharpe_ratio"] < 0.5
