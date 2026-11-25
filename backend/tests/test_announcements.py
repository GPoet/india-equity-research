import json
from datetime import date, datetime
from pathlib import Path

from eqr.sources.announcements import NOISE, parse_announcements

FIX = Path(__file__).parent / "fixtures" / "nse" / "tcs_announcements.json"


def test_parses_and_drops_noise() -> None:
    raw = json.loads(FIX.read_text())
    items = parse_announcements(raw)
    assert items
    assert all(a.category not in NOISE for a in items)
    assert len(items) < len(raw)


def test_fields() -> None:
    a = parse_announcements(json.loads(FIX.read_text()))[0]
    assert isinstance(a.when, datetime)
    assert a.symbol == "TCS"
    assert a.text
    assert a.url is None or a.url.startswith("https://")
    assert a.industry == "Computers - Software"


def test_newest_first() -> None:
    items = parse_announcements(json.loads(FIX.read_text()))
    assert [a.when for a in items] == sorted((a.when for a in items), reverse=True)


def test_malformed_row_skipped() -> None:
    items = parse_announcements([{"an_dt": "garbage", "desc": "Updates"}, {"symbol": "X"}])
    assert items == []


def test_window_query_format() -> None:
    from eqr.sources.announcements import window_path

    assert window_path("M&M", date(2026, 8, 1), date(2026, 11, 25)) == (
        "corporate-announcements?index=equities&symbol=M%26M&from_date=01-08-2026&to_date=25-11-2026"
    )
