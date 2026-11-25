from datetime import date
from pathlib import Path

import pytest

from eqr.sources.bhavcopy import bhavcopy_url, parse_bhavcopy

FIX = Path(__file__).parent / "fixtures" / "nse" / "bhavcopy_20261120_sample.csv"


@pytest.fixture(scope="module")
def bars():
    return parse_bhavcopy(FIX.read_text())


def test_url_format() -> None:
    assert bhavcopy_url(date(2026, 11, 20)) == (
        "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20261120_F_0000.csv.zip"
    )


def test_parses_equity_rows(bars) -> None:
    tcs = bars["TCS"]
    assert tcs.trade_date == date(2026, 11, 20)
    assert tcs.close == 2376.20
    assert tcs.prev_close == 2342.70
    assert tcs.high == 2414.80
    assert tcs.volume == 2960416
    assert tcs.isin == "INE467B01029"


def test_all_sample_symbols_present(bars) -> None:
    assert {"TCS", "RELIANCE", "SBIN", "20MICRONS"} <= set(bars)


def test_change_pct(bars) -> None:
    assert bars["TCS"].change_pct == pytest.approx((2376.20 / 2342.70 - 1) * 100)


def test_bad_row_skipped_not_fatal() -> None:
    lines = FIX.read_text().splitlines()
    bad = lines[1].split(",")
    bad[17] = ""  # empty close price
    text = "\n".join([lines[0], ",".join(bad), *lines[2:]]) + "\n"
    bars = parse_bhavcopy(text)
    assert len(bars) == len(lines) - 2


def test_change_pct_none_without_prev_close(bars) -> None:
    from dataclasses import replace

    assert replace(bars["TCS"], prev_close=0.0).change_pct is None
