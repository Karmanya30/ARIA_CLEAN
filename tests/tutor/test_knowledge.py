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


def test_mastery_is_clearly_lower_with_wrong_answers_than_with_right_ones():
    # Relative, not "< 0.5": the simulated learners the model is trained on get better with every attempt (a practice
    # bonus), so even after several misses the honest next-answer probability sits near 0.5. What matters is that a
    # struggling learner is scored well below a succeeding one on the same concept.
    wrong = mastery_vector([{"concept_id": "sharpe_ratio", "is_correct": False} for _ in range(6)])["sharpe_ratio"]
    right = mastery_vector([{"concept_id": "sharpe_ratio", "is_correct": True} for _ in range(6)])["sharpe_ratio"]
    assert right - wrong > 0.1
