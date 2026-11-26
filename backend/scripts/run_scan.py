"""Run or resume the daily market scan without the API (for scheduled jobs, e.g. GitHub Actions).

Usage: uv run python scripts/run_scan.py [--budget-minutes 320]
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
from eqr.sources.bhavcopy import BhavcopySource

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-minutes", type=float, default=320)
    args = ap.parse_args()
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
    if not should_run(date.fromisoformat(last["price_day"]) if last else None, latest_day):
        print(f"Up to date: latest complete scan covers {latest_day}")
        return 0
    t0 = time.time()
    status = scanner.run_now(deadline=t0 + args.budget_minutes * 60)
    p, latest = status["progress"], status["latest"]
    done = latest and latest["price_day"] == str(latest_day)
    print(
        f"{'Complete' if done else 'Stopped at budget'}: {p.get('done')} of {p.get('total')} in {(time.time() - t0) / 60:.0f} min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
