"""Sector strength across the market, and the picture for one company's sector.

Usage: uv run python scripts/sectors.py [COMPANY]
First run downloads ~1 year of NSE daily index files (a few minutes); later runs are cached.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from eqr.cache import Cache
from eqr.nse_client import NseClient
from eqr.sectors.catalog import sector_for_industry
from eqr.sectors.view import SectorStat, build_stats, sector_picture
from eqr.sources.announcements import fetch_announcements
from eqr.sources.indices import IndexHistory
from eqr.sources.universe import load_resolver

ROOT = Path(__file__).resolve().parent.parent


def pct(x: float | None) -> str:
    return "    -" if x is None else f"{x:+6.1%}"


def line(s: SectorStat) -> str:
    pe = "-" if s.pe is None else f"{s.pe:5.1f}"
    return (
        f"  {s.rank:>2}. {s.label[:34]:34} {s.stance:23} 3m {pct(s.rs_3m)}  6m {pct(s.rs_6m)}  "
        f"vs200d {pct(s.vs_200dma)}  P/E {pe} ({pct(s.pe_premium)} vs 1y median)"
    )


def main(args: list[str]) -> int:
    logging.basicConfig(level=logging.ERROR)
    cache = Cache(ROOT / "data" / "cache.sqlite")
    client = NseClient(cache=cache)
    closes, pe = IndexHistory(client, cache).frame(date.today(), days=400)
    print(
        f"NSE index data: {closes.index[0].date()} to {closes.index[-1].date()} ({len(closes)} trading days)"
    )
    print("Relative strength = return minus the Nifty 50's over the same period.\n")
    stats = sorted((s for s in build_stats(closes, pe).values() if s.rank), key=lambda s: s.rank)
    print("All sectors, strongest first:")
    for s in stats:
        print(line(s))

    if not args:
        return 0
    res = load_resolver(ROOT / "data").resolve(args[0])
    if res.match is None:
        print("Not sure which company: " + ", ".join(c.security.symbol for c in res.candidates))
        return 2
    sym = res.match.symbol
    anns = fetch_announcements(client, sym, date.today() - timedelta(days=120), date.today())
    industry = anns[0].industry if anns else None
    key = sector_for_industry(industry, res.match.name)
    pic = sector_picture(key, closes, pe)
    print(f"\n=== {sym}: NSE industry '{industry}' -> sector '{key}' ===")
    if pic.sector:
        print(line(pic.sector))
    print("Related sectors (correlation = weekly moves after removing the market's):")
    for r in pic.related:
        corr = "  n/a" if r.correlation is None else f"{r.correlation:+.2f}"
        print(f"  {r.stat.label[:30]:30} {r.stat.stance:23} corr {corr}  [{r.basis}] {r.why}")
    bullish = [r.stat.label for r in pic.related if r.stat.stance.startswith("bullish")]
    print("Bullish related sectors: " + (", ".join(bullish) or "none right now"))
    for n in pic.notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
