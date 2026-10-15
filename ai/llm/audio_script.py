from .groq_client import generate_audio
from .prompt_templates import get_audio_script_prompt
import re


def clean_for_tts(text: str) -> str:
    text = text.strip()

    # remove extra spaces
    text = re.sub(r"\s+", " ", text)

    # add natural pauses
    text = text.replace(". ", "... ")

    return text


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