"""
Module 1 orchestrator — ties XGBoost risk, LSTM forecast, Isolation Forest
anomaly detection, LP budget optimization, real tax slabs, and closed-form
SIP math together into one M1Response, narrated by the shared LLM client
(Groq, falling back to Gemini — see ai/llm/groq_client.py).
"""
from __future__ import annotations

from ai.llm.groq_client import generate_response
from ai.llm.prompt_templates import M1_NARRATION, instrument_recommendation_prompt
from modules.finance import anomaly, budget_optimize, forecast_model, instrument_recommender, risk_model, tax
from modules.finance.schemas import BudgetAllocation, M1Response, SipPlan, UserFinancialInput

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


def run(user_input: UserFinancialInput, include_investment_plan_narrative: bool = False) -> M1Response:
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
    try:
        budget = budget_optimize.optimize_budget(
            income=user_input.monthly_income,
            existing_emi=user_input.existing_emi,
            city_tier=user_input.city_tier,
            risk_label=risk.label,
            emergency_fund_months=user_input.emergency_fund_months,
        )
    except ValueError as exc:
        # Zero or negative income (e.g. "I earn 0 a month") cannot be
        # optimised — return a graceful, informative response instead of
        # crashing.  All other fields (risk score, tax at zero, etc.) are
        # still meaningful and are returned so callers get a well-formed dict.
        return M1Response(
            risk=risk,
            forecast=forecast,
            anomalies=anomalies,
            budget=BudgetAllocation(
                housing=0.0,
                food=0.0,
                transport=0.0,
                utilities=0.0,
                emi=0.0,
                sip=0.0,
                entertainment=0.0,
                emergency_fund_add=0.0,
            ),
            sip_plan=_build_sip_plan(0.0, risk.label, user_input.tax_regime),
            tax=tax.compute(
                monthly_income=user_input.monthly_income,
                regime=user_input.tax_regime,
            ),
            natural_language=(
                f"I wasn't able to build a budget plan because: {exc}  "
                "If you've recently lost income or are between jobs, I can still "
                "help you with tax questions, SIP concepts, or financial planning "
                "once you have an income to work with."
            ),
        )
    tax_result = tax.compute(
        monthly_income=user_input.monthly_income, regime=user_input.tax_regime
    )
    sip_plan = _build_sip_plan(budget.sip, risk.label, user_input.tax_regime)

    # Stage 12 -- deterministic instrument-type ranking (real risk/horizon/
    # tax/emergency-fund inputs, no LLM guessing the ranking itself) is
    # always computed -- it's cheap (no LLM call) and useful structured
    # data regardless of narration. Narrating it is a second LLM call, so
    # that only happens when the caller says the query actually asked for
    # it (modules/finance/pipeline.py's _wants_investment_plan gate).
    investment_plan = instrument_recommender.recommend(
        risk_label=risk.label,
        horizon_years=user_input.horizon_years,
        tax_regime=user_input.tax_regime,
        emergency_fund_months=user_input.emergency_fund_months,
    )
    investment_narrative = ""
    if include_investment_plan_narrative:
        investment_prompt = instrument_recommendation_prompt([rec.model_dump() for rec in investment_plan])
        investment_narrative = generate_response(investment_prompt)

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
        investment_plan=investment_plan,
        investment_plan_narrative=investment_narrative,
    )
