"""
modules/finance/train/train_xgb_risk.py

Trains the XGBoost risk-profile classifier on synthetic transaction data.
Run scripts/generate_synthetic_transactions.py first.

Usage:
    python -m modules.finance.train.train_xgb_risk
"""
from __future__ import annotations

import joblib
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold, cross_val_score

from config.model_config import XGB_CPU_PARAMS, XGB_CV_FOLDS, RANDOM_STATE
from config.paths import FINANCE_MODELS_DIR, TRANSACTIONS_DIR, XGB_RISK_PATH
from modules.finance.features import FEATURE_NAMES, build_user_feature_row
from modules.finance.schemas import RISK_LABELS

ARTIFACTS_PATH = FINANCE_MODELS_DIR / "xgb_risk_profile.artifacts.joblib"


def load_training_frame() -> tuple[pd.DataFrame, pd.Series]:
    metadata_path = TRANSACTIONS_DIR / "_metadata.csv"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"{metadata_path} not found. Run "
            "`python -m scripts.generate_synthetic_transactions` first."
        )
    metadata = pd.read_csv(metadata_path)

    rows = []
    for _, meta in metadata.iterrows():
        txn_path = TRANSACTIONS_DIR / f"{meta['user_id']}.parquet"
        txn_df = pd.read_parquet(txn_path)
        row = build_user_feature_row(
            txn_df,
            monthly_income=meta["monthly_income"],
            age=int(meta["age"]),
            dependents=int(meta["dependents"]),
            existing_emi=meta["existing_emi"],
            city_tier=int(meta["city_tier"]),
        )
        rows.append(row)

    x = pd.DataFrame(rows, columns=FEATURE_NAMES)
    y = metadata["risk_label"]
    return x, y


def main() -> None:
    x, y = load_training_frame()
    y_encoded = y.map({label: idx for idx, label in enumerate(RISK_LABELS)})

    clf = xgb.XGBClassifier(
        objective="multi:softprob",
        num_class=len(RISK_LABELS),
        **{k: v for k, v in XGB_CPU_PARAMS.items() if k not in ("objective", "num_class")},
    )

    cv = StratifiedKFold(n_splits=XGB_CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    scores = cross_val_score(clf, x, y_encoded, cv=cv, scoring="f1_macro")
    print(f"{XGB_CV_FOLDS}-fold CV macro-F1: {scores.mean():.3f} (+/- {scores.std():.3f})")

    clf.fit(x, y_encoded)

    FINANCE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    clf.save_model(str(XGB_RISK_PATH))
    joblib.dump({"label_order": RISK_LABELS, "feature_names": FEATURE_NAMES}, ARTIFACTS_PATH)
    print(f"Saved model -> {XGB_RISK_PATH}")
    print(f"Saved artifacts -> {ARTIFACTS_PATH}")


if __name__ == "__main__":
    main()
