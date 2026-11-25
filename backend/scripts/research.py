"""Research a company with Claude (your local Claude Code login) and print the report.

Usage: uv run python scripts/research.py TCS [--model sonnet|opus] [--refresh]
Results are cached for 12 hours in data/research/ to spare your plan's usage limits.
"""

from __future__ import annotations

import argparse
import json
import logging
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
from eqr.sources.documents import fetch_documents
from eqr.sources.filings import FilingsSource
from eqr.sources.universe import load_resolver
from eqr.valuation.engine import fetch_price_data, value_company

ROOT = Path(__file__).resolve().parent.parent
CACHE_HOURS = 12


def print_report(data: dict) -> None:
    r, meta = data["report"], data["meta"]
    print(
        f"\n=== {data['symbol']} research ({meta['as_of']}, {meta['model']}, "
        f"{meta['num_turns']} turns, {meta.get('documents_given', 0)} filings read, {meta['duration_ms'] / 1000:.0f}s) ==="
    )
    print(f"\n{r['summary']}\n\nLatest results: {r['latest_results']}")
    print("\nCatalysts:")
    for c in sorted(r["catalysts"], key=lambda c: -c["materiality"]):
        print(
            f"  [{c['direction']:8}] m{c['materiality']} {c['date'] or '?':10} {c['title']} ({c['source_name']})"
        )
    print("\nRegulation:")
    for g in r["regulation"]:
        print(
            f"  [{g['direction']:8}] {g['regulator']}: {g['title']} ({g['status']}, effective {g['effective_date'] or '?'})"
        )
    s = r["sector_view"]
    print(f"\nSector: {s['sector']} - {s['stance']}. {s['reasoning'][:300]}")
    print("\nRisks:")
    for k in sorted(r["risks"], key=lambda k: -k["severity"]):
        print(f"  s{k['severity']} {k['title']}")
    print("\nUpcoming:")
    for e in r["events"]:
        print(f"  {e['date'] or '?':10} {e['event']}")
    print(f"\nBull: {r['bull_case']}\nBear: {r['bear_case']}")
    if r["data_gaps"]:
        print("Gaps: " + "; ".join(r["data_gaps"]))
    if any(data["dropped"].values()):
        print(f"Dropped by sourcing rules: {data['dropped']}")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    resolver = load_resolver(ROOT / "data")
    res = resolver.resolve(args.query)
    if res.match is None:
        print("Not sure which company: " + ", ".join(c.security.symbol for c in res.candidates))
        return 2
    sym, name = res.match.symbol, res.match.name
    out_dir = ROOT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sym}.json"
    if out.exists() and not args.refresh and time.time() - out.stat().st_mtime < CACHE_HOURS * 3600:
        print(f"(cached result from {CACHE_HOURS}h window; --refresh to rerun)")
        print_report(json.loads(out.read_text()))
        return 0

    today = date.today()
    cache = Cache(ROOT / "data" / "cache.sqlite")
    client = NseClient(cache=cache)
    f = load_fundamentals(FilingsSource(client), sym)
    valuation = value_company(
        f, load_market_inputs(), fetch_price_data(sym, [y.fy_end for y in f.years], today), today
    )
    anns = fetch_announcements(client, sym, today - timedelta(days=NEWS_WINDOW_DAYS), today)
    docs = fetch_documents(client, cache, anns)
    brief = build_brief(name, anns[0].industry if anns else None, f, valuation)
    provider = ClaudeCliProvider(workdir=ROOT / "data" / "claude-workdir")
    print(f"Researching {sym} with Claude ({args.model}); this takes a few minutes...")
    try:
        run = run_research(provider, brief, anns, today, model=args.model, documents=docs)
    except LlmError as exc:
        print(f"Research failed ({exc.kind}): {exc}")
        return 1
    data = {
        "symbol": sym,
        "name": name,
        "brief": brief.facts,
        "report": run.report.model_dump(),
        "dropped": run.dropped,
        "meta": run.meta,
    }
    out.write_text(json.dumps(data, indent=1))
    print_report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
