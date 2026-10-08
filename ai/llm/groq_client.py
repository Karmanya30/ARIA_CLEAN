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
import time
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
FALLBACK_GROQ_MODEL = os.environ.get("FALLBACK_GROQ_MODEL", "openai/gpt-oss-20b")
SECOND_FALLBACK_GROQ_MODEL = os.environ.get("SECOND_FALLBACK_GROQ_MODEL", "qwen/qwen3.8-27b")  # its own daily allowance


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
        **({"reasoning_effort": "low"} if "gpt-oss" in (model or MODEL_NAME) else {}),  # fewer hidden reasoning tokens: faster, and kinder to the per-minute token cap
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


_dead: dict[str, float] = {}  # backend name -> monotonic time until which it is skipped (daily token quota exhausted)
_BACKENDS = (("groq", _call_groq), ("gemini", _call_gemini))


# ── CORE GENERATION ────────────────────────────────────────────────────
def generate_response(prompt: str, system_prompt: str | None = None, model: str | None = None, groq_model: str | None = None) -> str:
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
    default = system_prompt is None  # explicit prompts (JSON, classifier, rewrite, agents) never get the tone guide
    if default:
        system_prompt = "You are a helpful AI assistant."
    from shared.human_state import current_plan as current_voice_plan, current_voice_block # set by core.orchestrator.handle_query
    from shared.news import current_news_block  # set by core.orchestrator for time-sensitive questions

    if news := current_news_block():
        system_prompt = f"{system_prompt}\n\n{news}"
    if default and (voice := current_voice_block()):
        if (plan := current_voice_plan()) and plan["format"] == "prose":  # prose wins over a module prompt that demands labels
            system_prompt = f"{voice}\n\n{system_prompt}"
            prompt += "\n\nAnswer as 2-4 short plain paragraphs without section labels."
        else:
            system_prompt = f"{system_prompt}\n\n{voice}"

    text: str | None = None
    last_error: Exception | None = None

    # Each Groq model has its own rate bucket, so a smaller one is a real second chance when the main one is limited; a short
    # pause and one more pass rides out the brief 429/503 spikes that hit when several report calls run at once.
    chain = [(n, (lambda p, s, m, f=f: f(p, s, groq_model or m)) if n == "groq" else f) for n, f in _BACKENDS]  # groq_model: Groq only (each model has its own per-minute token bucket)
    chain.append(("groq-small", lambda p, s, m: _call_groq(p, s, m or FALLBACK_GROQ_MODEL)))
    chain.append(("groq-qwen", lambda p, s, m: _call_groq(p, s, m or SECOND_FALLBACK_GROQ_MODEL)))
    for attempt in range(2):
        for name, backend in chain:
            if _dead.get(name, 0) > time.monotonic():  # its daily quota is spent: do not wait on it again
                continue
            try:
                text = backend(prompt, system_prompt, model)
                break
            except Exception as e:
                last_error = e
                logger.warning(f"LLM backend '{name}' failed, trying next: {e}")
                if "tokens per day" in str(e):
                    _dead[name] = time.monotonic() + 1800  # ponytail: fixed 30 min, parse the "try again in" hint if it matters
        if text is not None or not re.search(r"429|503|rate limit|unavailable|overloaded", str(last_error), re.I):
            break
        wait = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", str(last_error))  # a per-minute cap names its own wait
        time.sleep(min(30.0, int(wait.group(1) or 0) * 60 + float(wait.group(2)) + 0.5) if wait else 2)

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
