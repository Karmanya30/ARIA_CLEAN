"""
Financial-intelligence layer for Module 4 (Equity Research).

Turns a company into an auditable research report: multi-year statement
analysis, deterministic valuation (DCF / DDM / comps), a bull/bear/judge debate,
a verification gate, and a provenance ledger -- on top of, not instead of, the
existing Module 4 pipeline. Entry point: ``pipeline.run_research``.

Principle (adapted from FinRobot, Apache-2.0 -- see THIRD_PARTY_NOTICES.md):
numbers are computed by code, judgment is written by the LLM, and every figure
in the output traces back to a ``facts.Fact``.
"""
