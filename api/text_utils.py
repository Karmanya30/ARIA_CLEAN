"""Small text-formatting helpers shared across API routes."""
from __future__ import annotations

import re


_LATEX_WORDS = {r"\times": "×", r"\cdot": "×", r"\div": "÷", r"\approx": "≈", r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
                r"\neq": "≠", r"\pm": "±", r"\%": "%", r"\,": " ", r"\;": " ", r"\!": "", r"\ ": " ", r"\left": "", r"\right": "",
                r"\quad": " ", r"\qquad": " ", r"\rightarrow": "→", r"\to": "→"}
_LATEX_CMD = re.compile(r"\\(?:text|textbf|mathrm|mathbf|frac|sqrt|times|cdot|div|approx|leq?|geq?|neq|pm|left|right|rightarrow|to)\b")


def plain_math(text: str) -> str:
    """A formula as words and plain symbols, for the voice: the screen typesets the LaTeX (web/.../Markdown.tsx), but read aloud
    `\\[ \\text{Cost} = P \\times n \\]` would be 'backslash text'. Text without a LaTeX command is returned untouched."""
    s = str(text or "")
    if not (_LATEX_CMD.search(s) or "$$" in s):
        return s
    s = re.sub(r"\$\$(.+?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\\\[(.+?)\\\]|\\\((.+?)\\\)", lambda m: m.group(1) or m.group(2), s, flags=re.DOTALL)
    s = re.sub(r"\[\s*([^\[\]]*\\(?:text|times|frac|cdot|div|sqrt)[^\[\]]*?)\s*\]", r"\1", s)  # the same wrapper once its backslashes were eaten
    s = re.sub(r"([\^_])\{([^{}]*)\}", lambda m: m.group(1) + (m.group(2) if len(m.group(2)) == 1 else f"({m.group(2)})"), s)  # first: no braces left inside a fraction
    for _ in range(3):  # innermost first, so nested braces resolve
        s = re.sub(r"\\(?:text|textbf|mathrm|mathbf)\{([^{}]*)\}", r"\1", s)
        s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
        s = re.sub(r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)", s)
    for word in sorted(_LATEX_WORDS, key=len, reverse=True):
        s = re.sub(re.escape(word) + (r"\b" if word[-1].isalpha() else ""), _LATEX_WORDS[word], s)
    return re.sub(r"[ \t]{2,}", " ", s)


def speech_text(text: str) -> str:
    """Convert Markdown-ish assistant output into text that sounds natural
    when spoken by TTS (strip code fences, links, headings, bullets, bold
    markers, etc.)."""
    cleaned = plain_math(str(text or "")).replace("$", "")  # answers carry LaTeX for the screen; the voice gets it as plain words (prices are rupees, so $ is only ever math)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"(^|\s)[*_]{1,3}([^*_]+)[*_]{1,3}(:?)", r"\1\2\3", cleaned)
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*(\d+)\.\s+", r"\1. ", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("*", "").replace("_", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
