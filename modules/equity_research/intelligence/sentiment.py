"""Sentence-level financial sentiment with FinBERT.

Model: ProsusAI/FinBERT (github.com/ProsusAI/finBERT, Apache-2.0), a BERT model further pre-trained on
financial text and fine-tuned for positive / negative / neutral classification. See Araci (2019), "FinBERT:
Financial Sentiment Analysis with Pre-trained Language Models" (arXiv:1908.10063); the classifier head was
fine-tuned on the Financial PhraseBank (Malo et al., 2014, "Good debt or bad debt: Detecting semantic
orientations in economic texts").

The weights are read from a local directory only (nothing is ever downloaded at runtime); when they are
absent, or ARIA_SENTIMENT=0, every call degrades to None and callers fall back to no sentiment.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from loguru import logger

MODEL_NAME = "ProsusAI/FinBERT"
THRESHOLD = 0.25  # |net| at or above this is called positive/negative
_BATCH, _MAX_LEN = 16, 96

# Fixed keyword rules: the headline direction when FinBERT is not available (also the cheap path of tone()).
_UP = re.compile(r"\b(wins?|won|bags|secures?|record|beats?|surges?|jumps?|soars?|rises?|rallies|growth|expands?|approv\w*|upgrade\w*|raises?|strong|higher|gains?|boost\w*|launch\w*)\b", re.I)
_DOWN = re.compile(r"\b(falls?|drops?|slumps?|plunges?|miss(?:es)?|cuts?|penalty|probe|raid|resigns?|downgrade\w*|weak|lower|loss|declines?|ban|delay\w*|default\w*|slows?|warns?|underperform\w*|lags?)\b", re.I)

_lock = threading.Lock()
_cache: dict[str, dict] = {}  # text -> score; the same headlines and call sentences recur between requests
_CACHE_MAX = 5000
_model: tuple | None = None  # (tokenizer, model, lower-cased labels in the model's own index order)


def model_dir() -> Path:
    return Path(os.environ.get("ARIA_FINBERT_DIR") or Path(__file__).resolve().parents[3] / "models" / "nlp" / "finbert")


def enabled() -> bool:
    if os.environ.get("ARIA_SENTIMENT") == "0":
        return False
    d = model_dir()
    return (d / "config.json").exists() and (d / "pytorch_model.bin").exists()


def label(net: float) -> str:
    return "positive" if net >= THRESHOLD else "negative" if net <= -THRESHOLD else "neutral"


def _load() -> tuple:
    global _model
    if _model is None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        d = str(model_dir())
        tok = AutoTokenizer.from_pretrained(d, local_files_only=True)
        mdl = AutoModelForSequenceClassification.from_pretrained(d, local_files_only=True).eval()
        _model = (tok, mdl, [mdl.config.id2label[i].lower() for i in range(mdl.config.num_labels)])
    return _model


def loaded() -> bool:
    return _model is not None


def score(texts: list[str], wait: float = -1) -> list[dict] | None:
    """[{"positive", "negative", "neutral", "net": positive - negative}] per text, in order; None when sentiment is
    disabled, anything fails, or the model is busy for longer than ``wait`` seconds (-1 waits for as long as it takes)."""
    if not texts:
        return []
    if not enabled():
        return None
    todo = sorted((t for t in dict.fromkeys(texts) if t not in _cache), key=len)  # similar lengths per batch: less padding, about twice as fast
    if todo:
        if not _lock.acquire(timeout=wait):  # one forward pass at a time; also guards the lazy load
            return None
        try:
            import torch

            tok, mdl, labels = _load()
            if len(_cache) + len(todo) > _CACHE_MAX:
                _cache.clear()  # ponytail: wholesale clear, an LRU if hit rates ever matter
            with torch.no_grad():
                for i in range(0, len(todo), _BATCH):
                    batch = todo[i:i + _BATCH]
                    enc = tok(batch, padding=True, truncation=True, max_length=_MAX_LEN, return_tensors="pt")
                    for t, row in zip(batch, torch.softmax(mdl(**enc).logits, dim=-1).tolist()):
                        p = dict(zip(labels, row))
                        _cache[t] = {"positive": p["positive"], "negative": p["negative"], "neutral": p["neutral"], "net": p["positive"] - p["negative"]}
        except Exception as exc:
            logger.warning(f"FinBERT scoring failed: {exc}")
            return None
        finally:
            _lock.release()
    return [_cache[t] for t in texts]


def tone(texts: list[str]) -> dict:
    """Quick read of some short texts: FinBERT when it is already loaded and free, else the keyword rules. Never loads the model."""
    scores = score(texts, wait=0.3) if texts and loaded() else None
    if scores:
        nets = [s["net"] for s in scores]
    else:
        nets = [float(bool(_UP.search(t))) - float(bool(_DOWN.search(t))) for t in texts]
    net = sum(nets) / len(nets) if nets else 0.0
    return {"engine": "finbert" if scores else "keywords", "net": net, "label": label(net),
            "items": [{"text": t, "label": label(n), "net": n} for t, n in zip(texts, nets)]}
