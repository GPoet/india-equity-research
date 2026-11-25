"""Inputs to the 1-2 month forecast, computed only from data known on the as-of date, so the
live page and the history test use exactly the same numbers.

Each input has published evidence at this horizon:
- 12-1 month relative momentum (Jegadeesh-Titman; NSE runs momentum indices on it)
- 1-month reversal (short-term reversal effect)
- earnings surprise, for the ~60 days after results (post-earnings-announcement drift)
- volatility and results-day jumps, for the width of the range (not the direction)
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

import numpy as np
import pandas as pd

YEAR, MONTH = 252, 21  # trading days
EWMA_LAMBDA = 0.94  # RiskMetrics daily decay
SURPRISE_CLIP = 3.0
SURPRISE_DAYS = 90  # calendar days after a results filing during which drift is measured
MIN_SURPRISE_HISTORY = 4
MIN_JUMPS = 4


def _upto(s: pd.Series, as_of: date) -> pd.Series:
    return s[[d <= as_of for d in s.index]].dropna()


def price_features(stock: pd.Series, index: pd.Series, as_of: date) -> dict[str, float] | None:
    """Relative momentum, reversal and daily volatility (total and vs the Nifty). None when
    there is not a year of prices."""
    joined = pd.concat([_upto(stock, as_of), _upto(index, as_of)], axis=1, join="inner").dropna()
    if len(joined) <= YEAR:
        return None
    logp = np.log(joined.to_numpy())
    rel = logp[:, 0] - logp[:, 1]  # log(stock / Nifty)
    mom = rel[-1 - MONTH] - rel[-1 - YEAR]
    rev = rel[-1] - rel[-1 - MONTH]
    r_stock = np.diff(logp[-YEAR - 1 :, 0])
    r_rel = np.diff(rel[-YEAR - 1 :])
    return {
        "mom_12_1": float(mom),
        "rev_1m": float(rev),
        "vol_daily": _blend_vol(r_stock),
        "vol_excess_daily": _blend_vol(r_rel),
    }


def _blend_vol(returns: np.ndarray) -> float:
    """Half recent (EWMA), half the past year: reacts to new turbulence without overreacting."""
    weights = EWMA_LAMBDA ** np.arange(len(returns))[::-1]
    ewma_var = float(np.sum(weights * returns**2) / np.sum(weights))
    year_var = float(np.var(returns))
    return math.sqrt(0.5 * ewma_var + 0.5 * year_var)


def _year_ago(by_end: dict[date, float], end: date) -> float | None:
    for d, v in by_end.items():
        if abs((d - (end - timedelta(days=365))).days) <= 10:
            return v
    return None


def earnings_surprise(quarters: list[tuple[date, float]]) -> float | None:
    """Latest quarter's year-on-year profit change, standardised by the company's own past
    year-on-year changes (a 'standardised unexpected earnings' score). Profit, not EPS, so
    bonus issues do not distort it."""
    by_end = {d: v for d, v in quarters if v is not None}
    ends = sorted(by_end, reverse=True)
    changes = []
    for end in ends:
        prior = _year_ago(by_end, end)
        if prior is not None:
            changes.append(by_end[end] - prior)
    if len(changes) < MIN_SURPRISE_HISTORY + 1:
        return None
    latest, past = changes[0], changes[1 : 1 + 8]
    spread = statistics.pstdev(past)
    if spread == 0:
        return None
    z = (latest - statistics.fmean(past)) / spread
    return max(-SURPRISE_CLIP, min(SURPRISE_CLIP, z))


def next_results_estimate(filed: list[tuple[date, date]]) -> date | None:
    """(period_end, filed_on) pairs -> expected date of the next results: the quarter after the
    latest, plus the company's typical filing lag."""
    if not filed:
        return None
    latest_end = max(e for e, _ in filed)
    lag = statistics.median((f - e).days for e, f in filed)
    m = latest_end.month + 3
    nxt_month = date(latest_end.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
    nxt_end = date(nxt_month.year + nxt_month.month // 12, nxt_month.month % 12 + 1, 1) - timedelta(
        days=1
    )
    return nxt_end + timedelta(days=int(lag))


def jump_variance(
    stock: pd.Series, index: pd.Series, filing_days: list[date], as_of: date
) -> float | None:
    """Extra variance a results day adds: mean squared move vs the Nifty from the close before
    the filing day to the first close after it, minus what two ordinary days would give."""
    joined = pd.concat([_upto(stock, as_of), _upto(index, as_of)], axis=1, join="inner").dropna()
    if len(joined) < 60:
        return None
    rel = pd.Series(
        np.log(joined.iloc[:, 0].to_numpy() / joined.iloc[:, 1].to_numpy()), index=joined.index
    )
    days = list(rel.index)
    moves = []
    for fd in filing_days:
        before = [d for d in days if d < fd]
        after = [d for d in days if d > fd]
        if before and after and fd < as_of:
            moves.append(rel[after[0]] - rel[before[-1]])
    if len(moves) < MIN_JUMPS:
        return None
    normal = float(np.var(np.diff(rel.to_numpy()[-YEAR:])))
    return max(float(np.mean(np.square(moves))) - 2 * normal, 0.0)
