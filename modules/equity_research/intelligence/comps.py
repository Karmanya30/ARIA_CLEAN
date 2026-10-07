"""
Relative valuation (peer multiples) and the cross-method synthesis.

``Method`` is one valuation result (a per-share low/mid/high in rupees);
``synthesize`` reconciles several of them into a fair-value estimate, a
confidence tier and a directional stance -- or honestly withholds the point
estimate when the methods do not corroborate each other.

Adapted from FinRobot's valuation-synthesis design (Apache-2.0, AI4Finance
Foundation; see THIRD_PARTY_NOTICES.md): the two-tier multiple filtering, the
method-agreement confidence dial, tier-widening verdict bands, and "withhold the
number, never the judgment". Thresholds are re-tuned for Indian large caps.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from modules.equity_research.intelligence.data import Peer

# A multiple outside SANITY is a data artifact (currency/unit mismatch -- Yahoo reports
# INFY's EV/EBITDA as 905x): dropped entirely. A multiple above NM_CAP is real but says
# nothing about a mature company's earnings power (trough earnings, hyper-growth): it
# stays visible in the peer table but is excluded from the median.
SANITY = {"pe": (1.0, 300.0), "fwd_pe": (1.0, 300.0), "pb": (0.1, 50.0), "ev_ebitda": (0.5, 300.0)}
NM_CAP = {"pe": 100.0, "fwd_pe": 100.0, "pb": 50.0, "ev_ebitda": 60.0}
def group_name(group: str) -> str:
    """Readable peer-group name: acronyms upper-cased, the rest title-cased."""
    return group.upper() if group in ("it", "nbfc") else group.replace("_", " ").title()


LABELS = {"pe": "P/E", "fwd_pe": "forward P/E", "pb": "P/B", "ev_ebitda": "EV/EBITDA"}
MIN_PEERS = 3
# Peer multiples only transfer between companies of broadly similar scale and business:
# Reliance (a telecom/retail/energy group) is ~12x the size of the PSU refiners in its
# Yahoo industry, and pricing it off their 9x P/E says nothing about what it is worth.
SIZE_RATIO_MAX = 8.0

# Confidence weight of each method when they corroborate and are blended.
WEIGHTS_DEFAULT = {"dcf": 1.0, "ddm": 1.0, "justified_pb": 0.7, "comps_pe": 0.8, "comps_fpe": 0.8, "comps_pb": 0.8, "comps_ev_ebitda": 0.7}

# Independent lines of evidence. DCF/DDM/justified P/B value the company from its own cash flows or
# book; every peer-multiple method reads the same peer group. Counting P/E, forward P/E and EV/EBITDA as
# three votes against one for the DCF let one peer set outvote the fundamentals (ITC +135%, LT +82%), so the
# cross-method comparison is between the two families, not between individual methods.
INTRINSIC = frozenset({"dcf", "ddm", "justified_pb"})


def _family_mids(methods: list["Method"]) -> dict[str, float]:
    fam: dict[str, list[Method]] = {}
    for m in methods:
        fam.setdefault("intrinsic" if m.key in INTRINSIC else "relative", []).append(m)
    return {f: sum(m.mid * m.weight for m in ms) / sum(m.weight for m in ms) for f, ms in fam.items()}


# Verdict bands (buy_discount, sell_premium) by confidence tier: the less trustworthy the
# fair value, the further price must sit from it before a directional call is made.
# The sell premium exceeds the buy discount in every tier (asymmetric).
VERDICT_BANDS = {"high": (0.20, 0.25), "medium": (0.30, 0.35), "low": (0.40, 0.55), "very_low": (0.50, 0.75)}
AGREE_SPAN = 1.5  # max(mid)/min(mid) up to this: methods corroborate -> confidence-weighted blend
MEDIUM_SPAN = 2.5  # beyond this the approaches do not corroborate each other: withhold the point estimate
VERY_LOW_SPAN = 4.0
MARKET_RATIO_K = 4.0  # fair value more than 4x (or under 1/4) of price: outside model calibration
SINGLE_METHOD_K = 2.0  # a lone method more than 2x off the market has no cross-check
STREET_BAND = (0.6, 1.4)  # a lone method outside this band of the analyst mean target is uncorroborated


@dataclass(frozen=True)
class Method:
    key: str  # dcf | ddm | justified_pb | comps_pe | comps_pb | comps_ev_ebitda
    label: str
    low: float  # rupees per share
    mid: float
    high: float
    weight: float
    basis: str  # one line: what drives this number
    facts: tuple[str, ...] = ()  # ledger ids behind it

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "low": self.low, "mid": self.mid, "high": self.high,
                "weight": self.weight, "basis": self.basis, "facts": list(self.facts)}


@dataclass(frozen=True)
class Synthesis:
    methods: tuple[Method, ...]
    price: float
    central: float | None  # None when the point estimate is withheld
    low: float
    high: float
    spread: float | None  # max(mid)/min(mid) across methods; None for a single method
    tier: str  # high | medium | low | very_low
    upside: float  # fraction; from the nearest range edge when the point is withheld
    rating: str  # BUY | HOLD | SELL  (always directional)
    stance: str  # Undervalued | Fairly valued | Overvalued
    withheld: bool
    notes: tuple[str, ...] = ()
    street: float | None = None

    def to_dict(self) -> dict:
        return {
            "methods": [m.to_dict() for m in self.methods], "price": self.price, "fair_value": self.central,
            "low": self.low, "high": self.high, "spread": self.spread, "confidence": self.tier,
            "upside_pct": self.upside * 100, "rating": self.rating, "stance": self.stance,
            "withheld": self.withheld, "notes": list(self.notes), "street": self.street,
        }


# ── peer multiples ─────────────────────────────────────────────────────────
@dataclass
class MultipleStats:
    kind: str
    used: list[float] = field(default_factory=list)
    dropped: list[tuple[str, float, str]] = field(default_factory=list)  # (symbol, value, reason)
    median: float | None = None
    low: float | None = None
    high: float | None = None

    @property
    def usable(self) -> bool:
        return len(self.used) >= MIN_PEERS


SIZE_BAND = (0.2, 5.0)  # a peer worth under a fifth or over five times the company is not a like-for-like comparison


def _size_ok(peer: Peer, mcap_cr: float | None) -> bool:
    return not (mcap_cr and peer.mcap_cr) or SIZE_BAND[0] <= peer.mcap_cr / mcap_cr <= SIZE_BAND[1]


def multiple_stats(kind: str, peers: list[Peer], mcap_cr: float | None = None) -> MultipleStats:
    """Median of the peers' multiple. Peers far from the company in size are left out (a mid-cap's 45x P/E says little about a
    mega-cap), unless that would leave too few to compute a median."""
    stats = MultipleStats(kind)
    lo, hi = SANITY[kind]
    sized = [p for p in peers if _size_ok(p, mcap_cr) and getattr(p, kind) is not None]
    like = sized if len(sized) >= MIN_PEERS else peers
    for peer in peers:
        v = getattr(peer, kind)
        if v is None:
            continue
        if peer not in like:
            stats.dropped.append((peer.symbol, v, "much larger or smaller than the company (outside 0.2x to 5x its market value)"))
            continue
        if not lo <= v <= hi:
            stats.dropped.append((peer.symbol, v, "outside sanity bounds (likely currency/unit artifact)"))
        elif v > NM_CAP[kind]:
            stats.dropped.append((peer.symbol, v, f"above {NM_CAP[kind]:g}x (not meaningful for a median)"))
        else:
            stats.used.append(v)
    if stats.usable:
        stats.median = statistics.median(stats.used)
        if len(stats.used) >= 4:
            q = statistics.quantiles(stats.used, n=4, method="inclusive")
            stats.low, stats.high = q[0], q[2]
        else:
            stats.low, stats.high = min(stats.used), max(stats.used)
    return stats


def comps_table(peers: list[Peer], stats: dict[str, MultipleStats]) -> dict:
    """Peer table for the report: each peer's size, operating metrics and multiples, with the multiples
    excluded from a median marked."""
    kinds = ("pe", "fwd_pe", "pb", "ev_ebitda")
    dropped = {(k, sym) for k, st in stats.items() for sym, _, _ in st.dropped}
    rows = [{"symbol": p.symbol, "name": p.name, "mcap_cr": p.mcap_cr, "ev_cr": p.ev_cr, "revenue_cr": p.revenue_cr,
             "ebitda_cr": p.ebitda_cr, "net_income_cr": p.net_income_cr, "ev_sales": p.ev_sales, "rev_growth": p.rev_growth,
             "op_margin": p.op_margin, "roe": p.roe, **{k: getattr(p, k) for k in kinds},
             "excluded": [k for k in kinds if (k, p.symbol) in dropped]} for p in peers]
    return {
        "peers": rows,
        "medians": {k: st.median for k, st in stats.items()},
        "counts": {k: len(st.used) for k, st in stats.items()},
        "excluded": {k: [{"symbol": s, "value": v, "reason": r} for s, v, r in st.dropped] for k, st in stats.items()},
    }


# ── synthesis ──────────────────────────────────────────────────────────────
def verdict(upside: float, tier: str) -> tuple[str, str]:
    buy, sell = VERDICT_BANDS[tier]
    if upside >= buy:
        return "BUY", "Undervalued"
    if upside <= -sell:
        return "SELL", "Overvalued"
    return "HOLD", "Fairly valued"


def synthesize(methods: list[Method], price: float, street: float | None = None) -> Synthesis:
    """Reconcile methods into one call. Never returns a non-directional verdict:
    uncertainty lowers the tier (widening the bands) or withholds the point estimate."""
    if not methods:
        raise ValueError("at least one valuation method is required")
    if price <= 0:
        raise ValueError("price must be positive")
    mids = [m.mid for m in methods]
    notes: list[str] = []
    withheld = False

    if len(methods) == 1:
        m = methods[0]
        spread = None
        tier = "medium"
        central: float | None = m.mid
        low, high = m.low, m.high
        notes.append(f"Only one method ({m.label}) could be computed, so there is no cross-check.")
        if street and not STREET_BAND[0] <= m.mid / street <= STREET_BAND[1]:
            tier = "low"
            notes.append(f"{m.label} also sits outside {STREET_BAND[0]:.0%}-{STREET_BAND[1]:.0%} of the analyst mean target, so it is not corroborated by the sell-side either; confidence is low.")
        if not 1 / SINGLE_METHOD_K <= m.mid / price <= SINGLE_METHOD_K:
            tier, withheld, central = "low", True, None
            notes.append(f"{m.label} sits more than {SINGLE_METHOD_K:g}x away from the market price with nothing to corroborate it; the point estimate is withheld.")
    else:
        families = _family_mids(methods)
        basis = list(families.values()) if len(families) >= 2 else mids  # two independent families, else the methods themselves
        spread = max(basis) / min(basis) if min(basis) > 0 else float("inf")
        low, high = min(mids), max(mids)
        if spread <= AGREE_SPAN:
            tier = "high"
            central = statistics.fmean(basis) if len(families) >= 2 else sum(m.mid * m.weight for m in methods) / sum(m.weight for m in methods)
        else:
            tier = "medium" if spread <= MEDIUM_SPAN else ("low" if spread <= VERY_LOW_SPAN else "very_low")
            central = statistics.median(basis)
            what = "The intrinsic and peer-multiple approaches" if len(families) >= 2 else "The methods"
            notes.append(f"{what} diverge {spread:.1f}x, so the central estimate is their median, not a blend, and confidence is {tier.replace('_', ' ')}.")
        if spread > MEDIUM_SPAN:
            withheld, central = True, None
            notes.append(f"They diverge more than {MEDIUM_SPAN:g}x and do not corroborate each other, so no point estimate is given -- only the range; the direction comes from where the price sits relative to it.")

    if central is not None and not 1 / MARKET_RATIO_K <= central / price <= MARKET_RATIO_K:
        tier = "low" if tier in ("high", "medium") else tier
        withheld, central = True, None
        notes.append(f"The fair value is more than {MARKET_RATIO_K:g}x away from the market price, outside what these models are calibrated for; the point estimate is withheld.")

    if central is not None:
        upside = central / price - 1
    else:  # direction from the nearest edge of the range, never from the withheld interior
        upside = 0.0 if low <= price <= high else (low / price - 1 if price < low else high / price - 1)
    rating, stance = verdict(upside, tier)
    return Synthesis(tuple(methods), price, central, low, high, spread, tier, upside, rating, stance, withheld, tuple(notes), street)
