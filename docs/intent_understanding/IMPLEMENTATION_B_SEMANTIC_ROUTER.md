# Implementation B: Semantic Router

## What was inspected first
`aurelio-labs/semantic-router` 1.1.1 (MIT; installed with `pip install semantic-router`). Version 1.x replaced the older `RouteLayer` API: routes (`Route(name, utterances)`) are scored by an `IndexedRouter` that embeds the utterances with any `DenseEncoder`, keeps them in a vector index (local by default) and returns a per-route `confidence` (aggregation of the top-k nearest utterances). There is also a `DecisionRouter` (learned, calibrated) that needs labelled data. Dependencies: about 40 extra packages (cohere, openai, mistral, voyage SDKs for the optional hosted encoders); no existing ARIA pin changed (NumPy 2.3.1, Pydantic 2.13.0 and Torch 2.13.0 are unchanged).

## What was built
* `core/intent/taxonomy.py`: the route labels are the modules the orchestrator can actually call (finance, tutor, market, equity_research, company_intelligence, data_lookup, general, smalltalk) and 93 hand-written example utterances, checked by `check_leakage.py` not to equal any benchmark query.
* `core/intent/semantic.py`: `AriaEncoder` is a `DenseEncoder` that wraps ARIA's own Sentence-BERT model (`shared.vector_store._get_encoder`), so a classification is one local embedding: about 7 to 12 ms warm, no LLM call, no tokens, no new model download. `classify()` returns every route's score, the margin to the second route, and the engine used; if the library is missing it falls back to the same idea in NumPy.
* `core/intent/arch.py::decide_b`: the router is consulted only for questions the deterministic rules could not place (they would fall through to the general model). It acts only above a score and margin threshold chosen on the dev split, never on `general`, and logs `intent_route` with score, margin and engine. Low confidence means "no opinion": the baseline route runs. `ARIA_SR_MODE=override` is the ablation that lets it override the rules.

## Why not more
The raw similarity of a small sentence encoder with 8 to 15 examples per route is a ranking signal, not a calibrated probability, and it confuses neighbouring modules (SIP as a concept versus SIP for my salary; a stock price versus a data lookup). The measured effect is in BENCHMARK_RESULTS.md.
