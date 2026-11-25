from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from eqr.sources.bhavcopy import bhavcopy_urls, parse_bhavcopy
from eqr.valuation.pricedata import MarketSeries, rebased

FIX = Path(__file__).parent / "fixtures" / "nse"


def test_legacy_format_parses() -> None:
    bars = parse_bhavcopy((FIX / "bhav_legacy_20210813_sample.csv").read_text())
    hdfc = bars["HDFCBANK"]
    assert hdfc.close == pytest.approx(1526.2)
    assert hdfc.trade_date == date(2021, 8, 13)
    assert hdfc.isin == "INE040A01034"


def test_urls_by_era() -> None:
    old = bhavcopy_urls(date(2021, 8, 13))
    assert "historical/EQUITIES/2021/AUG/cm13AUG2021bhav.csv.zip" in old[0]
    new = bhavcopy_urls(date(2025, 1, 10))
    assert "BhavCopy_NSE_CM_0_0_0_20250110_F_0000" in new[0]
    assert len(old) == 2 and len(new) == 2  # the other format is the fallback


def test_rebased_restores_as_of_share_basis() -> None:
    idx = [date(2021, 8, 12), date(2021, 8, 13)]
    s = MarketSeries(
        closes=pd.Series([760.0, 763.1], index=idx),
        index_closes=pd.Series([16000.0, 16100.0], index=idx),
        dividends=pd.Series([3.25], index=[date(2021, 6, 1)]),
    )
    r = rebased(s, 2.0)
    assert r.closes.iloc[-1] == pytest.approx(1526.2)
    assert r.dividends.iloc[0] == pytest.approx(6.5)
    assert r.index_closes.equals(s.index_closes)
    assert rebased(s, 1.0) is s
