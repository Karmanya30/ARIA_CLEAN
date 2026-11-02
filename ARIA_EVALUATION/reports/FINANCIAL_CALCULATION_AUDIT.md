# ARIA financial calculation audit (Phase A)

Date: 2026-11-02. Scope: deterministic code in `modules/finance` (SIP, EMI, goals, retirement, tax old/new, budget LP, health score, affordability, instrument recommender, spending insights) plus the three ML numbers (spend forecast LSTM, IsolationForest anomaly, XGBoost risk). Application code was not modified. No LLM, no network, no server, no browser, no microphone, no user database.

## How it was measured
* Reference implementations: `ARIA_EVALUATION/tests/financial/ref_impl.py` (written independently: month-by-month roll-forward for SIP, bisection on simulated loan balance for EMI, bracket-slice tax, closed-form LP bound). Nothing is imported from ARIA into the reference.
* Drivers (in-process imports, `OMP_NUM_THREADS=2 MKL_NUM_THREADS=2`):
  * `run_finance_only.py` -> `run_financial_validation.py` sections `sip_emi`, `tax`, `engine` (the equity/valuation/ratio sections of that file were NOT run; they are outside this task).
  * `run_finance_extra.py` -> budget, recommender, spending, anomaly, forecast, risk.
* Raw per-check results (id, case, actual, expected, verdict): `ARIA_EVALUATION/tests/financial/results/*.json`.
* Command: `.venv\Scripts\python.exe -X utf8 ARIA_EVALUATION\tests\financial\run_finance_only.py` and `...\run_finance_extra.py`.
* I corrected two mistakes in my own test file after the first run (the pipeline SIP wrapper was extracted without its import; one hand-calculated tax expectation used the wrong slab). Both were test errors, not ARIA errors; ARIA matched the corrected hand figure 292,500.

## Summary (VERIFIED unless stated)
| Area | Checks | Pass | Fail | Observed |
|---|---|---|---|---|
| SIP / EMI (`sip_emi_calc.py`, pipeline wrapper, amount parsing) | 67 | 56 | 4 | 7 |
| Tax old/new (`tax.py`) | 91 | 87 | 2 | 2 |
| Engine: snapshot, goals, retirement, health score, afford, what-if (`engine.py`) | 57 | 50 | 3 | 4 |
| Budget LP | 30 | 21 | 0 | 9 |
| Instrument recommender | 357 | 170 | 182 | 5 |
| Spending insights | 18 | 16 | 0 | 2 |
| Anomaly (IsolationForest) | 9 | 5 | 0 | 4 |
| Spend forecast (LSTM) | 10 | 4 | 0 | 6 |
| Risk (XGBoost) | 6 | 1 | 0 | 5 |

Headline: the core closed-form maths agrees with the independent references to 1e-9 relative (SIP future value and required SIP across 7 parameter sets, EMI across 6 loans, total interest, round trip, zero-rate, invalid-input zero returns, old/new slab boundaries including 87A rebate and the new-regime marginal relief at 12L). The defects are in edges, in rule wiring, and in the ML outputs.

## Defects

### FIN-001 Instrument recommender applies the 80C bonus/penalty to instruments that have no 80C benefit (P2) - VERIFIED
* Evidence: `modules/finance/instrument_recommender.py:102` tests `"80c" in tax_treatment.lower()`. The catalogue text in `data/raw/concepts_kb/concepts.json` for ETF, Index Fund and Direct Equity is "... no Section 80C benefit." and for FD "... a separate 5-year tax-saver FD variant is 80C eligible". The substring matches the negation. Reproduce: `run_finance_extra.py`, checks REC-338..343 (flag by substring is True for etf, index_fund, fd, direct_equity; true eligibility is False). Measured against a reference using the true flag, 178 of 336 score cells differ (ids REC-001..336; every cell for those four instruments that is not clamped at 0/100).
* Effect: under the old regime ETF, Index Fund, Direct Equity and generic FD get +15 and the sentence "this qualifies for a Section 80C-family deduction" (false); under the new regime they get -10 and "main tax-saving benefit doesn't apply" (misleading, there was none). Ranking and fit labels (strong_fit/consider) shift. The explanation does not match reality for 4 of 7 instruments.
* Fix: add an explicit boolean `eligible_80c` to the catalogue entries (single source of truth) and read it instead of substring matching. Regression risk: low; catalogue schema gains one field, scores for ELSS/PPF/NPS unchanged.

