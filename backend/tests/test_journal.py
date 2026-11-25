from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from eqr.journal import HORIZONS, Journal, score_entry, summarise


def entry(**kw):
    base = {
        "id": 1,
        "day": "2025-01-01",
        "symbol": "X",
        "price": 100.0,
        "signal": "Undervalued",
        "confidence": "high",
        "low": 120.0,
        "mid": 140.0,
        "high": 160.0,
        "upside": 0.4,
    }
    base.update(kw)
    return base


def line(start: date, days: int, start_value: float, end_value: float) -> pd.Series:
    idx = [start + timedelta(days=i) for i in range(days)]
    step = (end_value - start_value) / (days - 1)
    return pd.Series([start_value + step * i for i in range(days)], index=idx)


def test_record_upserts_one_per_symbol_per_day(tmp_path: Path) -> None:
    j = Journal(tmp_path / "j.sqlite")
    j.record_raw(entry(price=100.0))
    j.record_raw(entry(price=101.0))
    rows = j.entries()
    assert len(rows) == 1 and rows[0]["price"] == 101.0


def test_score_hit_for_undervalued_that_beat_market() -> None:
    stock = line(date(2025, 1, 1), 400, 100, 130)
    nifty = line(date(2025, 1, 1), 400, 1000, 1050)
    s = score_entry(entry(), stock, nifty, today=date(2026, 3, 1))
    six = s["6m"]
    assert six["stock_return"] > six["index_return"]
    assert six["outcome"] == "hit"


def test_overvalued_that_beat_market_is_a_miss() -> None:
    stock = line(date(2025, 1, 1), 400, 100, 130)
    nifty = line(date(2025, 1, 1), 400, 1000, 1000)
    s = score_entry(entry(signal="Overvalued"), stock, nifty, today=date(2026, 3, 1))
    assert s["6m"]["outcome"] == "miss"


def test_horizon_not_reached_is_pending() -> None:
    stock = line(date(2025, 1, 1), 40, 100, 101)
    nifty = line(date(2025, 1, 1), 40, 1000, 1001)
    s = score_entry(entry(), stock, nifty, today=date(2025, 2, 5))
    assert s["12m"]["outcome"] == "pending"
    assert s["1m"]["outcome"] in ("hit", "miss")


def test_summary_by_signal_and_horizon() -> None:
    scored = [
        {
            "signal": "Undervalued",
            "scores": {h: {"outcome": "hit", "excess": 0.1} for h in HORIZONS},
        },
        {
            "signal": "Undervalued",
            "scores": {h: {"outcome": "miss", "excess": -0.05} for h in HORIZONS},
        },
        {
            "signal": "Overvalued",
            "scores": {h: {"outcome": "pending", "excess": None} for h in HORIZONS},
        },
    ]
    s = summarise(scored)
    under = next(r for r in s if r["signal"] == "Undervalued" and r["horizon"] == "6m")
    assert under["n"] == 2 and under["hit_rate"] == pytest.approx(0.5)
    assert under["mean_excess"] == pytest.approx(0.025)
    over = next(r for r in s if r["signal"] == "Overvalued" and r["horizon"] == "6m")
    assert over["n"] == 0 and over["pending"] == 1


def test_stale_close_is_no_data() -> None:
    from datetime import date

    import pandas as pd

    from eqr.journal import score_entry

    days = [date(2025, 1, 1), date(2025, 1, 2)]  # series stops early (suspended)
    s = pd.Series([100.0, 101.0], index=days)
    out = score_entry({"day": "2025-01-02", "signal": "Undervalued"}, s, s, date(2026, 1, 1))
    assert out["1m"]["outcome"] == "no data"


def test_thin_counts_a_symbol_once_per_window() -> None:
    from eqr.journal import thin

    entries = [{"symbol": "TCS", "day": f"2026-01-{d:02d}"} for d in (1, 2, 15, 31)] + [
        {"symbol": "INFY", "day": "2026-01-02"},
        {"symbol": "TCS", "day": "2026-02-05"},
    ]
    kept = thin(entries, days=30)
    assert sorted((e["symbol"], e["day"]) for e in kept) == [
        ("INFY", "2026-01-02"),
        ("TCS", "2026-01-01"),
        ("TCS", "2026-01-31"),
    ]
