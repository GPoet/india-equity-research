"""Research a company with Claude (your local Claude Code login) and print the report.

Usage: uv run python scripts/research.py TCS [--model sonnet|opus] [--refresh]
Results are cached for 12 hours per company and model in data/research/ to spare your
plan's usage limits.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from eqr.llm.claude_cli import LlmError
from eqr.pipeline import Context, research


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

    ctx = Context()
    res = ctx.resolver.resolve(args.query)
    if res.match is None:
        print("Not sure which company: " + ", ".join(c.security.symbol for c in res.candidates))
        return 2
    sym, name = res.match.symbol, res.match.name
    cached = None if args.refresh else ctx.research_store.load(sym, args.model)
    if cached:
        print("(cached result, under 12h old; --refresh to rerun)")
        print_report(cached)
        return 0
    print(f"Researching {sym} with Claude ({args.model}); this takes a few minutes...")
    try:
        data = research(ctx, sym, name, date.today(), model=args.model)
    except LlmError as exc:
        print(f"Research failed ({exc.kind}): {exc}")
        return 1
    print_report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