### FIN-002 Surcharge is not implemented in income tax (P2) - VERIFIED (absence); size computed from published statute rates as I recall them, UNTESTED against an official calculator
* Evidence: `grep -i surcharge modules/finance/*.py` finds nothing; TAX-084/085: `tax_new(10_000_000).total_tax = 2,659,800`; the same tax with 10% surcharge (income 50L-1Cr) would be 2,925,780, a difference of 265,980 (10%). The module docstring calls itself "demo-grade", but `tax_compare` and the chat present the figure as the tax.
* Why it matters: for incomes above Rs 50 lakh the tax and the old-vs-new verdict are wrong by up to 10-25%.
* Fix: add surcharge slabs with marginal relief (new regime capped at 25%) or return a "excludes surcharge" flag and refuse above 50L. Regression risk: low, localised.

### FIN-003 Old-regime tax: negative deductions raise tax (P3) - VERIFIED
* Evidence: TAX-080: `tax_old(1_000_000, -200_000)` = 163,800 vs 106,600 with 0 deduction (`tax.py:102-106` uses `min(d, cap)` with no lower bound). Reachable if a profile field is negative. Fix: `max(0, ...)`; validate in schema. Risk: none.

### FIN-004 Sub-month tenure crashes required-SIP and EMI (P3) - VERIFIED
* Evidence: SIP-025/026/047/048: `sip_required(1e5, 0.04, 12)`, `emi(1e5, 9, 0.04)` and the zero-rate variants raise `ZeroDivisionError` because `n = int(round(years*12))` is 0 (`sip_emi_calc.py:17,28,39,48`). `sip_future_value` returns 0.0 silently for the same input (SIP-024). Fix: clamp `n = max(1, ...)` or return 0.0 consistently and validate. Risk: low. (Reachability from chat not traced: UNTESTED.)

### FIN-005 `afford_sip` and `sip_capacity` crash on unknown surplus (P3, latent) - VERIFIED
* Evidence: ENG-038/039: profile with income and only a `rent` expense gives `TypeError` (`engine.py:179`, `:190`). The chat path guards this (`pipeline.py:873-876` via `_known("expenses")`, same 3-category rule), so only a direct caller hits it. Fix: return an unknown/None result. Risk: none.

### FIN-006 Goal with 0 years and an unmet target reports sip_needed 0 (P3) - VERIFIED
* Evidence: ENG-014: `goal_plan({"name":"x","target":1e6,"years":0}, {})` gives `sip_needed: 0` although the gap is the whole target (`sip_emi_calc.sip_required` returns 0.0 for years<=0). Reads as "nothing needed". Fix: report the lump-sum gap or raise. Risk: low.

### FIN-007 Budget optimiser output is not a usable budget (P2) - VERIFIED
* Evidence: BUD-004 etc. The LP maximises only SIP; food/transport/utilities/emergency have no upper bound and no objective weight, so the solver dumps the remainder into one line. Income 1,00,000, EMI 0, tier 1, Moderate gives housing 0%, entertainment 0%, food 68%, SIP 25%. Other cases: food 33%, 54%, 52%, 52%. The SIP figure itself matches my closed form `min(cap*income, income - EMI - floors - emergency floor)` in all 6 feasible cases (BUD-001..), and the sum equals income within rounding (<= Rs 4), but "housing 0, food 52-68%" is not realistic advice. Which line absorbs the slack is solver-vertex dependent, so it may change between scipy versions (SUSPECTED).
* Fix: add soft targets (e.g. minimise deviation from a 50/30/20-style share) or cap food at a realistic share and put the slack into savings/emergency; document that only SIP is optimised. Risk: medium (changes narrated numbers; existing tests in `tests/finance` should be re-run).
* Also: negative EMI accepted (BUD-028, emits `emi = -5000` and inflates food), unknown tier/risk silently fall back (BUD-030), NaN income raises a scipy error rather than the friendly ValueError (BUD-029). All P3.

