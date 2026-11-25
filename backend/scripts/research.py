"""Research a company with Claude (your local Claude Code login) and print the report.

Usage: uv run python scripts/research.py TCS [--model sonnet|opus] [--refresh]
Results are cached for 12 hours per company and model in data/research/ to spare your
plan's usage limits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from eqr.cache import Cache
from eqr.fundamentals import load_fundamentals
from eqr.llm.claude_cli import ClaudeCliProvider, LlmError
from eqr.market import load_market_inputs
from eqr.nse_client import NseClient
from eqr.research.agent import NEWS_WINDOW_DAYS, run_research
from eqr.research.brief import build_brief
from eqr.sources.announcements import fetch_announcements
from eqr.sources.documents import fetch_documents, select_documents
from eqr.sources.filings import FilingsSource
from eqr.sources.universe import load_resolver
from eqr.valuation.engine import fetch_price_data, value_company

ROOT = Path(__file__).resolve().parent.parent
CACHE_HOURS = 12
SCHEMA_VERSION = 2


def cache_path(symbol: str, model: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_&-]", "_", f"{symbol}_{model}")
    return ROOT / "data" / "research" / f"{safe}.json"


def load_cached(path: Path) -> dict | None:
    if not path.exists() or time.time() - path.stat().st_mtime > CACHE_HOURS * 3600:
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if data.get("schema_version") == SCHEMA_VERSION else None


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def print_report(data: dict) -> None:
    r, meta = data["report"], data["meta"]
    secs = (meta.get("duration_ms") or 0) / 1000
    tools = ", ".join(f"{k} x{v}" for k, v in (meta.get("tool_calls") or {}).items()) or "none"
    print(
        f"\n=== {data['symbol']} research ({meta['as_of']}, {meta['model']}, {secs:.0f}s; "
        f"tools: {tools}; {meta.get('documents_given', 0)} NSE filings read) ==="
    )
    for w in data.get("warnings", []):
        print(f"WARNING: {w}")
    print(f"\n{r['summary']}\n\nLatest results: {r['latest_results']}")
    print("\nCatalysts:")
    for c in sorted(r["catalysts"], key=lambda c: -c["materiality"]):
        print(
            f"  [{c['direction']:8}] m{c['materiality']} {c['date'] or '?':10} {c['title']}\n"
            f"      {c['source_name']}: {c['source_url']}"
        )
    print("\nRegulation:")
    for g in r["regulation"]:
        print(
            f"  [{g['direction']:8}] {g['regulator']}: {g['title']} ({g['status']}, "
            f"effective {g['effective_date'] or '?'})\n      {g['source_url']}"
        )
    s = r["sector_view"]
    print(f"\nSector: {s['sector']} - {s['stance']}. {s['reasoning']}")
    for u in s["source_urls"]:
        print(f"      {u}")
    print("\nRisks:")
    for k in sorted(r["risks"], key=lambda k: -k["severity"]):
        print(
            f"  s{k['severity']} {k['title']}"
            + (f"\n      {k['source_url']}" if k["source_url"] else " (analysis)")
        )
    print("\nUpcoming:")
    for e in r["events"]:
        print(f"  {e['date'] or 'date TBA':10} {e['event']}")
    print(f"\nBull: {r['bull_case']}\nBear: {r['bear_case']}")
    if r["data_gaps"]:
        print("Gaps:\n  - " + "\n  - ".join(r["data_gaps"]))
    if any(data["dropped"].values()):
        print(f"Dropped by sourcing rules: { {k: v for k, v in data['dropped'].items() if v} }")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    res = load_resolver(ROOT / "data").resolve(args.query)
    if res.match is None:
        print("Not sure which company: " + ", ".join(c.security.symbol for c in res.candidates))
        return 2
    sym, name = res.match.symbol, res.match.name
    out = cache_path(sym, args.model)
    cached = None if args.refresh else load_cached(out)
    if cached:
        print(f"(cached result, under {CACHE_HOURS}h old; --refresh to rerun)")
        print_report(cached)
        return 0

    today = date.today()
    cache = Cache(ROOT / "data" / "cache.sqlite")
    client = NseClient(cache=cache)
    f = load_fundamentals(FilingsSource(client), sym)
    prices = fetch_price_data(sym, [y.fy_end for y in f.years], today)
    valuation = value_company(f, load_market_inputs(), prices, today)
    anns = fetch_announcements(client, sym, today - timedelta(days=NEWS_WINDOW_DAYS), today)
    docs = fetch_documents(client, cache, anns)
    warnings = []
    if select_documents(anns) and not docs:
        warnings.append(
            "None of the company's NSE filings could be read; results rely on web sources"
        )
    brief = build_brief(name, anns[0].industry if anns else None, f, valuation)
    print(f"Researching {sym} with Claude ({args.model}); this takes a few minutes...")
    try:
        run = run_research(
            ClaudeCliProvider(), brief, anns, today, model=args.model, documents=docs
        )
    except LlmError as exc:
        print(f"Research failed ({exc.kind}): {exc}")
        return 1
    data = {
        "schema_version": SCHEMA_VERSION,
        "symbol": sym,
        "name": name,
        "brief": brief.facts,
        "report": run.report.model_dump(),
        "dropped": run.dropped,
        "meta": run.meta,
        "warnings": warnings,
    }
    if not warnings:
        save(out, data)  # a degraded run is shown but not cached
    print_report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
