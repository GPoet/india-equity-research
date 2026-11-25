"""Value one or more NSE companies from the command line.

Usage: uv run python scripts/value.py TCS "HDFC Bank" https://www.screener.in/company/NTPC/
Writes data/reports/<SYMBOL>.json alongside the printed summary.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

from eqr.cache import Cache
from eqr.fundamentals import load_fundamentals
from eqr.market import load_market_inputs
from eqr.nse_client import NseClient
from eqr.sources.filings import FilingsSource
from eqr.sources.universe import load_resolver
from eqr.valuation.engine import ValuationReport, fetch_price_data, value_company

ROOT = Path(__file__).resolve().parent.parent
CRORE = 1e7


def fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "-"
    return f"{x:.1%}" if pct else f"{x:,.0f}"


def print_report(r: ValuationReport) -> None:
    b, a = r.result, r.assumptions
    print(f"\n=== {r.symbol} ({r.company_type}, {a['basis']}) ===")
    print(
        f"Price {r.price:,.2f} ({r.price_as_of[:16]})   Market cap {fmt((a['market_cap'] or 0) / CRORE)} cr"
    )
    print(
        f"Fair value {fmt(b.low)} / {fmt(b.mid)} / {fmt(b.high)} (low/mid/high)   "
        f"Buy below {fmt(b.buy_below)}   Upside {fmt(b.upside, True)}"
    )
    print(f"SIGNAL: {b.signal}   confidence: {b.confidence}  {'; '.join(b.reasons)}")
    if b.red_flags:
        print("RED FLAGS: " + "; ".join(b.red_flags))
    ig = r.implied_growth
    print(f"Reverse DCF: {ig.summary if ig.applicable else ig.reason}")
    print(
        f"Ke {fmt(a['cost_of_equity'], True)}  WACC {fmt(a['wacc'], True)}  beta {a['beta']:.2f}  "
        f"growth {fmt(a['growth'], True)}  tax {fmt(a['tax_rate'], True)}  history {a['years_of_history']} FY"
    )
    print(f"{'lens':38} {'school':32} {'value':>10}  {'weight':>6}  verdict / reason")
    for lens in r.lenses:
        weight = b.used.get(lens.key)
        if lens.applicable:
            shown = (
                fmt(lens.value)
                if lens.kind == "value"
                else f"{lens.value:.2f}"
                if lens.value is not None
                else "-"
            )
            print(
                f"{lens.name[:38]:38} {lens.school[:32]:32} {shown:>10}  {fmt(weight, True) if weight else '':>6}  "
                f"{lens.verdict or ''} {('| ' + lens.summary[:90]) if lens.kind != 'value' else ''}"
            )
        else:
            print(f"{lens.name[:38]:38} {lens.school[:32]:32} {'n/a':>10}  {'':>6}  {lens.reason}")
    for note in a["notes"] + list(r.warnings):
        print(f"  note: {note}")


def main(args: list[str]) -> int:
    logging.basicConfig(level=logging.ERROR)
    if not args:
        print(__doc__)
        return 2
    cache = Cache(ROOT / "data" / "cache.sqlite")
    source = FilingsSource(NseClient(cache=cache))
    resolver = load_resolver(ROOT / "data")
    market = load_market_inputs()
    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()
    for query in args:
        res = resolver.resolve(query)
        if res.match is None:
            options = (
                ", ".join(f"{c.security.symbol} ({c.security.name})" for c in res.candidates)
                or "none"
            )
            print(f"\n'{query}': not sure which company. Candidates: {options}")
            continue
        symbol = res.match.symbol
        try:
            f = load_fundamentals(source, symbol)
            prices = fetch_price_data(symbol, [y.fy_end for y in f.years], today)
            report = value_company(f, market, prices, today)
        except Exception as exc:
            print(f"\n{symbol}: failed: {type(exc).__name__}: {exc}")
            continue
        print_report(report)
        (out_dir / f"{symbol}.json").write_text(json.dumps(report.to_dict(), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
