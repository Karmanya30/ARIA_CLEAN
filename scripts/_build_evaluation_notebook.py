"""
One-off script that regenerates ARIA_Evaluation.ipynb. Not part of the
app -- run manually if the notebook needs rebuilding after an API change.
Kept in scripts/ rather than deleted so the notebook's structure has a
clear source of truth instead of being hand-edited as raw JSON.
"""
import json
import pathlib
import uuid


def _cell(cell_type: str, source: str) -> dict:
    return {
        "cell_type": cell_type,
        "id": uuid.uuid4().hex[:8],
        "metadata": {},
        "source": source.splitlines(keepends=True),
        **({"execution_count": None, "outputs": []} if cell_type == "code" else {}),
    }


CELLS = [
    ("markdown", """# ARIA — Multimodal Financial Intelligence Platform
### BTP Evaluation Notebook — IIIT Sri City

Run cells in order. Each cell demonstrates one real, trained component of
the system (`modules/`, `ai/`, `shared/`) -- not a mock. Run the training
commands in the README first if a cell reports a model as untrained."""),
    ("code", """# Setup -- run this first
import os, sys, warnings
ROOT = os.path.dirname(os.getcwd())  # notebook lives at repo root already; adjust if moved
if os.path.basename(os.getcwd()) != "ARIA_CLEAN" and os.path.exists(os.path.join(os.getcwd(), "modules")):
    ROOT = os.getcwd()
else:
    ROOT = os.getcwd()
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")
print("Setup complete. Working dir:", os.getcwd())"""),
    ("markdown", "## 1. Tax Rules Engine (FY 2025-26)\nDeterministic computation — no ML, pure financial logic, slabs verified live against current sources."),
    ("code", """from modules.finance.tax import tax_new, tax_old

incomes = [500_000, 700_000, 1_000_000, 1_200_000, 1_500_000]
print(f"{'Income':>15}  {'New Regime':>12}  {'Old Regime (80C=1.5L)':>22}  {'Save with Old':>14}")
print("-" * 70)
for inc in incomes:
    tn = tax_new(inc)
    to = tax_old(inc, deductions_80c=150_000)
    saving = tn.total_tax - to.total_tax
    print(f"Rs.{inc:>10,.0f}  Rs.{tn.total_tax:>9,.0f}  Rs.{to.total_tax:>19,.0f}  Rs.{saving:>11,.0f}")"""),
    ("markdown", "## 2. SIP & EMI Calculator\nClosed-form financial math — no ML."),
    ("code", """from modules.finance.sip_emi_calc import sip_future_value, emi

print("=== SIP Future Value ===")
for monthly, years, rate in [(5000, 10, 12), (10000, 20, 12), (15000, 30, 12)]:
    fv = sip_future_value(monthly, years, rate)
    print(f"  Rs.{monthly:,}/mo for {years}yr @{rate}% = Rs.{fv:,.0f}")

print("\\n=== EMI Calculation ===")
for principal, rate, years, label in [
    (3_000_000, 8.5, 20, "Home loan 30L"),
    (500_000, 10.5, 5, "Car loan 5L"),
    (200_000, 12.0, 3, "Personal loan 2L"),
]:
    e = emi(principal, rate, years)
    total = e * years * 12
    interest = total - principal
    print(f"  {label}: EMI=Rs.{e:,.0f}  Total interest=Rs.{interest:,.0f}")"""),
    ("markdown", "## 3. XGBoost Risk Profiler + SHAP Explainability\nReal trained model (5-fold CV macro-F1 = 0.99 on synthetic personas). Run `python -m modules.finance.train.train_xgb_risk` first if this errors."),
    ("code", """from modules.finance.risk_model import predict

personas = [
    ("Young IT (aggressive)", dict(monthly_income=120_000, age=26, dependents=0, existing_emi=0, city_tier=1)),
    ("Mid-career (moderate)", dict(monthly_income=150_000, age=38, dependents=2, existing_emi=25_000, city_tier=1)),
    ("Near-retire (conservative)", dict(monthly_income=100_000, age=57, dependents=1, existing_emi=8_000, city_tier=1)),
]

print(f"{'Persona':30} {'Risk':12} {'Conf':8} {'Top SHAP driver'}")
print("-" * 75)
for label, kwargs in personas:
    r = predict(transactions=[], **kwargs)
    driver = r.top_features[0][0] if r.top_features else "N/A"
    print(f"{label:30} {r.label:12} {r.confidence:7.0%}  {driver}")"""),
    ("markdown", "## 4. Budget Linear Program\nDeterministic `scipy.optimize.linprog` — no ML, always feasible for realistic inputs."),
    ("code", """from modules.finance.budget_optimize import optimize_budget
import matplotlib.pyplot as plt

income = 95000
b = optimize_budget(income=income, existing_emi=8500, city_tier=1, risk_label="Moderate", emergency_fund_months=1.0)

categories = ["Housing", "Food", "Transport", "Utilities", "EMI", "SIP", "Entertainment", "Emergency"]
amounts = [b.housing, b.food, b.transport, b.utilities, b.emi, b.sip, b.entertainment, b.emergency_fund_add]
colors = ["#5B9BD5"] * 5 + ["#70AD47", "#70AD47", "#ED7D31"]

fig, ax = plt.subplots(figsize=(10, 4))
bars = ax.barh(categories, amounts, color=colors)
for bar, amt in zip(bars, amounts):
    ax.text(bar.get_width() + 200, bar.get_y() + bar.get_height() / 2, f"Rs.{amt:,.0f}", va="center", fontsize=9)
ax.set_xlabel("Amount (Rs.)")
ax.set_title(f"Optimized Budget — Income Rs.{income:,} | Moderate Risk | City Tier 1")
ax.set_xlim(0, max(amounts) * 1.25)
plt.tight_layout()
plt.show()
print(f"Total allocated: Rs.{sum(amounts):,.0f} (income: Rs.{income:,})")
print(f"SIP maximised at: Rs.{b.sip:,.0f}/month ({b.sip/income:.0%} of income)")"""),
    ("markdown", "## 5. Isolation Forest — Anomaly Detection\nFit fresh per-user at request time (not a persisted model file) — needs at least 10 transactions to run."),
    ("code", """from modules.finance.anomaly import detect_for_user
from modules.finance.schemas import Transaction
from datetime import date, timedelta
import random

rng = random.Random(7)
today = date.today()
transactions = [
    Transaction(date=today - timedelta(days=i), category=rng.choice(["food", "transport", "utilities"]),
                amount=rng.uniform(200, 800), channel="upi")
    for i in range(15)
]
transactions.append(Transaction(date=today - timedelta(days=1), category="other", amount=85_000, channel="card"))  # anomalous!

flags = detect_for_user(transactions)
print(f"Transactions analysed: {len(transactions)}")
print(f"Anomalies flagged:     {len(flags)}")
for f in flags:
    print(f"\\n  FLAGGED: Rs.{f.transaction.amount:,.0f} ({f.transaction.category})")
    print(f"  Reason:  {f.reason}")
    print(f"  Score:   {f.score:.2f}")"""),
    ("markdown", "## 6. LSTM Spending Forecast (3-month)\nReal trained quantile-regression LSTM (held-out P50 MAE = 2.3% of income). Needs 12+ months of history for a non-trivial forecast -- a brand-new user with no history correctly gets an all-zero forecast, not a hallucinated one."),
    ("code", """from modules.finance.forecast_model import predict as forecast_predict

# Empty history: the honest cold-start behaviour, not a crash or a guess.
empty_forecast = forecast_predict(monthly_income=95_000, transactions=[])
print("Cold start (no history) sample:", empty_forecast[0].category, empty_forecast[0].forecast)

# With a full 15-month synthetic history (from scripts/generate_synthetic_transactions.py):
import pandas as pd
from pathlib import Path
from modules.finance.schemas import Transaction

meta_path = Path("data/raw/transactions_synthetic/_metadata.csv")
if meta_path.exists():
    meta = pd.read_csv(meta_path).iloc[0]
    txn_df = pd.read_parquet(f"data/raw/transactions_synthetic/{meta.user_id}.parquet")
    txns = [Transaction(**t) for t in txn_df.to_dict("records")]
    forecast = forecast_predict(meta.monthly_income, txns)
    for fc in forecast[:4]:
        print(f"  {fc.category:15} next month P50=Rs.{fc.forecast[0]:,.0f}  (P10=Rs.{fc.lower_ci[0]:,.0f}, P90=Rs.{fc.upper_ci[0]:,.0f})")
else:
    print("Run `python -m scripts.generate_synthetic_transactions` first to see the trained forecast in action.")"""),
    ("markdown", "## 7. SBERT + FAISS Concept Retrieval\nReal semantic search over the 50-concept knowledge base, threshold-gated against hallucinated matches."),
    ("code", """from modules.tutor.retriever import retrieve

queries = [
    "what is compounding",
    "SIP monthly investment",
    "how to save tax 80C",
    "retirement planning",
    "home loan EMI",
    "compoundd innterest",  # misspelled -- should still resolve
]

print(f"{'Query':35}  Top match (score)")
print("-" * 70)
for q in queries:
    hits = retrieve(q, k=1)
    top = f"{hits[0]['canonical_name']} ({hits[0]['score']:.2f})" if hits else "no match"
    print(f"{q:35}  {top}")"""),
    ("markdown", "## 8. Deep Knowledge Tracing (DKT) — Mastery Evolution\nReal trained LSTM (Piech et al. 2015 style; held-out AUC 0.74). Mastery should rise with repeated correct answers."),
    ("code", """import matplotlib.pyplot as plt
from modules.tutor.knowledge import mastery_vector

interactions = [
    {"concept_id": "compound_interest", "is_correct": False},
    {"concept_id": "compound_interest", "is_correct": False},
    {"concept_id": "compound_interest", "is_correct": True},
    {"concept_id": "simple_interest", "is_correct": True},  # prerequisite
    {"concept_id": "compound_interest", "is_correct": True},
    {"concept_id": "compound_interest", "is_correct": True},
]

masteries = [mastery_vector([])["compound_interest"]]
for i in range(1, len(interactions) + 1):
    masteries.append(mastery_vector(interactions[:i])["compound_interest"])

plt.figure(figsize=(9, 4))
plt.plot(masteries, "b-o", linewidth=2, markersize=8)
labels = ["Start", "Wrong", "Wrong", "Correct", "Prereq\\ncorrect", "Correct", "Correct"]
for i, (m, lbl) in enumerate(zip(masteries, labels)):
    plt.annotate(lbl, (i, m), textcoords="offset points", xytext=(0, 12), ha="center", fontsize=8)
plt.axhline(0.7, color="green", linestyle="--", label="Mastery threshold (70%)")
plt.xlabel("Interaction number"); plt.ylabel("Mastery probability")
plt.title("DKT: Compound Interest Mastery Evolution")
plt.ylim(0, 1); plt.legend(); plt.tight_layout()
plt.show()
print(f"Final mastery after 6 interactions: {masteries[-1]:.3f}")"""),
    ("markdown", "## 9. DQN Teaching Agent — Action Selection Policy\nReal trained agent (stable-baselines3, mean eval reward 3.75 vs. target > 0)."),
    ("code", """import numpy as np
from collections import Counter
import matplotlib.pyplot as plt
from modules.tutor.teaching import choose_action

mastery_levels = np.linspace(0, 1, 20)
actions_taken = [
    choose_action(mastery_target=float(m), avg_mastery_prereqs=0.7, last_5_accuracy=0.6,
                  session_length=0.0, concept_difficulty=0.4)
    for m in mastery_levels
]

print("Mastery -> Teaching action (as it changes):")
print("-" * 45)
last = None
for m, a in zip(mastery_levels, actions_taken):
    if a != last:
        print(f"  {m:.0%}+  ->  {a}")
        last = a

counts = Counter(actions_taken)
fig, ax = plt.subplots(figsize=(9, 3))
ax.bar(counts.keys(), counts.values(), color="#5B9BD5")
ax.set_title("DQN action distribution across mastery levels 0-100%")
ax.set_ylabel("Times selected")
plt.xticks(rotation=20)
plt.tight_layout(); plt.show()"""),
    ("markdown", "## 10. Entity Extraction from Free Text\nThe production path (`modules/finance/pipeline.py`) parses income/EMI/age directly out of chat messages -- this is what actually powers Module 1's structured-input trigger, not a separate NER module."),
    ("code", """from modules.finance.pipeline import _parse_indian_amount, _extract_age

sentences = [
    "I earn 95k/month, pay 25k rent, 8.5k EMI",
    "my income is 12 lakh per year",
    "I have 2 crore in savings and I am 32 years old",
    "save 60000 per year",
]

for sent in sentences:
    income = _parse_indian_amount(sent, "earn") or _parse_indian_amount(sent, "income")
    emi_amt = _parse_indian_amount(sent, "emi")
    age = _extract_age(sent)
    print(f"Input: {sent!r}")
    print(f"  income={income}  emi={emi_amt}  age={age}")"""),
    ("markdown", "## 11. Profile Persistence Across Turns\nDemonstrates the real `shared/user_store.py` (SQLite) flow: a profile stated in one turn is remembered on the next, without repeating every number."),
    ("code", """from modules.finance.pipeline import _try_build_financial_profile
from shared import user_store

demo_user = "notebook_demo_user"

profile = _try_build_financial_profile("I earn 95000 a month, pay 8500 EMI", demo_user)
print("Turn 1 (stated income+EMI):", profile.monthly_income, profile.existing_emi)

# Follow-up turn with no numbers at all -- should reuse the saved profile.
profile2 = _try_build_financial_profile("what about my tax", demo_user)
print("Turn 2 (no numbers stated):", profile2.monthly_income if profile2 else None)

saved = user_store.get_financial_profile(demo_user)
print("Saved in SQLite:", saved)"""),
    ("markdown", "## 12. Complete M1 Pipeline (All Models Together)\nXGBoost risk -> LSTM forecast -> Isolation Forest -> LP budget -> real tax -> SIP plan -> LLM narration, in one call."),
    ("code", """import time
from modules.finance.schemas import UserFinancialInput
from modules.finance.orchestrator import run

t0 = time.time()
inp = UserFinancialInput(
    user_id="notebook_demo", monthly_income=95_000, age=30, dependents=1,
    existing_emi=8_500, emergency_fund_months=2.0, city_tier=1, tax_regime="new",
)
resp = run(inp)
elapsed = time.time() - t0

print(f"Pipeline completed in {elapsed:.2f}s\\n")
print("=== RISK PROFILE (XGBoost) ===")
print(f"  Label:      {resp.risk.label}")
print(f"  Confidence: {resp.risk.confidence:.0%}")
if resp.risk.top_features:
    print("  SHAP drivers:", ", ".join(f"{f}={v:+.2f}" for f, v in resp.risk.top_features[:3]))

print("\\n=== BUDGET (Linear Programming) ===")
print(f"  Housing: Rs.{resp.budget.housing:,.0f}   SIP: Rs.{resp.budget.sip:,.0f}   EMI: Rs.{resp.budget.emi:,.0f}")

print("\\n=== SIP PLAN ===")
print(f"  Monthly SIP: Rs.{resp.sip_plan.monthly_sip:,.0f}   Equity/Debt: {resp.sip_plan.equity_pct:.0%} / {resp.sip_plan.debt_pct:.0%}")

print("\\n=== TAX (real FY2025-26 slabs) ===")
print(f"  Total tax: Rs.{resp.tax.total_tax:,.0f}   Effective rate: {resp.tax.effective_rate:.2f}%")

print(f"\\n=== NARRATION (Groq, falling back to Gemini) ===\\n{resp.natural_language}")"""),
    ("markdown", "## 13. LLM Reasoning Layer — Live Generation\nGroq (`openai/gpt-oss-120b`), automatically falling back to Gemini on error/rate-limit -- see `ai/llm/groq_client.py`. Needs `GROQ_API_KEY` and/or `GEMINI_API_KEY` in `.env`; the original plan's local FinGPT server was replaced with this for public-deployment reasons (no GPU needed, no 14GB VRAM requirement)."),
    ("code", """from ai.llm.groq_client import generate_response, health

if not health():
    print("Neither GROQ_API_KEY nor GEMINI_API_KEY is set -- add one to .env to run this cell live.")
else:
    prompt = "In one sentence, explain compound interest to a beginner using an Indian rupee example."
    print(f"Prompt: {prompt!r}\\nResponse:")
    print(generate_response(prompt))"""),
    ("markdown", "## 14. Trained Model / Artifact Summary\nReal metrics from this project's own training runs (not placeholders)."),
    ("code", """import pathlib, json
from config.paths import (
    XGB_RISK_PATH, LSTM_SPEND_PATH, LSTM_KT_PATH, DQN_TEACHER_PATH, VECTOR_STORE_DIR,
)

print("=== TRAINED MODEL FILES ===")
models = {
    "XGBoost Risk Profiler": (XGB_RISK_PATH, "5-fold CV macro-F1 = 0.99"),
    "LSTM Spend Forecaster": (LSTM_SPEND_PATH, "Held-out P50 MAE = 2.3% of income"),
    "DKT Knowledge Tracer": (LSTM_KT_PATH, "Held-out AUC = 0.74"),
    "DQN Teaching Agent": (DQN_TEACHER_PATH.with_suffix(".zip"), "Mean eval reward = 3.75 (target > 0)"),
    "FAISS Concept Index": (VECTOR_STORE_DIR / "concepts" / "index.faiss", "50 concepts, SBERT MiniLM-L6-v2"),
}
for name, (path, metric) in models.items():
    p = pathlib.Path(path)
    size_kb = p.stat().st_size // 1024 if p.exists() else 0
    status = "OK" if p.exists() else "MISSING (see README's 'Train the models' section)"
    print(f"  [{status:>7}]  {name:<24} {size_kb:>6} KB  |  {metric}")

print("\\nNote: Isolation Forest has no file here by design -- it's fit fresh")
print("per-user, at request time, on that user's own transaction history.")

print("\\n=== DATASET SIZES ===")
txn_dir = pathlib.Path("data/raw/transactions_synthetic")
kb_path = pathlib.Path("data/raw/concepts_kb/concepts.json")
seq_path = pathlib.Path("data/raw/kt_sequences/sequences.json")
if txn_dir.exists():
    print(f"  Synthetic users: {len(list(txn_dir.glob('*.parquet')))}")
if kb_path.exists():
    print(f"  Financial concepts: {len(json.loads(kb_path.read_text(encoding='utf-8')))}")
if seq_path.exists():
    print(f"  Simulated KT learners: {len(json.loads(seq_path.read_text(encoding='utf-8')))}")"""),
]


def main() -> None:
    notebook = {
        "cells": [_cell(t, s) for t, s in CELLS],
        "metadata": {
            "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.13.3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out_path = pathlib.Path(__file__).resolve().parent.parent / "ARIA_Evaluation.ipynb"
    out_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(CELLS)} cells -> {out_path}")


if __name__ == "__main__":
    main()
