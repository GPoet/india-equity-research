"""Pure valuation formulas, as their authors published them. No data access here.

Rates and growth are decimals (0.12 = 12%) unless a parameter name ends in _pct.
"""

from __future__ import annotations

import math
from collections.abc import Callable

HIGH_GROWTH_YEARS = 5
FORECAST_YEARS = 10


def cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Compound annual growth. None when either end is missing or not positive."""
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def growth_path(
    g1: float, g_terminal: float, years: int = FORECAST_YEARS, high_years: int = HIGH_GROWTH_YEARS
) -> list[float]:
    """g1 for the first high_years, then a straight-line fade to g_terminal by the last year."""
    fade = years - high_years
    return [g1] * high_years + [g1 + (g_terminal - g1) * (i / fade) for i in range(1, fade + 1)]


def two_stage_pv(
    base: float,
    g1: float,
    g_terminal: float,
    rate: float,
    years: int = FORECAST_YEARS,
    high_years: int = HIGH_GROWTH_YEARS,
) -> float:
    """Present value of a cash flow growing per growth_path, plus a Gordon terminal value."""
    if rate <= g_terminal:
        raise ValueError(f"Discount rate {rate:.2%} must exceed terminal growth {g_terminal:.2%}")
    flow, pv = base, 0.0
    for t, g in enumerate(growth_path(g1, g_terminal, years, high_years), start=1):
        flow *= 1 + g
        pv += flow / (1 + rate) ** t
    terminal = flow * (1 + g_terminal) / (rate - g_terminal)
    return pv + terminal / (1 + rate) ** years


def solve_growth(
    value_at: Callable[[float], float], target: float, lo: float = -0.30, hi: float = 0.60
) -> float | None:
    """Growth rate at which value_at(g) == target (bisection; value_at must rise with g)."""
    f_lo, f_hi = value_at(lo) - target, value_at(hi) - target
    if f_lo > 0 or f_hi < 0:
        return None  # target outside what any growth in [lo, hi] can justify
    for _ in range(100):
        mid = (lo + hi) / 2
        if value_at(mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return (lo + hi) / 2


def graham_number(eps: float, bvps: float) -> float | None:
    """Benjamin Graham: max price for a defensive investor = sqrt(22.5 x EPS x BVPS)
    (P/E 15 x P/B 1.5). Undefined for losses or negative book."""
    if eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def graham_formula(eps: float, growth_pct: float, aaa_yield_pct: float) -> float:
    """Graham's revised formula (1974): V = EPS x (8.5 + 2g) x 4.4 / Y.
    8.5 = P/E of a no-growth company; 4.4 = AAA yield when he wrote it; Y = AAA yield now."""
    return eps * (8.5 + 2 * growth_pct) * 4.4 / aaa_yield_pct


LYNCH_MAX_PE = 25.0


def lynch_fair_value(eps: float, growth_pct: float) -> float:
    """Peter Lynch: a fairly priced stock's P/E equals its growth rate (PEG = 1).
    He distrusted growth above ~25%, so the fair P/E is capped there."""
    return eps * min(growth_pct, LYNCH_MAX_PE)


def lynch_ratio(pe: float, growth_pct: float, dividend_yield_pct: float) -> float:
    """Lynch's dividend-adjusted test: (growth + yield) / P/E. Below 1 poor, 1.5 okay, 2+ very good."""
    return (growth_pct + dividend_yield_pct) / pe


RULE1_MARR = 0.15  # Phil Town's minimum acceptable rate of return
RULE1_YEARS = 10


def rule1_sticker(eps: float, growth: float, historical_pe: float | None) -> float:
    """Phil Town, Rule #1: EPS grown 10 years, times the lower of 2x growth (as a P/E) and the
    historical P/E, discounted back at 15% a year. Buy at half of it (margin of safety)."""
    default_pe = 2 * growth * 100
    future_pe = min(default_pe, historical_pe) if historical_pe else default_pe
    future_price = eps * (1 + growth) ** RULE1_YEARS * future_pe
    return future_price / (1 + RULE1_MARR) ** RULE1_YEARS


def justified_pb(roe: float, cost_of_equity: float, growth: float) -> float:
    """Gordon-model fair price-to-book: (ROE - g) / (Ke - g)."""
    if cost_of_equity <= growth:
        raise ValueError("Cost of equity must exceed growth")
    return (roe - growth) / (cost_of_equity - growth)


def residual_income_value(
    book: float,
    roe: float,
    cost_of_equity: float,
    retention: float,
    g_terminal: float,
    years: int = FORECAST_YEARS,
    high_years: int = HIGH_GROWTH_YEARS,
) -> float:
    """Residual income (Edwards-Bell-Ohlson): book value + PV of (ROE - Ke) x opening book.

    ROE holds for high_years, then fades linearly to the cost of equity (competition erodes
    excess returns); book grows by retained earnings. Any residual income left after the
    forecast continues at g_terminal.
    """
    if cost_of_equity <= g_terminal:
        raise ValueError("Cost of equity must exceed terminal growth")
    fade = years - high_years
    roes = [roe] * high_years + [
        roe + (cost_of_equity - roe) * (i / fade) for i in range(1, fade + 1)
    ]
    value, opening = book, book
    ri = 0.0
    for t, r in enumerate(roes, start=1):
        ri = (r - cost_of_equity) * opening
        value += ri / (1 + cost_of_equity) ** t
        opening *= 1 + r * retention
    terminal = ri * (1 + g_terminal) / (cost_of_equity - g_terminal)
    return value + terminal / (1 + cost_of_equity) ** years


def altman_z_em(wc_ta: float, re_ta: float, ebit_ta: float, eq_tl: float) -> float:
    """Altman Z'' for emerging-market and non-manufacturing firms (Altman 2005).
    Zones: above 5.85 safe, 4.15-5.85 grey, below 4.15 distress."""
    return 3.25 + 6.56 * wc_ta + 3.26 * re_ta + 6.72 * ebit_ta + 1.05 * eq_tl


def beneish_m(
    dsri: float,
    gmi: float,
    aqi: float,
    sgi: float,
    depi: float,
    sgai: float,
    tata: float,
    lvgi: float,
) -> float:
    """Beneish M-score (8 variables, 1999). Above -1.78 suggests likely earnings manipulation."""
    return (
        -4.84
        + 0.92 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )
