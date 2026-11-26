"""Export everything the hosted (static) site shows into plain JSON files.

Usage: uv run python scripts/export_site.py [--out ../frontend/public/data]
Reads the scan's per-company files (data/scan/companies/) and builds the market overview and
sector data with the same code the live API uses.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from eqr.app.scanner import safe_key
from eqr.app.serialize import clean
from eqr.app.services import LiveServices
from eqr.sectors.catalog import SECTORS, sector_for_industry
from eqr.sectors.view import sector_picture

ROOT = Path(__file__).resolve().parent.parent


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(data), separators=(",", ":")))


def slim(scan: dict[str, Any] | None) -> dict[str, Any] | None:
    """The site filters the ranked list itself; the full row list and the picks are duplicates."""
    if scan is None:
        return None
    return {k: v for k, v in scan.items() if k not in ("rows", "unranked", "picks")}


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "frontend" / "public" / "data"))
    out = Path(ap.parse_args().out)
    if out.exists():
        shutil.rmtree(out)
    scan_dir = ROOT / "data" / "scan"
    latest = (
        json.loads((scan_dir / "latest.json").read_text())
        if (scan_dir / "latest.json").exists()
        else None
    )
    current = (
        json.loads((scan_dir / "current.json").read_text())
        if (scan_dir / "current.json").exists()
        else None
    )
    industries = (
        json.loads((scan_dir / "industries.json").read_text())
        if (scan_dir / "industries.json").exists()
        else {}
    )

    index, n = [], 0
    for f in sorted((scan_dir / "companies").glob("*.json")):
        d = json.loads(f.read_text())
        row = d.get("row") or {}
        if not d.get("valuation"):
            continue  # not valued: listed in the scan table, no company page
        key = row.get("key") or (
            f"BSE:{row['symbol']}" if row.get("exchange") == "BSE" else row["symbol"]
        )
        industry = industries.get(row["symbol"]) if row.get("exchange") != "BSE" else None
        payload = {
            "symbol": row["symbol"],
            "name": row.get("name") or row["symbol"],
            "exchange": row.get("exchange", "NSE"),
            "ticker": row.get("ticker", row["symbol"]),
            "link": row.get("link"),
            "industry": industry,
            "sector_key": sector_for_industry(industry, row.get("name") or ""),
            "valuation": d["valuation"],
            "financials": d.get("financials"),
            "forecast": d.get("forecast")
            or {"status": "no_data", "error": "No forecast for this company"},
            "generated_at": d.get("price_day"),
        }
        write(out / "c" / f"{safe_key(key)}.json", payload)
        index.append(
            {
                "s": safe_key(key),
                "t": payload["ticker"],
                "n": payload["name"],
                "x": payload["exchange"],
            }
        )
        n += 1
    write(out / "index.json", index)

    svc = LiveServices()
    closes, pe = svc._index_frames()  # noqa: SLF001 - same frames the live API uses
    write(out / "sectors.json", svc.sectors())
    for key in SECTORS:
        write(
            out / "sector" / f"{key}.json",
            {"sector_key": key, "picture": sector_picture(key, closes, pe)},
        )
    write(
        out / "sector" / "none.json",
        {"sector_key": None, "picture": sector_picture(None, closes, pe)},
    )
    write(out / "overview.json", svc.overview())
    shown = latest or current
    write(
        out / "scan.json",
        {
            "running": False,
            "progress": {},
            "latest": slim(latest),
            "partial": None if latest else slim(current),
        },
    )
    backtest = ROOT / "data" / "backtest" / "latest.json"
    if not backtest.exists():
        backtest = ROOT / "seed" / "backtest.json"  # history test run locally, committed
    if backtest.exists():
        shutil.copy(backtest, out / "backtest.json")
    write(
        out / "meta.json",
        {
            "exported_at": time.time(),
            "day": date.today(),
            "price_day": shown["price_day"] if shown else None,
            "companies": n,
        },
    )
    print(f"Exported {n} company pages to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
