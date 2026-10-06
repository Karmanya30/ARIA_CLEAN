"""
ai/llm/groq_client.py

LLM client with automatic reliability fallback: Groq (primary, fast) falls
back to Google Gemini (secondary, more stable free tier) on any error or
rate limit. Implements a minimal, backwards-compatible LLM surface focused
on the single required function
`generate_response(prompt: str, system_prompt: str|None) -> str`.

Every caller in the codebase only depends on that function's signature, so
the fallback is transparent — no caller needs to change.
"""
from __future__ import annotations

import os
import re
from typing import Iterator

from loguru import logger

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# ── CONFIG ─────────────────────────────────────────────────────────────
# llama-3.3-70b-versatile was retired from Groq's hosted catalog; gpt-oss-120b
# is its current general-purpose replacement (checked live against
# client.models.list() on 2026-08-18).
DEFAULT_MODEL_NAME = "openai/gpt-oss-120b"
MODEL_NAME = os.environ.get("MODEL_NAME", DEFAULT_MODEL_NAME)

# gemini-2.0-flash was retired; Google's own 404 response names
# gemini-3.6-flash as its replacement (checked live 2026-08-18).
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", DEFAULT_GEMINI_MODEL)


# ── HELPERS ────────────────────────────────────────────────────────────
# Exchange-rate talk is *about* the dollar ("the rupee at 83 per dollar", "against the US dollar", "dollar index"): turning
# its dollars into rupees destroys the sentence, so text like that is left exactly as written.
_FX_TALK = re.compile(
    r"(?:\bper|\bagainst|\bversus|\bvs\.?|\bto)\s+(?:the\s+)?(?:US\s+|U\.S\.\s+)?dollars?\b|dollar\s+index|dollar[- ]rupee|"
    r"rupee[- ](?:dollar|vs)|USD\s*/\s*INR|\bUS\s+dollars?\s+(?:at|to|index)\b|\bgreenback\b", re.IGNORECASE)


def normalize_currency(text: str) -> str:
    """Convert dollar references to INR-style for consistency."""
    normalized = str(text or "")
    if _FX_TALK.search(normalized):
        return normalized
    normalized = re.sub(r"\bUSD\s*([0-9][0-9,]*(?:\.\d+)?)", r"₹\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", r"₹\1", normalized)
    normalized = re.sub(r"\bUS dollars?\b", "rupees", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdollars?\b", "rupees", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bcents?\b", "paise", normalized, flags=re.IGNORECASE)
    return normalized


def _make_groq_client():
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


def _extract_groq_text(response) -> str:
    try:
        return response.choices[0].message.content
    except Exception:
        pass
    try:
        return response["choices"][0]["message"]["content"]
    except Exception:
        return str(response)


def _call_groq(prompt: str, system_prompt: str, model: str | None = None) -> str:
    """Raises on any failure — caller decides how to handle it."""
    client = _make_groq_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    response = client.chat.completions.create(
        model=model or MODEL_NAME,
        messages=messages,
        temperature=0.6,
        top_p=0.9,
    )
    text = _extract_groq_text(response)
    if not text:
        raise RuntimeError("Groq returned an empty response")
    return text


def _call_gemini(prompt: str, system_prompt: str, model: str | None = None) -> str:
    """Raises on any failure — caller decides how to handle it.

    Uses the current `google-genai` SDK (`from google import genai`), not the
    deprecated `google-generativeai` package.
    """
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        raise RuntimeError(
            "google-genai SDK not installed. Run: python -m pip install google-genai"
        ) from e

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model or GEMINI_MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text


_BACKENDS = (("groq", _call_groq), ("gemini", _call_gemini))


# ── CORE GENERATION ────────────────────────────────────────────────────
def generate_response(prompt: str, system_prompt: str | None = None, model: str | None = None) -> str:
    """
    Generate a response, trying Groq first and automatically falling back to
    Gemini if Groq errors out or is rate-limited. Safe wrapper — never
    crashes, always returns a string.

    `model` overrides the default MODEL_NAME/GEMINI_MODEL_NAME for this call
    only -- used by shared/domain_guard.py to route its classification calls
    to a smaller/cheaper model than the main narration model, without
    changing behavior for any other caller (default None preserves the
    exact prior behavior).
    """
    if system_prompt is None:
        system_prompt = "You are a helpful AI assistant."
    from shared.news import current_news_block  # set by core.orchestrator for time-sensitive questions

    if news := current_news_block():
        system_prompt = f"{system_prompt}\n\n{news}"

    text: str | None = None
    last_error: Exception | None = None

    for name, backend in _BACKENDS:
        try:
            text = backend(prompt, system_prompt, model)
            break
        except Exception as e:
            last_error = e
            logger.warning(f"LLM backend '{name}' failed, trying next: {e}")
            continue

    if text is None:
        logger.error(f"All LLM backends failed: {last_error}")
        return f"Error: {last_error}"

    text = normalize_currency(text).strip()

    # Ensure clean ending (no abrupt cut)
    if not text.endswith((".", "!", "?")):
        text += "."

    return text


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
    """Streams from Groq when possible; falls back to a single non-streamed
    chunk from generate_response() (which itself carries the Groq->Gemini
    fallback) on any failure."""
    if system_prompt is None:
        system_prompt = "You are a helpful AI assistant."

    try:
        client = _make_groq_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            stream=True,
        )

        yielded = False
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
                        yielded = True
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
                                yielded = True
                                yield text
            except Exception:
                pass

        if not yielded:
            yield generate_response(prompt, system_prompt=system_prompt)

    except Exception as exc:
        logger.warning(f"Groq streaming failed, falling back to non-streaming: {exc}")
        yield generate_response(prompt, system_prompt=system_prompt)


# ── UTILITIES ──────────────────────────────────────────────────────────
def health() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", "") or os.environ.get("GEMINI_API_KEY", ""))


def unload() -> None:
    return None


def warmup() -> None:
    # generate_response() catches its own backend errors and returns an
    # "Error: ..." string rather than raising, so there's nothing to catch
    # here -- this just primes any lazy client setup (e.g. SDK imports).
    generate_response("Hello")
