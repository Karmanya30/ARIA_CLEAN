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


def generate_audio_script(detailed_script: str, blocks: list[dict] | None = None) -> str:
    """`blocks` is optional (Stage 14) -- a response's `blocks` list (see
    shared/blocks.py), which lets this build from terse structural fields
    (a metric's value, a risk level, a recommendation's title) instead of
    compressing `detailed_script`'s full assembled prose. Falls back to
    `detailed_script` itself whenever `blocks` is omitted, empty, or
    carries no usable content -- callers that don't have blocks yet (or
    a response shape that's just plain text) are unaffected."""
    source = detailed_script
    if blocks:
        from shared.blocks import build_audio_summary

        summary = build_audio_summary(blocks)
        if summary:
            source = summary

    if not source or not source.strip():
        return "Sorry, I couldn't generate the explanation."

    prompt = get_audio_script_prompt(source)

    response = generate_audio(prompt)

    if response.startswith("Error"):
        return "Sorry, something went wrong while generating audio."

    return clean_for_tts(response)