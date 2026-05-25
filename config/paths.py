"""
Central filesystem paths for ARIA.

Import paths from here instead of hardcoding them. Data/model roots can be
overridden with ARIA_DATA_DIR and ARIA_MODEL_DIR in the environment or .env.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _rooted(env_name: str, default: str) -> Path:
    raw = os.getenv(env_name, default)
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = _rooted("ARIA_DATA_DIR", "data")
MODELS_DIR = _rooted("ARIA_MODEL_DIR", "models")
MODEL_DIR = MODELS_DIR  # compatibility alias


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
VECTOR_STORE_DIR = DATA_DIR / "vector_store"
USER_PROFILES_DIR = DATA_DIR / "user_profiles"

TRANSACTIONS_DIR = RAW_DIR / "transactions_synthetic"
KT_SEQUENCES_DIR = RAW_DIR / "kt_sequences"
CONCEPTS_KB_DIR = RAW_DIR / "concepts_kb"
CONCEPTS_KB_FILE = CONCEPTS_KB_DIR / "concepts.json"

RAW_TRANSACTIONS_DIR = TRANSACTIONS_DIR  # compatibility alias
RAW_KT_DIR = KT_SEQUENCES_DIR  # compatibility alias

AVATAR_DIR = DATA_DIR / "avatar"
AVATAR_CACHE_DIR = DATA_DIR / "avatar_cache"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

FINANCE_MODELS_DIR = MODELS_DIR / "finance"
TUTOR_MODELS_DIR = MODELS_DIR / "tutor"
EMBED_MODELS_DIR = MODELS_DIR / "embeddings"
LLM_MODELS_DIR = MODELS_DIR / "llm"

XGB_RISK_PATH = FINANCE_MODELS_DIR / "xgb_risk_profile.json"
LSTM_FORECAST_PATH = FINANCE_MODELS_DIR / "lstm_spend_forecast.pt"
ISO_FOREST_PATH = FINANCE_MODELS_DIR / "isolation_forest.joblib"

DKT_MODEL_PATH = TUTOR_MODELS_DIR / "lstm_kt.pt"
DQN_POLICY_PATH = TUTOR_MODELS_DIR / "dqn_teacher.zip"

SBERT_DIR = EMBED_MODELS_DIR / "sbert"

LLM_MODEL_PATH = None
LLM_PATH = None  # compatibility alias

INTENT_MODEL_DIR = MODELS_DIR / "intent_classifier"
NER_MODEL_DIR = MODELS_DIR / "ner_extractor"

LSTM_SPEND_PATH = LSTM_FORECAST_PATH  # compatibility alias
LSTM_KT_PATH = DKT_MODEL_PATH  # compatibility alias
DQN_TEACHER_PATH = TUTOR_MODELS_DIR / "dqn_teacher"  # stable-baselines path without .zip


# ---------------------------------------------------------------------------
# Avatar and Third-party Tools
# ---------------------------------------------------------------------------

AVATAR_PORTRAIT = AVATAR_DIR / "portrait.png"
WAV2LIP_DIR = ROOT / "thirdparty" / "Wav2Lip"
LIVEPORTRAIT_DIR = ROOT / "thirdparty" / "LivePortrait"


# ---------------------------------------------------------------------------
# Interface and Scripts
# ---------------------------------------------------------------------------

INTERFACE_DIR = ROOT / "interface"
SCRIPTS_DIR = ROOT / "scripts"
TRAIN_SCRIPTS_DIR = SCRIPTS_DIR / "train"
DATA_GEN_DIR = SCRIPTS_DIR / "data_generation"


REQUIRED_DIRS = [
    DATA_DIR,
    RAW_DIR,
    PROCESSED_DIR,
    VECTOR_STORE_DIR,
    USER_PROFILES_DIR,
    TRANSACTIONS_DIR,
    KT_SEQUENCES_DIR,
    CONCEPTS_KB_DIR,
    AVATAR_DIR,
    AVATAR_CACHE_DIR,
    MODELS_DIR,
    FINANCE_MODELS_DIR,
    TUTOR_MODELS_DIR,
    EMBED_MODELS_DIR,
    LLM_MODELS_DIR,
    INTENT_MODEL_DIR,
    NER_MODEL_DIR,
    SCRIPTS_DIR,
    TRAIN_SCRIPTS_DIR,
    DATA_GEN_DIR,
]


def ensure_dirs() -> None:
    """Create required runtime directories."""
    for directory in REQUIRED_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def as_str(path: Path) -> str:
    """Return a path as a string for libraries that do not accept PathLike."""
    return str(path)


ensure_dirs()
