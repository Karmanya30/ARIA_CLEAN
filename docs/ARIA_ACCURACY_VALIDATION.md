# ARIA accuracy validation

Validation date: 31 October 2026.

## Changes

- Currency normalization preserves original units rather than relabelling dollars or cents as rupees or paise.
- Daily index observations carry their source date. Market narration that incorrectly implies an undated current price or relabels foreign currency falls back to dated index facts. Driver summaries that assert causation without supporting evidence also fall back to dated facts. When a conceptual comparison contains an unsupported current-market sentence, the safe explanation is retained while that sentence is replaced.
- Generic company fundamentals requests ask for a company or ticker. Named-company requests and explicit company or instrument context remain available.
- SIP and risk-profile calculations, research ratings, debate calls, company suitability information and saved-report outputs retain their original functionality at the project owner’s request. No new recommendation restriction has been imposed.

## Provider-backed evidence

The final run in `.audit/live3/accuracy-targeted-real.json` records a real configured-provider market request taking 5.92 seconds. Its response dates the Nifty/Sensex observations to 2026-10-30, describes them as delayed and uses the factual fallback. Three repeated generic-company questions returned the company/ticker clarification. A separate `.audit/live3/accuracy-replay-evidence.json` records a real provider response that asserted a market cause, and its deterministic replay after the fix. These checks verify those observed responses, not every provider datum or future output.

## Regression evidence

78 tests passed across finance follow-ups, equity research/report generation, generic-company clarification, currency handling and market snapshot/date disclosure. These used isolated fixtures; the provider-backed run above is separate.

An additional 37 focused tests passed across `tests/market/test_accuracy_repairs.py`, `tests/market/test_snapshot_disclosure.py`, `tests/qa/test_trust.py`, and `tests/test_news.py`. They cover dated snapshots, original currency units, news relevance, retained conceptual explanations, named company/focus context, and unsupported cause wording.

## Remaining limits

- Source dates do not independently establish source accuracy, and generated explanations can still contain errors.
- Market fallback can reject valid mixed-currency prose because it prioritizes avoiding unsupported relabelling.
- The factual checks use finite text patterns and are not a complete fact checker. They can miss alternative wording or remove useful narrative.
- Financial models and forecasts rely on assumptions and are not guarantees.
- Provider availability, human microphone input, audio hardware and current market accuracy are outside the deterministic regression suite.
