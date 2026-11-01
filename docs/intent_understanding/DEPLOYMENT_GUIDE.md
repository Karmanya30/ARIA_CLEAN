# Deployment guide for the query-architecture variants

## Default: nothing changes
`ARIA_QUERY_ARCHITECTURE` unset or `baseline` runs today's routing; `core.intent` is not imported. Install nothing.

## Enabling a variant
1. `pip install -r requirements-intent.txt` (semantic-router 1.1.1 and langgraph 1.2.19, both MIT; tested with the pins in `requirements.txt`, which are unchanged). They add about 40 transitive packages; the Docker image only needs them if you set a variant.
2. Set the flag in `.env`: `ARIA_QUERY_ARCHITECTURE=semantic_router | langgraph | structured | hybrid`. Variants B-E need the sentence model ARIA already uses; D and E also need the language-model keys already configured (`GROQ_API_KEY`).
3. Thresholds (calibrated on the dev split; defaults are in `core/intent/arch.py`, overrides in `evaluation/intent_understanding/thresholds_*.json` or env): `ARIA_INTENT_SR_SCORE`, `ARIA_INTENT_SR_MARGIN`, `ARIA_INTENT_LLM_INTENT`, `ARIA_INTENT_LLM_CONTEXT`, `ARIA_INTENT_SR_VETO`. The dev optima are built in per variant (D: veto 0.7, E: veto 0.55; the others keep the defaults); the thresholds files are only read by the benchmark runner, and any `ARIA_INTENT_*` variable overrides the built-in value.
4. Ablation switches: `ARIA_SR_MODE=override`, `ARIA_INTENT_LLM=0`, `ARIA_INTENT_GRAPH=0`, `ARIA_INTENT_TIMEOUT_SECONDS`.

## Behaviour and safety
* Every new layer returns "no opinion" on any error, timeout, invalid model output or missing package, and the baseline route then runs. The decision is logged as `intent_route` (architecture, source, label, scores, model status) next to the existing `qa.answer` line; multi-part answers carry `intent_graph` (node trace) and a per-part grounding record.
* The model call is bounded (temperature 0, 8 s default) and its output is validated (strict schema, no invented or dropped numbers, no dropped negation). Do not raise the timeout above the pipeline's own limits.
* Cost: D about 1.0k tokens per query, E about 0.2k (see BENCHMARK_RESULTS.md). The free tier of the provider used in the benchmark allows 200,000 tokens per day for the model, i.e. fewer than 200 structured calls a day for D.
* Parts of a multi-part question run one after another; do not enable `parallel=True` in production until session state is thread-safe.

## Rollout plan (recommended)
1. Ship with `baseline` (no behaviour change).
2. Implement and run shadow mode (decision computed and logged, never acted on) for E and D; compare the logged decisions with what the baseline did on real traffic.
3. Complete the D/E test split when the provider budget allows (`run_benchmark.py --arch D --split test --llm record`, then `--arch E`), re-run `report.py`, and enable only a variant that is better on held-out data.

## Rollback
Set `ARIA_QUERY_ARCHITECTURE=baseline` (or remove it) and restart: the code path is exactly the previous one.

## Compatibility
Python 3.13, FastAPI as in `requirements.txt`; Docker: add `requirements-intent.txt` to the image only for the variants you enable. Tested on Windows with the project venv; the Linux image was not built (no Docker daemon was available).
