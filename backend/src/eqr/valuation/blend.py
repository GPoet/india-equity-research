"""Combine value lenses into a fair-value range, a signal and a confidence level.

Weights favour cash-flow models for operating companies and book-value models for
lenders; the classic investor formulas carry smaller weights as cross-checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from eqr.valuation.models import LensResult

WEIGHTS_OPERATING = {
    "dcf": 0.30,
    "owner_earnings": 0.25,
    "epv": 0.15,
    "graham_formula": 0.075,
    "lynch": 0.075,
    "rule1": 0.075,
    "ddm": 0.05,
    "graham_number": 0.025,
}
WEIGHTS_FINANCIAL = {
    "residual_income": 0.40,
    "justified_pb": 0.25,
    "ddm": 0.15,
    "graham_formula": 0.075,
    "lynch": 0.075,
    "graham_number": 0.05,
}
CORE_OPERATING = {"dcf", "owner_earnings", "epv"}
CORE_FINANCIAL = {"residual_income", "justified_pb"}
MIN_LENSES = 3
DISAGREEMENT = 0.6  # (high - low) / mid above this means the models disagree a lot

RED_FLAG_VERDICTS = {
    "altman_z": {"distress"},
    "beneish_m": {"possible manipulation"},
    "piotroski": {"weak"},
    "roic": {"destroys value"},
    "bank_asset_quality": {"weak"},
    "promoter": {"heavy pledge", "promoter selling"},
}


@dataclass(frozen=True)
class Blend:
    low: float | None
    mid: float | None
    high: float | None
    buy_below: float | None
    signal: str
    confidence: str
    upside: float | None  # mid / price - 1
    used: dict[str, float] = field(default_factory=dict)  # lens -> normalised weight
    reasons: tuple[str, ...] = ()
    red_flags: tuple[str, ...] = ()


def _weighted_percentile(pairs: list[tuple[float, float]], q: float) -> float:
    """Percentile of values where each value counts by its weight (pairs of value, weight)."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= q * total:
            return value
    return ordered[-1][0]


def blend(
    lenses: list[LensResult],
    price: float,
    financial: bool,
    margin_of_safety: float,
    data_warnings: int = 0,
) -> Blend:
    weights = WEIGHTS_FINANCIAL if financial else WEIGHTS_OPERATING
    core = CORE_FINANCIAL if financial else CORE_OPERATING
    raw = {
        r.key: r.value
        for r in lenses
        if r.applicable
        and r.kind == "value"
        and r.key in weights
        and r.value is not None
        and math.isfinite(r.value)
    }
    # A negative value (e.g. net debt above enterprise value) is a real answer: the model
    # says the equity is worth nothing. Keep it as zero and flag it; never drop it silently.
    negative = sorted(k for k, val in raw.items() if val < 0)
    values = {k: max(val, 0.0) for k, val in raw.items()}
    flags = tuple(
        f"{r.name}: {r.verdict}"
        for r in lenses
        if r.applicable and r.verdict in RED_FLAG_VERDICTS.get(r.key, set())
    ) + tuple(f"{k} gives a negative equity value" for k in negative)
    if len(values) < MIN_LENSES:
        return Blend(
            None,
            None,
            None,
            None,
            "Not enough data",
            "low",
            None,
            reasons=(f"Only {len(values)} valuation lens(es) could run; need {MIN_LENSES}",),
            red_flags=flags,
        )

    total = sum(weights[k] for k in values)
    used = {k: weights[k] / total for k in values}
    mid = sum(values[k] * w for k, w in used.items())
    pairs = [(values[k], used[k]) for k in values]
    low = min(_weighted_percentile(pairs, 0.25), mid)
    high = max(_weighted_percentile(pairs, 0.75), mid)
    buy_below = mid * (1 - margin_of_safety)
    sell_above = mid * (1 + margin_of_safety)

    # Outside the range AND past the margin of safety, so agreeing models and small price
    # moves cannot flip the signal.
    if price < min(low, buy_below):
        signal = "Undervalued"
    elif price > max(high, sell_above):
        signal = "Overvalued"
    else:
        signal = "Fairly valued"

    reasons: list[str] = []
    score = 3
    core_used = core & values.keys()
    if len(core_used) < 2:
        score -= 1
        reasons.append(
            f"Only {len(core_used)} of the core models ({', '.join(sorted(core))}) could run"
        )
    spread = (high - low) / mid if mid else 0
    if spread > DISAGREEMENT or not mid:
        score -= 1
        reasons.append(f"Models disagree: range is {spread:.0%} of the mid value")
    if len(values) < 5:
        score -= 1
        reasons.append(f"Only {len(values)} lenses contributed")
    if flags:
        score -= 1
        reasons.append("Red flags present")
    if data_warnings:
        score -= 1
        reasons.append(f"{data_warnings} data-quality warning(s)")
    confidence = "high" if score >= 3 else "medium" if score == 2 else "low"

    return Blend(
        low=low,
        mid=mid,
        high=high,
        buy_below=buy_below,
        signal=signal,
        confidence=confidence,
        upside=mid / price - 1 if price else None,
        used=used,
        reasons=tuple(reasons),
        red_flags=flags,
    )
