import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from eqr.forecast.features import (
    earnings_surprise,
    jump_variance,
    next_results_estimate,
    price_features,
)


def series(values, start=date(2023, 1, 2)):
    days, d = [], start
    while len(days) < len(values):
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return pd.Series(values, index=days, dtype=float)


def test_relative_momentum_and_reversal() -> None:
    n = 300
    stock = series(np.exp(np.linspace(0, 0.30, n)) * 100)  # +30% over the period, steady
    index = series(np.full(n, 1000.0))
    f = price_features(stock, index, stock.index[-1])
    # 12-1 momentum: from 252 to 21 trading days ago, vs a flat index
    expected = 0.30 * (252 - 21) / (n - 1)
    assert f["mom_12_1"] == pytest.approx(expected, rel=1e-6)
    assert f["rev_1m"] == pytest.approx(0.30 * 21 / (n - 1), rel=1e-6)
    assert f["vol_daily"] < 0.002  # smooth path: only the drift itself (EWMA is not demeaned)


def test_price_features_need_a_year() -> None:
    s = series(np.full(100, 100.0))
    assert price_features(s, s, s.index[-1]) is None


def test_price_features_ignore_future() -> None:
    n = 400
    stock = series(np.r_[np.full(300, 100.0), np.full(100, 200.0)])
    index = series(np.full(n, 1000.0))
    f = price_features(stock, index, stock.index[299])
    assert f["rev_1m"] == 0.0 and f["mom_12_1"] == 0.0


def q(end, pat):
    return (end, pat)


def test_earnings_surprise_standardised_yoy_change() -> None:
    ends = [date(2022 + (m - 1) // 12, (m - 1) % 12 + 1, 1) for m in range(3, 3 + 3 * 12, 3)]
    ends = [date(e.year, e.month, 28) for e in ends]  # quarter-ish ends, consecutive
    pats = [100 + 10 * i + (0, 3, -3)[i % 3] for i in range(len(ends))]  # YoY change ~40
    pats[-1] += 40  # latest quarter jumps far above its usual change
    got = earnings_surprise(list(zip(ends, pats)))
    assert got == 3.0  # clipped
    flat = [100 + 10 * i for i in range(len(ends))]  # identical changes: no spread to judge by
    assert earnings_surprise(list(zip(ends, flat))) is None


def test_earnings_surprise_needs_history() -> None:
    assert earnings_surprise([(date(2024, 3, 31), 1.0), (date(2023, 3, 31), 0.5)]) is None


def test_next_results_estimate_uses_typical_lag() -> None:
    filed = [
        (date(2024, 3, 31), date(2024, 4, 25)),
        (date(2024, 6, 30), date(2024, 7, 25)),
        (date(2024, 9, 30), date(2024, 10, 25)),
    ]
    assert next_results_estimate(filed) == date(2024, 12, 31) + timedelta(days=25)


def test_jump_variance_from_results_days() -> None:
    n = 300
    rng = np.random.default_rng(0)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    stock = series(base)
    index = series(np.full(n, 1000.0))
    days = [stock.index[i] for i in (50, 110, 170, 230)]
    for d in days:  # 8% jump the day after each filing
        stock.loc[stock.index > d] *= 1.08
    jv = jump_variance(stock, index, days, stock.index[-1])
    assert jv == pytest.approx(math.log(1.08) ** 2, rel=0.35)
