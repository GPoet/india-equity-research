"""Forecast inputs (and, for history, outcomes) for one company on one date, from data known
then. The live page and the fitting script both call observation(), so they cannot drift."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from eqr.backtest import _filed, refs_known_on, usable
from eqr.forecast.features import (
    SURPRISE_DAYS,
    earnings_surprise,
    jump_variance,
    next_results_estimate,
    price_features,
)
from eqr.forecast.model import HORIZONS
from eqr.fundamentals import build_fundamentals, main_basis, owners_profit
from eqr.sources.filings import FilingRef
from eqr.valuation.pricedata import MarketSeries
from eqr.xbrl import Filing

VALUE_CLIP = (-1.5, 1.0)


def value_input(valuation_row: dict[str, Any] | None) -> float | None:
    """log(1 + upside) from a usable valuation, clipped; None when the valuation is not usable."""
    if not valuation_row or valuation_row.get("upside") is None or not usable(valuation_row)[0]:
        return None
    up = max(valuation_row["upside"], -0.99)
    return max(VALUE_CLIP[0], min(VALUE_CLIP[1], math.log1p(up)))


def _results_filings(refs: list[FilingRef]) -> list[tuple[date, date]]:
    """(period_end, first filing day) per quarter: when the results became public."""
    first: dict[date, date] = {}
    for r in refs:
        f = _filed(r)
        if f is not None:
            d = f.date()
            first[r.period_end] = min(first.get(r.period_end, d), d)
    return sorted(first.items())


def outcomes(series: MarketSeries, as_of: date) -> dict[str, float | None]:
    """Log return vs the Nifty over each horizon, from the as-of close (None if not yet known)."""
    joined = pd.concat([series.closes, series.index_closes], axis=1, join="inner").dropna()
    days = list(joined.index)
    start = [i for i, d in enumerate(days) if d <= as_of]
    out: dict[str, float | None] = {}
    for name, n in HORIZONS.items():
        if not start or start[-1] + n >= len(days) or (as_of - days[start[-1]]).days > 7:
            out[f"y_{name}"] = None
            continue
        a, b = joined.iloc[start[-1]], joined.iloc[start[-1] + n]
        out[f"y_{name}"] = float(np.log(b.iloc[0] / a.iloc[0]) - np.log(b.iloc[1] / a.iloc[1]))
    return out


def observation(
    symbol: str,
    pairs: list[tuple[FilingRef, Filing]],
    series: MarketSeries,
    as_of: date,
    valuation_row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    px = price_features(series.closes, series.index_closes, as_of)
    if px is None:
        return None
    known = refs_known_on([r for r, _ in pairs], as_of)
    known_urls = {r.xbrl_url for r in known}
    chosen = [(r, f) for r, f in pairs if r.xbrl_url in known_urls]
    consolidated = main_basis(r for r, _ in chosen)
    chosen = [(r, f) for r, f in chosen if r.consolidated == consolidated]
    filings = _results_filings(known)

    surprise = None
    if chosen and filings and (as_of - filings[-1][1]).days <= SURPRISE_DAYS:
        try:
            f = build_fundamentals(symbol, chosen)
            surprise = earnings_surprise(
                [(q.period_end, owners_profit(q.income)) for q in f.quarters]
            )
        except ValueError:
            surprise = None

    nxt = next_results_estimate(filings)
    events = {
        f"event_{n}": int(
            nxt is not None and as_of < nxt <= as_of + timedelta(days=round(n * 7 / 5))
        )
        for n in HORIZONS.values()
    }
    return {
        "symbol": symbol,
        "day": as_of.isoformat(),
        **px,
        "surprise": surprise,
        "value": value_input(valuation_row),
        "jump_var": jump_variance(
            series.closes, series.index_closes, [d for _, d in filings], as_of
        ),
        "next_results_est": nxt.isoformat() if nxt else None,
        **events,
    }
