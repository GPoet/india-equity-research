from datetime import date, timedelta

import pytest

from eqr.overview import most_traded, unusual_volume, window_returns
from eqr.sources.bhavcopy import DailyBar


def bar(sym, d, close, prev, vol=1000, turnover=2e8):
    return DailyBar(sym, "IN", "EQ", d, close, close, close, close, prev, vol, turnover)


def days(n, start=date(2025, 6, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_window_returns_chain_and_correct_split_days() -> None:
    ds = days(3)
    files = [
        (ds[0], {"A": bar("A", ds[0], 110, 100), "B": bar("B", ds[0], 9331, 9368.5)}),
        (ds[1], {"A": bar("A", ds[1], 121, 110), "B": bar("B", ds[1], 938, 9331)}),  # B 1:10
        (ds[2], {"A": bar("A", ds[2], 121, 121), "B": bar("B", ds[2], 950, 938)}),
    ]
    factors = {("B", ds[1]): 10.0}
    r = window_returns(files, factors, 3)
    assert r["A"] == pytest.approx(0.21)
    assert r["B"] == pytest.approx(9331 / 9368.5 * 9380 / 9331 * 950 / 938 - 1)
    assert window_returns(files, factors, 1)["A"] == pytest.approx(0.0)


def test_window_returns_skip_symbols_missing_on_many_days() -> None:
    ds = days(3)
    files = [(d, {"A": bar("A", d, 100, 100)}) for d in ds]
    files[2][1]["NEW"] = bar("NEW", ds[2], 50, 40)  # listed only on the last day
    r = window_returns(files, {}, 3)
    assert "NEW" not in r and "A" in r


def test_unusual_volume_adjusts_for_splits_and_needs_liquidity() -> None:
    ds = days(21)
    files = []
    for i, d in enumerate(ds):
        vol = 1000 if i < 20 else 5000
        files.append(
            (
                d,
                {
                    "A": bar("A", d, 10, 10, vol=vol, turnover=2e8),
                    "S": bar("S", d, 10, 10, vol=1000 if i < 10 else 10000, turnover=2e8),
                    "TINY": bar("TINY", d, 1, 1, vol=1 if i < 20 else 100, turnover=1e5),
                },
            )
        )
    factors = {("S", ds[10]): 10.0}  # S split 1:10: later volume is 10x for the same trading
    top = unusual_volume(files, factors, n=5)
    assert top[0]["symbol"] == "A" and top[0]["ratio"] == pytest.approx(5.0)
    assert all(t["symbol"] != "S" for t in top if t["ratio"] > 1.5)
    assert all(t["symbol"] != "TINY" for t in top)


def test_most_traded_by_turnover() -> None:
    d = date(2025, 6, 2)
    out = most_traded(
        {"A": bar("A", d, 10, 9, turnover=5e9), "B": bar("B", d, 10, 10, turnover=9e9)}, n=2
    )
    assert [o["symbol"] for o in out] == ["B", "A"]
    assert out[1]["change"] == pytest.approx(10 / 9 - 1)


def test_headline_strips_exchange_boilerplate() -> None:
    from eqr.overview import headline

    t = "Maruti Suzuki India Limited has informed the Exchange about Price increase"
    assert headline(t) == "Price increase"
    assert headline("Board approved a buyback") == "Board approved a buyback"
