"""Price inputs for a valuation as of any date: the price, beta, dividends and fiscal-year-end
prices, using only data up to that date. Live valuations call it with today; the backtest
calls it with past dates, so both follow exactly the same rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from eqr.valuation.context import PriceData

DEFAULT_BETA = 1.0
BETA_RANGE = (0.5, 2.0)  # outside this a 2-year beta is noise (thin trading, one-off moves)
BETA_YEARS = 2
MIN_WEEKS = 50


@dataclass(frozen=True)
class MarketSeries:
    closes: pd.Series  # split/bonus-adjusted daily close, indexed by date
    index_closes: pd.Series  # Nifty 50 daily close, indexed by date
    dividends: pd.Series | None  # per share, indexed by ex-date; None = could not fetch


def _upto(s: pd.Series, as_of: date) -> pd.Series:
    return s[[d <= as_of for d in s.index]]


def beta_as_of(stock: pd.Series, index: pd.Series, as_of: date) -> tuple[float, str]:
    start = as_of - timedelta(days=365 * BETA_YEARS)
    window = lambda s: s[[start < d <= as_of for d in s.index]]  # noqa: E731
    joined = pd.concat([window(stock), window(index)], axis=1, join="inner").dropna()
    if joined.empty:
        return DEFAULT_BETA, f"default {DEFAULT_BETA} (no overlapping prices)"
    joined.index = pd.to_datetime(joined.index)
    weekly = joined.resample("W-FRI").last().pct_change().dropna()
    if len(weekly) < MIN_WEEKS:
        return DEFAULT_BETA, f"default {DEFAULT_BETA} (only {len(weekly)} weekly returns)"
    raw = weekly.iloc[:, 0].cov(weekly.iloc[:, 1]) / weekly.iloc[:, 1].var()
    adjusted = 0.67 * raw + 0.33  # Blume: betas drift toward 1
    bounded = min(max(adjusted, BETA_RANGE[0]), BETA_RANGE[1])
    note = "" if bounded == adjusted else f", capped from {adjusted:.2f}"
    return bounded, f"2y weekly vs Nifty 50, raw {raw:.2f}, Blume-adjusted{note}"


def _fy_of(day: date) -> date:
    return date(day.year if day.month <= 3 else day.year + 1, 3, 31)


def price_data_as_of(
    series: MarketSeries,
    fy_ends: list[date],
    as_of: date,
    price: float | None = None,
    price_as_of: str | None = None,
) -> PriceData:
    closes = _upto(series.closes.dropna(), as_of)
    if closes.empty:
        raise ValueError(f"No price on or before {as_of}")
    known_fy = [fy for fy in fy_ends if fy <= as_of]
    fy_prices: dict[date, float] = {}
    for fy in known_fy:
        before = closes[[d <= fy for d in closes.index]]
        if not before.empty and (fy - before.index[-1]).days <= 10:
            fy_prices[fy] = float(before.iloc[-1])
    if series.dividends is None:
        by_fy: dict[date, float] = {}
        dps_ttm: float | None = None  # unknown, not zero
    else:
        divs = _upto(series.dividends, as_of)
        by_fy = {fy: 0.0 for fy in known_fy}
        for d, amount in divs.items():
            fy = _fy_of(d)
            if fy in by_fy:
                by_fy[fy] += float(amount)
        cutoff = as_of - timedelta(days=365)
        dps_ttm = float(sum(a for d, a in divs.items() if d > cutoff))
    beta, source = beta_as_of(series.closes, series.index_closes, as_of)
    return PriceData(
        price=price if price is not None else float(closes.iloc[-1]),
        as_of=price_as_of or closes.index[-1].isoformat(),
        beta=beta,
        beta_source=source,
        dps_ttm=dps_ttm,
        dps_by_fy=by_fy,
        fy_end_prices=fy_prices,
    )
