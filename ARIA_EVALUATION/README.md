# ARIA pre-launch evaluation

Independent evaluation of ARIA for launch readiness. Start with `EXECUTION_STATUS.md` (current phase, what is done, how to resume).

* Discovery: `PROJECT_DISCOVERY.md`, `ARCHITECTURE_MAP.md`, `FEATURE_INVENTORY.md`, `API_INVENTORY.md`, `DATA_SOURCE_INVENTORY.md`, `DEPENDENCY_INVENTORY.md`
* Specialist audits: `reports/`
* Benchmarks (Phase B): `evaluation/`
* Tests written by the evaluation: `tests/`
* Improvement backlog (Phase C): `improvements/`
* Agent definitions: `.claude/agents/` (regenerate with `make_agents.py`)

Rules: findings are labelled VERIFIED / SUSPECTED / RECOMMENDATION / UNTESTED / BLOCKED; application code is not changed in Phase A.