### FIN-008 Spend forecast does not reproduce a flat history and is not income-invariant (P2) - VERIFIED measurement; interpretation SUSPECTED
* Evidence (`models/finance/lstm_spend_forecast.pt`, synthetic 8 months of constant spend, income 1,00,000): food history 8,000 -> forecast P50 13,794 / 13,591 / 13,142 (+72%); transport 3,000 -> 5,416 (+80%); housing 20,000 -> 17,185 (-14%); EMI 8,000 -> 9,023. Same rupee spend with income 2,00,000 gives a food forecast of 26,301 (3.3x). FCS-006..010. The model predicts ratios of income and rescales, so the rupee forecast is dominated by what the net learned for typical income, not by the user's history. Synthetic flat data may be out of distribution, so this is a probe, not an accuracy benchmark.
* Passing: ratio computation matches the reference; P10<=P50<=P90 held for all categories and months; no negatives; empty history gives zeros; income<=0 returns zeros without error.
* Fix: evaluate against held-out real or realistic series with a naive (last value / moving average) baseline and ship the forecast only where it beats it; otherwise show the baseline. Risk: medium.

### FIN-009 IsolationForest always flags about 2% (P3) - VERIFIED
* Evidence: ANO-006: 60 clean transactions with no outlier still produce 2 flags (`IF_CONTAMINATION = 0.02`, `config/model_config.py:64`). An injected 100x outlier ranks first (ANO-003) and the reason text ratio (122.9x) equals the true amount/median (ANO-005). Fewer than 10 transactions, None, identical or zero amounts give no flags. A negative amount makes `log1p` NaN, filled with 0 (ANO-009). Fix: present flags as "most unusual" not "anomalous", or threshold on score. Risk: low.

### FIN-010 Smaller input-handling observations (P3) - VERIFIED
* `_parse_return_rate("0%")` returns 0.0 and `target_return or realistic_return` in `pipeline.py:271` replaces 0 with the default (SIP-067).
* "invest 10 percent of 50000" is parsed as Rs 10 (SIP-065).
* `inr(-5000)` prints "₹5k": a deficit loses its sign (ENG-056).
* NaN/negative rate inputs propagate without validation (SIP-027/028/049/050).
* `afford_purchase` with negative price returns EMI 0 and a "yes"-style result (ENG-030).

## Verified correct (measured)
* SIP future value (annuity due), required SIP, round trip: relative error <= 1e-9 against the roll-forward loop (SIP-001..).
* EMI and total interest vs bisection on simulated balance: <= 1e-8 relative; published example 10L @ 8.5% 20y = 8,678 (SIP, within Rs 0.5).
* Pipeline `_future_value_monthly_sip` now delegates to `sip_emi_calc` (agrees to 1e-12).
* New regime: slab boundaries, 87A rebate up to 12L taxable, marginal relief just above, cess 4%, 75,000 standard deduction (hand and reference agreement). Old regime: slabs for normal/senior/super-senior, 80C cap 1.5L, 80D caps 25k/50k, 87A rebate to 5L taxable, no relief above (cliff of about Rs 13,000 at 5L is statute behaviour, TAX-073).
* Spending insights: spend/EMI averages, savings rate, per-month net, category share, benchmark flag, trim amount, month-on-month trend, recurring detection, outlier flag, <10 transaction guard (16/16 against hand figures).
* Retirement and goal formulas: matched in the engine section (corpus = annual expense at retirement / 3.5%, inflation 6%/8% education).
* Determinism of the recommender, risk model and score ordering; fit labels follow the thresholds (70/40).

## Absent (not implemented, no tests invented)
XIRR, CAGR, portfolio analytics and risk (correlation, volatility, VaR), loan prepayment/amortisation schedule, goal wizard beyond the profile form, HRA / home-loan interest / 80CCD(1B) / capital-gains tax, surcharge (FIN-002), rent-vs-buy. (The equity-research valuation and ratio code has reference tests in `run_financial_validation.py` but was not run in this task.)

## NOT tested
* Whether the tax slab constants match the current official schedule for AY 2026-27: UNTESTED (no network; the file cites the Income Tax Department page dated 2026-10-16).
* Any LLM narration, template wording against numbers, or chat parsing end to end: BLOCKED (no LLM calls allowed; only the deterministic functions and the amount parsers were exercised).
* HTTP API routes, authentication, database-backed profile load: not run (no server started).
* Equity-research DCF, comps, ratios, scenario and price-forecast engines: not run in this task.
* XGBoost risk labels: no oracle; only determinism and crash behaviour probed (RSK-001..005, e.g. negative income and age 200 return a label without validation).
* Accuracy of the LSTM and the risk model on real data: UNTESTED.
* Float rounding at the API/UI layer (JSON number formatting): UNTESTED.
