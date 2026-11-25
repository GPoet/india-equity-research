"""Point-in-time backtest of the valuation signal on today's Nifty 50.

Usage: uv run python scripts/backtest.py [--start 2021-08-15] [--end 2025-11-15] [--symbols TCS,INFY]
Resumable: finished companies are kept in data/backtest/rows/. Writes data/backtest/latest.json.
First run downloads every company's filings from NSE (cached), which takes a while.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

from eqr.app.serialize import clean
from eqr.backtest import LIMITATIONS, quarterly_dates, run_symbol, score_rows, summary
from eqr.pipeline import Context
from eqr.sources.bhavcopy import BhavcopySource
from eqr.valuation import ENGINE_VERSION
from eqr.valuation.engine import fetch_market_series

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "backtest"
NIFTY50 = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"


def universe(ctx: Context) -> list[str]:
    text = ctx.client.get_bytes(NIFTY50).decode("utf-8-sig")
    return [row["Symbol"].strip() for row in csv.DictReader(io.StringIO(text)) if row.get("Symbol")]


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-08-15")
    ap.add_argument("--end", default="2025-11-15")
    ap.add_argument("--symbols", default="")
    args = ap.parse_args()

    ctx = Context()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or universe(ctx)
    dates = quarterly_dates(date.fromisoformat(args.start), date.fromisoformat(args.end))
    today = date.today()
    market = ctx.market()
    rows_dir = OUT / "rows" / f"{args.start}_{args.end}_{ENGINE_VERSION}"
    rows_dir.mkdir(parents=True, exist_ok=True)
    bhav = BhavcopySource(ctx.client, ctx.cache)
    day_bars = {d: bhav.on_or_before(d) for d in dates}  # as-traded prices, one file per date
    missing_days = [d.isoformat() for d, b in day_bars.items() if not b]
    if missing_days:
        print(f"No NSE price file found near: {', '.join(missing_days)}", flush=True)
    rows: list[dict] = []
    per_symbol: dict[str, dict] = {}
    for i, sym in enumerate(symbols, 1):
        cached = rows_dir / f"{sym.replace('&', '_')}.json"
        t0 = time.time()
        try:
            series = fetch_market_series(sym)  # always fresh: scores mature over time
            if cached.exists():
                saved = json.loads(cached.read_text())
                got, skipped, errors = saved["rows"], saved["skipped"], 0
            else:
                as_traded = {d: day_bars[d].get(sym) for d in dates}
                got, skipped, errors = run_symbol(
                    ctx.filings, sym, dates, series, market, as_traded
                )
                if errors == 0:  # a run with errors is retried next time, not frozen
                    cached.write_text(json.dumps(clean({"rows": got, "skipped": skipped})))
        except Exception as exc:  # noqa: BLE001 - keep going; report what was skipped
            per_symbol[sym] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[{i}/{len(symbols)}] {sym}: skipped ({type(exc).__name__}: {exc})", flush=True)
            continue
        scored = clean(score_rows(got, series, today))
        rows.extend(scored)
        per_symbol[sym] = {"rows": len(got), "skipped": skipped, "errors": errors}
        print(
            f"[{i}/{len(symbols)}] {sym}: {len(got)} valuations, skipped {skipped or 'none'}, "
            f"{errors} errors, {time.time() - t0:.0f}s",
            flush=True,
        )

    result = clean(
        {
            "run_at": today,
            "engine_version": ENGINE_VERSION,
            "start": args.start,
            "end": args.end,
            "universe": "Nifty 50 (current constituents)",
            "symbols": len(symbols),
            "limitations": list(LIMITATIONS),
            "summary": summary(rows),
            "per_symbol": per_symbol,
            "rows": rows,
        }
    )
    tmp = OUT / "latest.tmp"
    tmp.write_text(json.dumps(result))
    os.replace(tmp, OUT / "latest.json")
    s = result["summary"]
    print(f"\n{s['observations']} valuations, {s['usable']} usable; excluded: {s['excluded']}")
    print(
        "Base rate (share of usable calls where the stock beat the Nifty):",
        {h: (f"{v:.0%}" if v is not None else "-") for h, v in s["base_rate"].items()},
    )
    for r in s["by_signal"]:
        if r["horizon"] in ("6m", "12m") and r["n"]:
            print(
                f"  {r['signal']:13} {r['horizon']:>3}: n={r['n']:4}  hit rate {r['hit_rate']:.0%}  "
                f"mean excess {r['mean_excess']:+.1%}  median {r['median_excess']:+.1%}"
            )
    for h, st in s["upside_vs_return"].items():
        if st["spearman"] is not None:
            print(
                f"  upside vs {h} excess: spearman {st['spearman']:+.2f}, top fifth {st['top_quintile_excess']:+.1%}, "
                f"bottom fifth {st['bottom_quintile_excess']:+.1%} (n={st['n']})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
