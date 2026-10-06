"""Turn a written module answer (labelled sections, bullets, tables) into what a person would say aloud on a call.

Shared by every voice mode: the Live Avatar streams this rewrite sentence by sentence, Tavus gets it as one piece.
"""
from __future__ import annotations

import re

SPOKEN_SYSTEM = (
    "You are ARIA, speaking out loud on a live video call. Turn the written answer you are given into what you would "
    "actually say: warm, plain spoken English, short sentences, no markdown, lists, labels such as Insight or Analysis, "
    "emojis or symbols. Say numbers the way they are said and use rupees. Keep every important number, name and caveat. "
    "This is the middle of a conversation: never greet or say hello, go straight to the answer. "
    "Stay under 90 words, then offer to go deeper if there is more."
)
_LABELS = re.compile(r"(?m)^\s*(?:[*\-\u2022]|\d+[.)]|#+|(?:Insight|Analysis|Recommendation|Risk|Sources?):)")


def needs_rewrite(written: str) -> bool:
    """A short, plain answer is spoken as it is; anything long or laid out for reading is rewritten for the ear."""
    return len(written.split()) > 60 or bool(_LABELS.search(written))


def spoken_prompt(question: str, written: str) -> str:
    return f"The user asked: {question}\n\nWritten answer:\n{written}"


def spoken_version(question: str, written: str) -> str:
    """The whole rewrite in one call (Tavus). Falls back to the written answer if the model is unavailable."""
    if not needs_rewrite(written):
        return written
    from ai.llm.groq_client import generate_response

    out = generate_response(spoken_prompt(question, written), system_prompt=SPOKEN_SYSTEM)
    return written if not out or out.startswith("Error") else out
