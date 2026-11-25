from datetime import date

import pytest

from eqr.backtest import quarterly_dates, refs_known_on, upside_rank_stats
from eqr.sources.filings import FilingRef


def ref(end: date, filed: str, url: str, source: str = "integrated") -> FilingRef:
    return FilingRef("X", end, True, url, filed, source)


def test_only_filings_filed_before_the_date() -> None:
    refs = [
        ref(date(2024, 12, 31), "20-Jan-2025 18:00:00", "q3"),
        ref(date(2025, 3, 31), "25-Apr-2025 18:00:00", "q4"),
        ref(date(2025, 6, 30), "20-Jul-2025 18:00:00", "q1"),
    ]
    known = refs_known_on(refs, date(2025, 5, 1))
    assert [r.xbrl_url for r in known] == ["q4", "q3"]


def test_later_revision_not_used_before_it_was_filed() -> None:
    original = ref(date(2025, 3, 31), "25-Apr-2025 18:00:00", "orig")
    revised = ref(date(2025, 3, 31), "10-Jun-2025 18:00:00", "rev")
    assert refs_known_on([original, revised], date(2025, 5, 1))[0].xbrl_url == "orig"
    assert refs_known_on([original, revised], date(2025, 7, 1))[0].xbrl_url == "rev"


def test_undated_filings_excluded() -> None:
    assert refs_known_on([ref(date(2025, 3, 31), "", "x")], date(2026, 1, 1)) == []


def test_quarterly_dates() -> None:
    d = quarterly_dates(date(2021, 8, 15), date(2022, 8, 15))
    assert d == [
        date(2021, 8, 15),
        date(2021, 11, 15),
        date(2022, 2, 15),
        date(2022, 5, 15),
        date(2022, 8, 15),
    ]


def test_upside_rank_stats() -> None:
    rows = [
        {"upside": u, "excess": e}
        for u, e in [(0.5, 0.2), (0.3, 0.1), (0.0, 0.0), (-0.2, -0.1), (-0.4, -0.3)]
    ]
    stats = upside_rank_stats(rows)
    assert stats["spearman"] == pytest.approx(1.0)
    assert stats["top_quintile_excess"] > stats["bottom_quintile_excess"]
    assert stats["n"] == 5
