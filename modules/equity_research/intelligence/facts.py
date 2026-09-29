"""
Provenance ledger for the equity-research intelligence layer.

Every number a report can show is a ``Fact`` created here, with the metadata
that lets a reader (and the audit layer) tell what kind of number it is:

    raw         taken from a data source as published (screener.in, yfinance)
    calculated  produced by deterministic code from other facts (``inputs`` ids)
    assumption  a modelling choice, with the reason it was made

The LLM never creates facts. It is shown ``Fact.id`` + label + formatted value
and can only *cite* them (``{{E12}}``); the renderer substitutes the value.
That is the mechanism that keeps invented figures out of the narrative.

Design adapted from FinRobot's "numbers are code-calculated, narratives are
LLM-assisted, every output is provenance-tracked" principle (Apache-2.0,
AI4Finance Foundation) -- see THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Iterable, Iterator

RAW = "raw"
CALCULATED = "calculated"
ASSUMPTION = "assumption"
_KINDS = (RAW, CALCULATED, ASSUMPTION)


def fmt(value: float | None, unit: str) -> str:
    """The one place a number becomes display text (report, evidence chips, prompts)."""
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if unit == "%":
        return f"{sign}{v:.1f}%"
    if unit == "x":
        return f"{sign}{v:.1f}x"
    if unit == "₹":
        return f"{sign}₹{v:,.2f}"
    if unit == "₹ Cr":
        return f"{sign}₹{v:,.0f} Cr" if v >= 100 else f"{sign}₹{v:,.1f} Cr"
    if unit == "days":
        return f"{sign}{v:.0f} days"
    if unit == "Cr shares":
        return f"{sign}{v:,.1f} Cr shares"
    return f"{sign}{v:,.2f}{(' ' + unit) if unit else ''}"


@dataclass(frozen=True)
class Fact:
    id: str
    label: str
    value: float
    unit: str
    period: str  # "FY2026", "TTM", "as of 2026-09-29", or "" when timeless
    source: str  # e.g. "screener.in (consolidated)", "yfinance", "ARIA valuation model"
    kind: str  # raw | calculated | assumption
    method: str = ""  # how it was calculated / why it was assumed
    inputs: tuple[str, ...] = ()  # fact ids a calculated fact was derived from
    tag: str = ""  # "model_input" marks the figures a valuation model was fed (the assumptions table)

    @property
    def text(self) -> str:
        return fmt(self.value, self.unit)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["inputs"] = list(self.inputs)
        d["text"] = self.text
        return d


@dataclass(frozen=True)
class Table:
    """A multi-year table shown as-is. Provenance is table-level: one source and
    basis for the whole table, and each row says whether it is raw or calculated."""

    title: str
    columns: list[str]
    rows: list[dict]  # {"label", "unit", "kind", "values": {column: float | None}}
    source: str

    def to_dict(self) -> dict:
        return {"title": self.title, "columns": self.columns, "rows": self.rows, "source": self.source}


@dataclass
class Ledger:
    _facts: dict[str, Fact] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)  # label -> why it is not available

    def add(
        self,
        label: str,
        value: float,
        unit: str,
        period: str,
        source: str,
        kind: str,
        *,
        method: str = "",
        inputs: Iterable[Fact | str] = (),
        tag: str = "",
    ) -> Fact:
        # A non-finite value or a missing source is a bug in the caller, not a data problem:
        # data problems go through ``miss`` so the report says "n/a" instead of a number.
        if value is None or not math.isfinite(value):
            raise ValueError(f"fact {label!r} needs a finite value, got {value!r}")
        if not source:
            raise ValueError(f"fact {label!r} needs a source")
        if kind not in _KINDS:
            raise ValueError(f"fact {label!r} has unknown kind {kind!r}")
        fact = Fact(
            id=f"E{len(self._facts) + 1}",
            label=label,
            value=float(value),
            unit=unit,
            period=period,
            source=source,
            kind=kind,
            method=method,
            inputs=tuple(i.id if isinstance(i, Fact) else i for i in inputs),
            tag=tag,
        )
        self._facts[fact.id] = fact
        return fact

    def miss(self, label: str, reason: str) -> None:
        self.missing.setdefault(label, reason)

    def get(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def find(self, label: str, period: str | None = None) -> Fact | None:
        """Latest fact with this label (optionally for one period)."""
        for fact in reversed(list(self._facts.values())):
            if fact.label == label and (period is None or fact.period == period):
                return fact
        return None

    def __iter__(self) -> Iterator[Fact]:
        return iter(self._facts.values())

    def __len__(self) -> int:
        return len(self._facts)

    def evidence_lines(self, facts: Iterable[Fact] | None = None) -> str:
        """Compact evidence table for prompts: one fact per line, id first."""
        lines = []
        for f in facts if facts is not None else self:
            basis = f"{f.kind}{' · ' + f.method if f.method else ''}"
            period = f" [{f.period}]" if f.period else ""
            lines.append(f"{f.id}: {f.label}{period} = {f.text} ({basis})")
        return "\n".join(lines)

    def to_dicts(self) -> list[dict]:
        return [f.to_dict() for f in self]
