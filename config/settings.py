"""
config/settings.py

Runtime configuration for ARIA.

Keep filesystem paths in config/paths.py and training hyperparameters in
config/model_config.py.

This file is ONLY for runtime behavior.
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# LLM settings — Groq primary, Gemini automatic fallback (see ai/llm/groq_client.py)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEFAULT_MODEL_NAME = "llama-3.3-70b-versatile"
MODEL_NAME = os.getenv("MODEL_NAME", DEFAULT_MODEL_NAME)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_GEMINI_MODEL_NAME = "gemini-2.0-flash"
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", DEFAULT_GEMINI_MODEL_NAME)


# ===============================
# Helpers
# ===============================
def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ===============================
# App
# ===============================
PROJECT_NAME = os.getenv("PROJECT_NAME", "ARIA_CLEAN")
DEBUG = _bool_env("DEBUG", True)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# ===============================
# Speech Runtime
# ===============================
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_USE_GPU = _bool_env("WHISPER_USE_GPU", True)

TTS_VOICE = os.getenv("TTS_VOICE", "en-IN-NeerjaNeural")
TTS_TIMEOUT_SECONDS = float(os.getenv("TTS_TIMEOUT_SECONDS", "30"))
TTS_RATE = int(os.getenv("TTS_RATE", "165"))

FFMPEG_DIR = os.getenv("FFMPEG_DIR", "")
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "")


# ===============================
# Retrieval Runtime
# ===============================
SBERT_MODEL = os.getenv(
    "SBERT_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
SBERT_DEVICE = os.getenv("SBERT_DEVICE", "cpu")

RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "5"))
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD", "0.45"))


# ===============================
# Database Runtime
# ===============================
DB_URL = os.getenv("DB_URL", "sqlite:///data/user_profiles/aria.db")


# ===============================
# Intent Constants
# ===============================
INTENT_LABELS = [
    "budget_plan",
    "sip_advice",
    "emi_compare",
    "tax_plan",
    "expense_forecast",
    "fraud_check",
    "risk_profile",
    "explain_concept",
    "quiz_me",
    "learning_path",
    "market_analysis",
    "stock_query",
    "sector_query",
    "greet",
    "clarify",
    "chitchat",
]

M1_INTENTS = {
    "budget_plan",
    "sip_advice",
    "emi_compare",
    "tax_plan",
    "expense_forecast",
    "fraud_check",
    "risk_profile",
}

M2_INTENTS = {"explain_concept", "quiz_me", "learning_path"}

M3_INTENTS = {"market_analysis", "stock_query", "sector_query"}

SHARED_INTENTS = {"greet", "clarify", "chitchat"}


# ===============================
# Tutor Runtime
# ===============================
RISK_LABELS = ["Conservative", "Moderate", "Aggressive"]
N_CONCEPTS = int(os.getenv("N_CONCEPTS", "50"))


# ===============================
# Teaching Actions (DQN)
# ===============================
TEACHING_ACTIONS = [
    "simplify_level_down",
    "give_example",
    "ask_quiz",
    "increase_level",
    "use_analogy",
    "teach_prerequisite",
]
