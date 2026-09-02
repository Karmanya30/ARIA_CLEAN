from .groq_client import generate_audio
from .prompt_templates import get_audio_script_prompt
import re

# The prompt asks for 2-3 sentences, but LLM instruction-following on exact
# length isn't reliable -- this is the literal failure mode that let the
# voice pipeline read full paragraph answers aloud before this cap existed.
# ~40 words is generous headroom over the prompt's target (roughly 15-20s
# spoken) while still guaranteeing a hard ceiling regardless of what the
# model does.
_MAX_WORDS = 40
_FALLBACK_CLOSING_PHRASE = "Check the chat for the full details."


def clean_for_tts(text: str) -> str:
    text = text.strip()

    # remove extra spaces
    text = re.sub(r"\s+", " ", text)

    # add natural pauses
    text = text.replace(". ", "... ")

    return text


def _enforce_word_cap(text: str, max_words: int = _MAX_WORDS) -> str:
    """Deterministic backstop, not just prompt trust -- if the model still
    overruns the requested length, truncate at the last sentence boundary
    within the cap and append a fixed closing phrase, rather than cutting
    off mid-sentence or letting a long answer through unchanged."""
    words = text.split()
    if len(words) <= max_words:
        return text

    truncated = " ".join(words[:max_words])
    last_boundary = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
    if last_boundary > 0:
        truncated = truncated[: last_boundary + 1]
    else:
        # No sentence boundary at all within the cap -- fall back to a
        # hard cut rather than running further past the word limit.
        truncated = truncated.rstrip(",;:") + "."

    return f"{truncated} {_FALLBACK_CLOSING_PHRASE}"


def generate_audio_script(detailed_script: str) -> str:
    if not detailed_script or not detailed_script.strip():
        return "Sorry, I couldn't generate the explanation."

    prompt = get_audio_script_prompt(detailed_script)

    response = generate_audio(prompt)

    if response.startswith("Error"):
        return "Sorry, something went wrong while generating audio."

    return clean_for_tts(_enforce_word_cap(response))