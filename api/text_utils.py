"""Small text-formatting helpers shared across API routes."""
from __future__ import annotations

import re


def speech_text(text: str) -> str:
    """Convert Markdown-ish assistant output into text that sounds natural
    when spoken by TTS (strip code fences, links, headings, bullets, bold
    markers, etc.)."""
    cleaned = str(text or "")
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
