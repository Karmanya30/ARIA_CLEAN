"""ai/llm/audio_script.py's deterministic word-cap backstop -- the prompt
(get_audio_script_prompt) asks for 2-3 sentences, but LLM instruction-
following on exact length isn't reliable. This is the actual failure mode
that let the voice pipeline read full paragraph answers aloud (see
tests/test_api_avatar.py::test_long_response_is_shortened_before_being_spoken
for the end-to-end version through the Tavus route)."""
from ai.llm.audio_script import _MAX_WORDS, _enforce_word_cap, clean_for_tts, generate_audio_script


def test_short_text_passes_through_unchanged():
    text = "SIP stands for Systematic Investment Plan."
    assert _enforce_word_cap(text) == text


def test_long_text_is_truncated_to_a_sentence_boundary():
    text = "First sentence here is short. Second sentence adds more detail than needed. " * 10
    result = _enforce_word_cap(text)
    words = result.split()
    # Capped near _MAX_WORDS, plus a handful more for the appended closing
    # phrase -- not unbounded like the input.
    assert len(words) <= _MAX_WORDS + 10
    assert result.endswith("Check the chat for the full details.")


def test_truncation_does_not_cut_off_mid_sentence():
    text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa. " * 5
    result = _enforce_word_cap(text)
    # Everything before the appended closing phrase must end with real
    # sentence-ending punctuation, not a bare truncated word.
    before_closing = result.rsplit("Check the chat", 1)[0].strip()
    assert before_closing.endswith((".", "!", "?"))


def test_generate_audio_script_returns_friendly_message_on_backend_error(monkeypatch):
    import ai.llm.audio_script as audio_script

    monkeypatch.setattr(audio_script, "generate_audio", lambda prompt: "Error: backend down")
    result = generate_audio_script("some detailed narration")
    assert "went wrong" in result.lower()


def test_generate_audio_script_handles_empty_input():
    assert "couldn't generate" in generate_audio_script("").lower()
    assert "couldn't generate" in generate_audio_script("   ").lower()


def test_clean_for_tts_collapses_whitespace_and_adds_pauses():
    assert clean_for_tts("Hello.  World.\nAgain.") == "Hello... World... Again."
