"""
ai/llm/groq_client.py

Groq API client replacement for the local LLaMA client.

Implements a minimal, backwards-compatible LLM surface focused on the
single required function `generate_response(prompt: str, system_prompt: str|None) -> str`.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Iterator

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# ── CONFIG ─────────────────────────────────────────────────────────────
DEFAULT_MODEL_NAME = "llama-3.3-70b-versatile"
MODEL_NAME = os.environ.get("MODEL_NAME", DEFAULT_MODEL_NAME)


# ── HELPERS ────────────────────────────────────────────────────────────
def normalize_currency(text: str) -> str:
    """Convert dollar references to INR-style for consistency."""
    normalized = str(text or "")
    normalized = re.sub(r"\bUSD\s*([0-9][0-9,]*(?:\.\d+)?)", r"₹\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", r"₹\1", normalized)
    normalized = re.sub(r"\bUS dollars?\b", "rupees", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdollars?\b", "rupees", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bcents?\b", "paise", normalized, flags=re.IGNORECASE)
    return normalized


def _make_client():
    try:
        import groq
    except Exception as e:
        raise RuntimeError(
            "groq SDK not installed. Run: python -m pip install groq"
        ) from e

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    return groq.Groq(api_key=api_key)


# ── CORE GENERATION ────────────────────────────────────────────────────
def generate_response(prompt: str, system_prompt: str | None = None) -> str:
    """
    Generate a response using Groq API.
    Safe wrapper — never crashes, always returns string.
    """
    try:
        client = _make_client()

        if system_prompt is None:
            system_prompt = "You are a helpful AI assistant."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,         
            temperature=0.6,         
            top_p=0.9,              
        )

        # Extract safely
        try:
            text = response.choices[0].message.content
        except Exception:
            try:
                text = response["choices"][0]["message"]["content"]
            except Exception:
                text = str(response)

        text = normalize_currency(text).strip()

        # Ensure clean ending (no abrupt cut)
        if not text.endswith((".", "!", "?")):
            text += "."

        return text

    except Exception as e:
        return f"Error: {str(e)}"


# ── WRAPPERS ───────────────────────────────────────────────────────────
def generate(
    prompt: str,
    *,
    system_prompt: str | None = None,
) -> str:
    """Compatibility wrapper."""
    return generate_response(prompt, system_prompt=system_prompt)


def generate_audio(prompt: str) -> str:
    """
    Specialized generator for speech-friendly output.
    """
    return generate_response(
        prompt,
        system_prompt="You are a friendly teacher explaining concepts in a natural, conversational spoken way.",
    )


# ── STREAMING ──────────────────────────────────────────────────────────
def generate_stream(
    prompt: str,
    *,
    system_prompt: str | None = None,
) -> Iterator[str]:
    try:
        client = _make_client()

        if system_prompt is None:
            system_prompt = "You are a helpful AI assistant."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            stream = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                stream=True,
            )

            for event in stream:
                try:
                    chunk = getattr(event, "choices", None)
                    if chunk:
                        delta = getattr(chunk[0], "delta", None)
                        if delta and hasattr(delta, "get"):
                            text = delta.get("content")
                        else:
                            text = getattr(chunk[0], "text", None)
                        if text:
                            yield text
                            continue
                except Exception:
                    pass

                try:
                    if isinstance(event, dict):
                        choices = event.get("choices")
                        if choices:
                            delta = choices[0].get("delta") or choices[0].get("message")
                            if isinstance(delta, dict):
                                text = delta.get("content")
                                if text:
                                    yield text
                except Exception:
                    pass

        except TypeError:
            # fallback
            yield generate_response(prompt, system_prompt=system_prompt)

    except Exception as e:
        yield f"Error: {str(e)}"


# ── UTILITIES ──────────────────────────────────────────────────────────
def health() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", ""))


def unload() -> None:
    return None


def warmup() -> None:
    try:
        generate_response("Hello")
    except Exception:
        pass