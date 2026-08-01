"""
Module 1 orchestrator — ties XGBoost risk, LSTM forecast, Isolation Forest
anomaly detection, LP budget optimization, real tax slabs, and closed-form
SIP math together into one M1Response, narrated by the shared LLM client
(Groq, falling back to Gemini — see ai/llm/groq_client.py).
"""
from __future__ import annotations

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import M1_NARRATION
from modules.finance import anomaly, budget_optimize, forecast_model, risk_model, tax
from modules.finance.schemas import M1Response, SipPlan, UserFinancialInput

# Equity/debt split by risk class — more aggressive risk tolerance -> more equity.
EQUITY_SPLIT = {"Conservative": 0.3, "Moderate": 0.6, "Aggressive": 0.8}
# ELSS cap under Section 80C = ₹1.5L / 12 months; only meaningful in the old regime.
TAX_SAVER_MONTHLY_CAP = 12_500


def _build_sip_plan(sip_amount: float, risk_label: str, tax_regime: str) -> SipPlan:
    equity_pct = EQUITY_SPLIT.get(risk_label, EQUITY_SPLIT["Moderate"])
    tax_saver_cap = TAX_SAVER_MONTHLY_CAP if tax_regime == "old" else 0.0
    tax_saver = min(sip_amount * equity_pct, tax_saver_cap)
    return SipPlan(
        monthly_sip=round(sip_amount, 0),
        equity_pct=equity_pct,
        debt_pct=round(1 - equity_pct, 2),
        tax_saver_amount=round(tax_saver, 0),
    )


def run(user_input: UserFinancialInput) -> M1Response:
    risk = risk_model.predict(
        monthly_income=user_input.monthly_income,
        age=user_input.age,
        dependents=user_input.dependents,
        existing_emi=user_input.existing_emi,
        city_tier=user_input.city_tier,
        transactions=user_input.transactions,
    )
    forecast = forecast_model.predict(user_input.monthly_income, user_input.transactions)
    anomalies = anomaly.detect_for_user(user_input.transactions)
    budget = budget_optimize.optimize_budget(
        income=user_input.monthly_income,
        existing_emi=user_input.existing_emi,
        city_tier=user_input.city_tier,
        risk_label=risk.label,
        emergency_fund_months=user_input.emergency_fund_months,
    )
    tax_result = tax.compute(
        monthly_income=user_input.monthly_income, regime=user_input.tax_regime
    )
    sip_plan = _build_sip_plan(budget.sip, risk.label, user_input.tax_regime)

    forecast_next_month_total = sum(f.forecast[0] for f in forecast) if forecast else 0.0
    top_factor = risk.top_features[0][0] if risk.top_features else "overall financial profile"

    prompt = M1_NARRATION.format(
        income=user_input.monthly_income,
        age=user_input.age,
        city_tier=user_input.city_tier,
        emi=user_input.existing_emi,
        regime=user_input.tax_regime,
        risk_label=risk.label,
        risk_conf=risk.confidence,
        top_factor=top_factor,
        sip=sip_plan.monthly_sip,
        equity_pct=sip_plan.equity_pct,
        debt_pct=sip_plan.debt_pct,
        tax_saver=sip_plan.tax_saver_amount,
        emergency=budget.emergency_fund_add,
        free_cash=budget.sip,
        forecast=forecast_next_month_total,
        n_anomalies=len(anomalies),
    )
    narration = generate_response(prompt)

    return M1Response(
        risk=risk,
        forecast=forecast,
        anomalies=anomalies,
        budget=budget,
        sip_plan=sip_plan,
        tax=tax_result,
        natural_language=narration,
    )
