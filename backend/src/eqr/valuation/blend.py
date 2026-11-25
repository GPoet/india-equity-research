"""Combine value lenses into a fair-value range, a signal and a confidence level.

Weights favour cash-flow models for operating companies and book-value models for
lenders; the classic investor formulas carry smaller weights as cross-checks.
"""

from __future__ import annotations

import statistics
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


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def blend(
    lenses: list[LensResult], price: float, financial: bool, margin_of_safety: float
) -> Blend:
    weights = WEIGHTS_FINANCIAL if financial else WEIGHTS_OPERATING
    core = CORE_FINANCIAL if financial else CORE_OPERATING
    values = {
        r.key: r.value
        for r in lenses
        if r.applicable
        and r.kind == "value"
        and r.key in weights
        and r.value is not None
        and r.value > 0
    }
    flags = tuple(
        f"{r.name}: {r.verdict}"
        for r in lenses
        if r.applicable and r.verdict in RED_FLAG_VERDICTS.get(r.key, set())
    )
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
    vals = list(values.values())
    low = min(_percentile(vals, 0.25), mid)
    high = max(_percentile(vals, 0.75), mid)

    signal = "Undervalued" if price < low else "Overvalued" if price > high else "Fairly valued"

    reasons: list[str] = []
    score = 3
    core_used = core & values.keys()
    if len(core_used) < 2:
        score -= 1
        reasons.append(
            f"Only {len(core_used)} of the core models ({', '.join(sorted(core))}) could run"
        )
    spread = (high - low) / mid if mid else 0
    if spread > DISAGREEMENT:
        score -= 1
        reasons.append(f"Models disagree: range is {spread:.0%} of the mid value")
    if len(values) < 5:
        score -= 1
        reasons.append(f"Only {len(values)} lenses contributed")
    if flags:
        score -= 1
        reasons.append("Red flags present")
    if statistics.pstdev(vals) / statistics.mean(vals) > 0.75:
        score -= 1
        reasons.append("Lens values are widely scattered")
    confidence = "high" if score >= 3 else "medium" if score == 2 else "low"

    return Blend(
        low=low,
        mid=mid,
        high=high,
        buy_below=mid * (1 - margin_of_safety),
        signal=signal,
        confidence=confidence,
        upside=mid / price - 1 if price else None,
        used=used,
        reasons=tuple(reasons),
        red_flags=flags,
    )
