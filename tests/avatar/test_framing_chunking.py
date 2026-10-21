import numpy as np
import pytest

from avatar_engine import protocol
from avatar_engine.chunking import split_text


def test_video_and_audio_roundtrip():
    v = protocol.unpack(protocol.pack_video(7, 1234, b"\xff\xd8jpeg"))
    assert v == (protocol.VIDEO, 7, 1234, b"\xff\xd8jpeg")
    pcm = np.arange(10, dtype=np.int16).tobytes()
    t, seq, ts, (sr, body) = protocol.unpack(protocol.pack_audio(9, 40, pcm, 22050))
    assert (t, seq, ts, sr, body) == (protocol.AUDIO, 9, 40, 22050, pcm)
    assert protocol.HEADER.size == 9


def test_timestamp_wraps_to_u32():
    assert protocol.unpack(protocol.pack_video(1, 2 ** 32 + 5, b"x"))[2] == 5


def test_sentences_split():
    assert split_text("Hello there. How are you? Fine!") == ["Hello there.", "How are you?", "Fine!"]


def test_first_piece_is_short_and_long_sentences_cut_at_clauses():
    text = "Your portfolio gained two point four percent this quarter, driven mostly by banking and information technology holdings, and I would suggest rebalancing."
    parts = split_text(text, first_max=60, max_len=100)
    assert len(parts[0]) <= 60 and all(len(p) <= 100 for p in parts)
    assert " ".join(parts) == text


def test_no_punctuation_is_cut_at_spaces_and_nothing_lost():
    text = " ".join(["word"] * 80)
    parts = split_text(text, first_max=40, max_len=60)
    assert all(len(p) <= 60 for p in parts) and " ".join(parts) == text


@pytest.mark.parametrize("t", ["", "   ", None])
def test_empty(t):
    assert split_text(t) == []


def test_long_first_clause_is_cut_early_for_a_fast_first_word():
    text = "Your portfolio gained two point four percent this quarter, driven mostly by banking."
    parts = split_text(text)
    assert len(parts[0]) <= 36 and " ".join(parts) == text
