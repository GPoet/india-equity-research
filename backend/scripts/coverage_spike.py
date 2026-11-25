"""Phase 0: check how much data we can actually get for a spread of stocks.

Run: uv run python scripts/coverage_spike.py
Prints one row per stock and writes data/coverage_report.json.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from eqr.cache import Cache
from eqr.nse_client import NseClient
from eqr.resolver import Resolver
from eqr.sources.bhavcopy import BhavcopySource
from eqr.sources.filings import FilingsSource
from eqr.sources.prices import history, quote

ROOT = Path(__file__).resolve().parent.parent
STOCKS = {
    "HDFCBANK": "private bank",
    "BAJFINANCE": "NBFC",
    "TCS": "IT",
    "HINDUNILVR": "FMCG",
    "NTPC": "PSU power",
    "TATASTEEL": "metal",
    "SUNPHARMA": "pharma",
    "BAJAJHLDNG": "holdco",
    "20MICRONS": "small cap",
    "LGEINDIA": "recent IPO",
}
CORE = ("revenue", "pat", "ebitda", "eps_basic", "depreciation", "finance_costs")
BANK_CORE = (
    "total_income",
    "nii",
    "ppop",
    "provisions",
    "pat",
    "eps_basic",
    "gnpa_pct",
    "cet1_pct",
)
BS = ("total_assets", "equity_owners", "total_debt", "cash")
CRORE = 1e7


def check(symbol: str, kind: str, filings: FilingsSource, bars: dict, resolver: Resolver) -> dict:
    row: dict = {"symbol": symbol, "kind": kind, "errors": []}
    row["resolved"] = bool(resolver.by_symbol(symbol))
    try:
        refs = filings.list(symbol)
        row["filings_total"] = len(refs)
        row["filings_integrated"] = sum(r.source == "integrated" for r in refs)
        row["oldest_period"] = min(r.period_end for r in refs).isoformat() if refs else None
        cons = [r for r in refs if r.consolidated] or refs
        if cons:
            latest = filings.fetch(cons[0])
            m = latest.quarter_metrics()
            row["is_bank"] = latest.is_bank
            row["latest_period"] = cons[0].period_end.isoformat()
            row["latest_is_consolidated"] = cons[0].consolidated
            core = BANK_CORE if latest.is_bank else CORE
            row["present"] = [k for k in core if m.get(k) is not None]
            row["missing"] = [k for k in core if m.get(k) is None]
            top = m.get("total_income") if latest.is_bank else m.get("revenue")
            row["revenue_cr"] = round(top / CRORE) if top else None
            row["pat_cr"] = round(m["pat"] / CRORE) if m.get("pat") else None
            bs = latest.balance_metrics()
            row["bs_present"] = [k for k in BS if bs.get(k) is not None]
            row["bs_period"] = (
                latest.balance_sheet.end.isoformat() if latest.balance_sheet else None
            )
            row["concept_count"] = len(latest.quarter.values)
            # Banks use a different taxonomy; record what revenue-like tags exist.
            if m.get("revenue") is None:
                row["revenue_like_tags"] = sorted(
                    k for k in latest.quarter.values if "Interest" in k or "Income" in k
                )[:12]
    except Exception as exc:  # spike: record and continue
        row["errors"].append(f"filings: {type(exc).__name__}: {exc}"[:240])
    try:
        q = quote(symbol)
        row["yf_price"] = round(q.price, 2)
        row["yf_as_of"] = q.as_of.isoformat()
        row["yf_history_years"] = round(len(history(symbol, period="max")) / 248, 1)
    except Exception as exc:
        row["errors"].append(f"yfinance: {type(exc).__name__}: {exc}"[:240])
    bar = bars.get(symbol) if bars else None
    row["bhav_close"] = bar.close if bar else None
    row["bhav_date"] = bar.trade_date.isoformat() if bar else None
    return row


def main() -> int:
    cache = Cache(ROOT / "data" / "cache.sqlite")
    client = NseClient(cache=cache)
    resolver = Resolver.from_csv(ROOT / "data" / "EQUITY_L.csv")
    filings = FilingsSource(client)
    bars = BhavcopySource(client, cache).latest(date.today()) or {}
    rows = []
    for symbol, kind in STOCKS.items():
        row = check(symbol, kind, filings, bars, resolver)
        rows.append(row)
        print(
            f"{symbol:11} {kind:11} filings={row.get('filings_total', '-'):>4} "
            f"since={row.get('oldest_period', '-')} latest={row.get('latest_period', '-')} "
            f"rev={row.get('revenue_cr', '-')}cr pat={row.get('pat_cr', '-')}cr "
            f"missing={row.get('missing', '-')} bs={row.get('bs_present', '-')} "
            f"yf={row.get('yf_price', '-')} bhav={row.get('bhav_close', '-')} "
            f"errors={len(row['errors'])}",
            flush=True,
        )
    out = ROOT / "data" / "coverage_report.json"
    out.write_text(json.dumps(rows, indent=1, default=str))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
