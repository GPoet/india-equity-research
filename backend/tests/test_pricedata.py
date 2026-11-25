from datetime import date

import numpy as np
import pandas as pd
import pytest

from eqr.valuation.pricedata import MarketSeries, beta_as_of, price_data_as_of


def series():
    days = pd.bdate_range("2022-01-03", "2026-11-20")
    rng = np.random.default_rng(3)
    m = rng.normal(0, 0.01, len(days))
    idx = pd.Series(100 * np.exp(np.cumsum(m)), index=days.date)
    stock = pd.Series(
        50 * np.exp(np.cumsum(1.5 * m + rng.normal(0, 0.002, len(days)))), index=days.date
    )
    divs = pd.Series(
        [5.0, 6.0, 7.0], index=[date(2024, 7, 10), date(2025, 7, 10), date(2026, 7, 10)]
    )
    return MarketSeries(stock, idx, divs)


def test_beta_close_to_true_value_then_blume() -> None:
    beta, src = beta_as_of(series().closes, series().index_closes, date(2026, 11, 20))
    assert beta == pytest.approx(0.67 * 1.5 + 0.33, abs=0.08)
    assert "Blume" in src


def test_point_in_time_has_no_future_data() -> None:
    s = series()
    pd_2025 = price_data_as_of(s, [date(2025, 3, 31), date(2026, 3, 31)], date(2025, 8, 1))
    assert pd_2025.price == pytest.approx(
        float(s.closes[s.closes.index <= date(2025, 8, 1)].iloc[-1])
    )
    assert pd_2025.dps_ttm == pytest.approx(6.0)  # only the July 2025 dividend in the past year
    assert date(2026, 3, 31) not in pd_2025.fy_end_prices  # that year had not ended
    assert date(2026, 3, 31) not in pd_2025.dps_by_fy


def test_dividends_unknown_stays_none() -> None:
    s = series()
    out = price_data_as_of(
        MarketSeries(s.closes, s.index_closes, None), [date(2025, 3, 31)], date(2026, 11, 20)
    )
    assert out.dps_ttm is None and out.dps_by_fy == {}


def test_explicit_live_price_wins() -> None:
    out = price_data_as_of(
        series(), [], date(2026, 11, 20), price=123.0, price_as_of="2026-11-20T15:00"
    )
    assert out.price == 123.0 and out.as_of == "2026-11-20T15:00"
