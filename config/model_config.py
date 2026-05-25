"""
config/model_config.py
Training + hyperparameters ONLY
"""

from __future__ import annotations


# ===============================
# Shared
# ===============================
RANDOM_STATE = 42


# ===============================
# XGBoost Risk Profiler
# ===============================
XGB_PARAMS = {
    "objective": "multi:softprob",
    "num_class": 3,
    "eval_metric": "mlogloss",
    "tree_method": "hist",
    "device": "cuda",
    "n_estimators": 400,
    "max_depth": 5,
    "learning_rate": 0.05,
    "min_child_weight": 3,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.0,
    "reg_lambda": 1.0,
    "random_state": RANDOM_STATE,
}

XGB_CPU_PARAMS = {**XGB_PARAMS, "device": "cpu"}

XGB_CV_FOLDS = 5
XGB_RISK_CLASSES = ["Conservative", "Moderate", "Aggressive"]


# ===============================
# LSTM Spend Forecast
# ===============================
LSTM_HIDDEN = 128
LSTM_LAYERS = 2
LSTM_DROPOUT = 0.3
LSTM_N_CATS = 8
LSTM_N_CTX = 12
LSTM_SEQ_LEN = 12
LSTM_HORIZON = 3
LSTM_BATCH_SIZE = 32
LSTM_EPOCHS = 80
LSTM_LR = 1e-3
LSTM_WEIGHT_DECAY = 1e-5
LSTM_QUANTILES = [0.10, 0.50, 0.90]
LSTM_GRAD_CLIP = 1.0
LSTM_EARLY_STOPPING_PATIENCE = 8


# ===============================
# Isolation Forest
# ===============================
IF_N_ESTIMATORS = 200
IF_CONTAMINATION = 0.02
IF_MAX_SAMPLES = "auto"
IF_RANDOM_STATE = RANDOM_STATE


# ===============================
# DKT
# ===============================
DKT_N_CONCEPTS = 50
DKT_HIDDEN = 128
DKT_LAYERS = 2
DKT_DROPOUT = 0.2
DKT_BATCH_SIZE = 64
DKT_EPOCHS = 50
DKT_LR = 1e-3
DKT_WEIGHT_DECAY = 1e-5
DKT_GRAD_CLIP = 1.0
DKT_EARLY_STOPPING_PATIENCE = 8


# ===============================
# DQN
# ===============================
DQN_LEARNING_RATE = 3e-4
DQN_BUFFER_SIZE = 50_000
DQN_BATCH_SIZE = 64
DQN_TRAIN_FREQ = 4
DQN_TARGET_UPDATE_INTERVAL = 1_000
DQN_EXPLORATION_FRACTION = 0.3
DQN_EXPLORATION_INITIAL_EPS = 1.0
DQN_EXPLORATION_FINAL_EPS = 0.05
DQN_GAMMA = 0.99
DQN_TOTAL_TIMESTEPS = 200_000
DQN_N_ACTIONS = 6
DQN_STATE_DIM = 5


# ===============================
# Intent Classifier
# ===============================
INTENT_MAX_LEN = 128
INTENT_BATCH_SIZE = 16
INTENT_EPOCHS = 5
INTENT_LR = 2e-5
INTENT_WEIGHT_DECAY = 0.01
INTENT_THRESHOLD = 0.45


# ===============================
# Backward Compatibility
# ===============================
N_CATEGORIES = LSTM_N_CATS
LSTM_BATCH = LSTM_BATCH_SIZE
DKT_BATCH = DKT_BATCH_SIZE

DQN_LR = DQN_LEARNING_RATE
DQN_BUFFER = DQN_BUFFER_SIZE
DQN_BATCH = DQN_BATCH_SIZE
DQN_TIMESTEPS = DQN_TOTAL_TIMESTEPS