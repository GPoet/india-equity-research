from datetime import date, datetime

from eqr.cache import Cache
from eqr.scan import rank, symbols_with_new_results
from eqr.sources.announcements import Announcement


def ann(sym, cat, d=date(2026, 11, 23)):
    return Announcement(sym, datetime(d.year, d.month, d.day, 18), cat, "t", None, None)


def test_only_results_filings_trigger_a_refresh() -> None:
    anns = [
        ann("A", "Financial Result Updates"),
        ann("B", "Outcome of Board Meeting"),
        ann("C", "Trading Window"),
        ann("D", "Integrated Filing- Financials"),
    ]
    assert symbols_with_new_results(anns) == {"A", "B", "D"}


def test_picks_need_liquidity_but_ranking_keeps_everyone() -> None:
    def row(sym, p, turnover):
        return {
            "symbol": sym,
            "red_flags": [],
            "turnover": turnover,
            "forecast": {"1m": {"p_beat_nifty": p}},
        }

    picks, ranked = rank([row("BIG", 0.55, 5e9), row("TINY", 0.60, 2e5)], n=10)
    assert [r["symbol"] for r in picks] == ["BIG"]
    assert [r["symbol"] for r in ranked] == ["TINY", "BIG"]


def test_cache_delete(tmp_path) -> None:
    c = Cache(tmp_path / "c.sqlite")
    c.set("k", "v", ttl=None)
    c.delete("k")
    assert c.get("k") is None
