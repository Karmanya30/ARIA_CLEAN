"""
XGBoost risk profiler — real trained model, not a heuristic.

Train first: python -m modules.finance.train.train_xgb_risk
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from loguru import logger

from config.paths import FINANCE_MODELS_DIR, XGB_RISK_PATH
from modules.finance.features import (
    FEATURE_NAMES,
    build_user_feature_row,
    transactions_to_dataframe,
)
from modules.finance.schemas import RiskProfile, Transaction

ARTIFACTS_PATH = FINANCE_MODELS_DIR / "xgb_risk_profile.artifacts.joblib"

_model: xgb.XGBClassifier | None = None
_label_order: list[str] | None = None
_explainer = None


def is_trained() -> bool:
    return XGB_RISK_PATH.exists() and ARTIFACTS_PATH.exists()


def _load() -> None:
    global _model, _label_order
    if _model is not None:
        return
    if not is_trained():
        raise FileNotFoundError(
            f"{XGB_RISK_PATH} not found. Train it first: "
            "python -m modules.finance.train.train_xgb_risk"
        )
    model = xgb.XGBClassifier()
    model.load_model(str(XGB_RISK_PATH))
    artifacts = joblib.load(ARTIFACTS_PATH)
    _model = model
    _label_order = artifacts["label_order"]


def _top_shap_features(x: pd.DataFrame, class_idx: int, k: int = 3) -> list[tuple[str, float]]:
    """SHAP contributions for the predicted class, most influential first.
    Never raises — an explanation is a nice-to-have, not load-bearing."""
    global _explainer
    try:
        import shap

        if _explainer is None:
            _explainer = shap.TreeExplainer(_model)
        # shap_values shape for a multiclass XGBClassifier: (n_samples, n_features, n_classes)
        shap_values = _explainer.shap_values(x)
        contributions = shap_values[0, :, class_idx]
        order = np.argsort(-np.abs(contributions))[:k]
        return [(FEATURE_NAMES[i], float(contributions[i])) for i in order]
    except Exception as exc:
        logger.debug(f"SHAP explanation failed (non-critical, narration still works): {exc}")
        return []


def predict(
    monthly_income: float,
    age: int,
    dependents: int,
    existing_emi: float,
    city_tier: int,
    transactions: list[Transaction] | None = None,
) -> RiskProfile:
    _load()
    txn_df = transactions_to_dataframe(transactions or [])
    row = build_user_feature_row(
        txn_df, monthly_income, age, dependents, existing_emi, city_tier
    )
    x = pd.DataFrame([row], columns=FEATURE_NAMES)

    probs = _model.predict_proba(x)[0]
    class_idx = int(np.argmax(probs))
    label = _label_order[class_idx]
    confidence = float(probs[class_idx])
    top_features = _top_shap_features(x, class_idx)

    return RiskProfile(label=label, confidence=confidence, top_features=top_features)
