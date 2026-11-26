"""Run or resume the daily market scan without the API (for scheduled jobs, e.g. GitHub Actions).

Usage: uv run python scripts/run_scan.py [--budget-minutes 320] [--shard 3/8 --delta-out DIR]
With --shard, scans only that slice of the companies (parallel jobs) and, with --delta-out,
exports what it added for scripts/merge_shards.py.
Exits 0 whether the scan completed or stopped at the budget (the next run resumes); prints
progress. Skips work when the latest complete scan already covers NSE's latest trading day.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

from eqr.app.scanner import Scanner
from eqr.listings import all_names, nifty50_symbols
from eqr.pipeline import Context
from eqr.scan import should_run
from eqr.shards import export_delta
from eqr.sources.bhavcopy import BhavcopySource

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-minutes", type=float, default=320)
    ap.add_argument("--shard", default="", help="I/N: scan slice I of N (0-based)")
    ap.add_argument("--delta-out", default="", help="export this run's additions here")
    args = ap.parse_args()
    shard = None
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        if not 0 <= i < n:
            raise SystemExit(f"Bad --shard {args.shard}")
        shard = (i, n)
    ctx = Context()
    scanner = Scanner(
        ctx,
        ROOT / "data" / "scan",
        lambda: all_names(ctx.client),
        lambda: nifty50_symbols(ctx.client),
    )
    bars = BhavcopySource(ctx.client, ctx.cache).latest(date.today())
    latest_day = next(iter(bars.values())).trade_date if bars else None
    last = scanner.latest()
    t0 = time.time()
    if not should_run(date.fromisoformat(last["price_day"]) if last else None, latest_day):
        print(f"Up to date: latest complete scan covers {latest_day}")
        if args.delta_out:
            Path(args.delta_out).mkdir(parents=True, exist_ok=True)
            (Path(args.delta_out) / "idle").write_text("up to date")
        return 0
    status = scanner.run_now(deadline=t0 + args.budget_minutes * 60, shard=shard)
    if args.delta_out:
        export_delta(ROOT / "data", Path(args.delta_out), since=t0)
    p, latest = status["progress"], status["latest"]
    done = latest and latest["price_day"] == str(latest_day)
    print(
        f"{'Complete' if done else 'Stopped at budget'}: {p.get('done')} of {p.get('total')} in {(time.time() - t0) / 60:.0f} min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
