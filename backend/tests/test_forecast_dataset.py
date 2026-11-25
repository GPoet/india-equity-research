import math
from datetime import date, timedelta

import pandas as pd
import pytest

from eqr.forecast.dataset import outcomes, value_input
from eqr.valuation.pricedata import MarketSeries


def bdays(n, start=date(2024, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_outcomes_are_excess_log_returns_and_none_when_future_unknown() -> None:
    days = bdays(30)
    stock = pd.Series([100.0] * 5 + [110.0] * 25, index=days)
    index = pd.Series([1000.0] * 30, index=days)
    out = outcomes(MarketSeries(stock, index, None), days[0])
    assert out["y_1m"] == pytest.approx(math.log(1.1))
    assert out["y_2m"] is None  # 42 trading days have not happened


def test_value_input_only_from_usable_valuations() -> None:
    good = {"upside": 0.25, "confidence": "high", "used": ["dcf"]}
    assert value_input(good) == pytest.approx(math.log(1.25))
    assert value_input({**good, "confidence": "low"}) is None
    assert value_input({**good, "upside": -0.95}) == -1.5  # clipped
    assert value_input(None) is None
