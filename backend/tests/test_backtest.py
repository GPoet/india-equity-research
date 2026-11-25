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


from eqr.backtest import share_basis_factor, summary, usable  # noqa: E402


def row(signal, conf, used, excess6, upside=0.1):
    sc = {h: {"outcome": "pending", "excess": None} for h in ("1m", "3m", "6m", "12m")}
    hit = (excess6 > 0) == (signal == "Undervalued")
    sc["6m"] = {
        "excess": excess6,
        "stock_return": excess6,
        "index_return": 0.0,
        "outcome": "hit" if hit else "miss",
    }
    return {"signal": signal, "confidence": conf, "used": used, "upside": upside, "scores": sc}


def test_share_basis_factor() -> None:
    assert share_basis_factor(1526.2, 763.1) == pytest.approx(2.0)
    assert share_basis_factor(100.4, 100.0) == 1.0  # rounding noise is not a split
    assert share_basis_factor(None, 100.0) is None
    assert share_basis_factor(50.0, 100.0) is None  # as-traded below adjusted: data error


def test_usable_needs_core_model_and_not_low_confidence() -> None:
    assert usable(row("Overvalued", "medium", ["dcf", "lynch", "rule1"], 0.0))[0]
    ok, why = usable(row("Overvalued", "low", ["dcf", "lynch", "rule1"], 0.0))
    assert not ok and why == "low confidence"
    ok, why = usable(row("Overvalued", "medium", ["graham_formula", "lynch", "rule1"], 0.0))
    assert (
        not ok and why == "no core model (DCF, owner earnings, EPV, residual income, justified P/B)"
    )


def test_summary_excludes_and_counts_and_gives_base_rate() -> None:
    rows = [
        row("Overvalued", "high", ["dcf"], -0.1),
        row("Undervalued", "high", ["epv"], 0.2),
        row("Overvalued", "low", ["lynch"], -0.5),
    ]
    s = summary(rows)
    assert s["observations"] == 3 and s["usable"] == 2
    assert s["excluded"] == {"low confidence": 1}
    assert s["base_rate"]["6m"] == pytest.approx(0.5)  # 1 of 2 usable rows beat the Nifty
