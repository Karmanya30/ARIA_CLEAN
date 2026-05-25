"""Quiz utility helpers."""

from typing import Any


def grade(answers: list[Any]) -> dict[str, int]:
    return {"score": len([answer for answer in answers if answer])}
