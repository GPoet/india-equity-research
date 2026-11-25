from datetime import date

from eqr.scan import order_universe, rank, should_run


def row(sym, p, flags=(), fc=True):
    return {
        "symbol": sym,
        "red_flags": list(flags),
        "turnover": 5e9,
        "forecast": {"1m": {"p_beat_nifty": p, "median": 100 * (1 + p - 0.5)}} if fc else None,
    }


def test_rank_puts_best_odds_first_and_keeps_flagged_out_of_picks() -> None:
    rows = [
        row("A", 0.55),
        row("B", 0.62, flags=["Altman distress"]),
        row("C", 0.58),
        row("D", 0.0, fc=False),
    ]
    picks, ranked = rank(rows, n=10)
    assert [r["symbol"] for r in ranked] == ["B", "C", "A"]  # no forecast: not ranked
    assert [r["symbol"] for r in picks] == ["C", "A"]  # red flags kept out of the picks


def test_order_universe_nifty50_first_then_by_turnover() -> None:
    out = order_universe(["X", "Y", "TCS", "Z"], nifty50={"TCS"}, turnover={"X": 1, "Y": 9, "Z": 5})
    assert out == ["TCS", "Y", "Z", "X"]


def test_should_run_when_nse_has_a_day_the_last_scan_did_not_use() -> None:
    assert should_run(last_price_day=date(2026, 11, 23), latest_file_day=date(2026, 11, 25))
    assert not should_run(date(2026, 11, 25), date(2026, 11, 25))  # nothing new
    assert should_run(None, date(2026, 11, 24))  # never scanned
    assert not should_run(date(2026, 11, 25), None)  # no file found: wait


def test_current_refs_latest_version_on_main_basis() -> None:
    from eqr.scan import _current_refs
    from eqr.sources.filings import FilingRef

    refs = [
        FilingRef("X", date(2026, 9, 30), True, "c-orig", "20-Oct-2026 18:00:00", "integrated"),
        FilingRef("X", date(2026, 9, 30), True, "c-rev", "02-Nov-2026 18:00:00", "integrated"),
        FilingRef("X", date(2026, 9, 30), False, "s", "20-Oct-2026 18:00:00", "integrated"),
        FilingRef("X", date(2026, 6, 30), True, "c-q1", "20-Jul-2026 18:00:00", "integrated"),
    ]
    got = {r.xbrl_url for r in _current_refs(refs, date(2026, 11, 23))}
    assert got == {"c-rev", "c-q1"}
