"""Fit the 1-2 month forecast on history and test it on later years it never saw.

Usage: uv run python scripts/forecast_fit.py [--split 2024-01-01] [--symbols TCS,INFY]
Monthly dates on today's Nifty 50 from Jul 2019. Fits on dates before --split, reports skill on
dates from --split on, then refits on everything for live use (same recipe, more data).
Writes config/forecast_model.json and data/forecast/eval.json. Inputs per company are cached
in data/forecast/obs/<engine version>/ (only runs without errors); outcomes are recomputed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

from eqr.app.serialize import clean
from eqr.backtest import value_as_of
from eqr.forecast.dataset import observation, outcomes
from eqr.forecast.model import HORIZONS, ForecastModel, evaluate, fit_horizon, shows_edge
from eqr.pipeline import Context
from eqr.sources.bhavcopy import BhavcopySource
from eqr.valuation import ENGINE_VERSION
from eqr.valuation.engine import fetch_market_series

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "forecast"
NIFTY50 = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"


def monthly(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = date(d.year + d.month // 12, d.month % 12 + 1, d.day)
    return out


def build(
    ctx: Context, sym: str, dates: list[date], day_bars: dict, market
) -> tuple[list[dict], int]:
    series = fetch_market_series(sym)
    cache = OUT / "obs" / ENGINE_VERSION / f"{sym.replace('&', '_')}.json"
    errors = 0
    if cache.exists():
        obs = json.loads(cache.read_text())
    else:
        pairs = []
        for r in ctx.filings.list_raw(sym):
            try:
                pairs.append((r, ctx.filings.fetch(r)))
            except Exception:  # noqa: BLE001 - counted; the run is not cached
                errors += 1
        obs = []
        for d in dates:
            try:
                v = value_as_of(sym, pairs, series, market, d, day_bars[d].get(sym))
                o = observation(sym, pairs, series, d, v if isinstance(v, dict) else None)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logging.warning("%s %s: %s", sym, d, exc)
                continue
            if o is not None:
                obs.append(o)
        if errors == 0:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(clean(obs)))
    return [{**o, **outcomes(series, date.fromisoformat(o["day"]))} for o in obs], errors


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-07-15")
    ap.add_argument("--split", default="2024-01-01")
    ap.add_argument("--symbols", default="")
    args = ap.parse_args()
    ctx = Context()
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or [
        r["Symbol"].strip()
        for r in csv.DictReader(io.StringIO(ctx.client.get_bytes(NIFTY50).decode("utf-8-sig")))
    ]
    dates = monthly(date.fromisoformat(args.start), date.today())
    bhav = BhavcopySource(ctx.client, ctx.cache)
    day_bars = {d: bhav.on_or_before(d) for d in dates}
    market = ctx.market()
    rows: list[dict] = []
    for i, sym in enumerate(syms, 1):
        t0 = time.time()
        try:
            got, errors = build(ctx, sym, dates, day_bars, market)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(syms)}] {sym}: skipped ({type(exc).__name__}: {exc})", flush=True)
            continue
        rows.extend(got)
        print(
            f"[{i}/{len(syms)}] {sym}: {len(got)} months, {errors} errors, {time.time() - t0:.0f}s",
            flush=True,
        )

    split = args.split
    train = [r for r in rows if r["day"] < split]
    test = [r for r in rows if r["day"] >= split]
    results, edge, horizons = {}, {}, {}
    for name in HORIZONS:
        held_out = evaluate(fit_horizon(train, name), test, name)
        results[name] = {
            "train_rows": sum(r.get(f"y_{name}") is not None for r in train),
            **held_out,
        }
        edge[name] = shows_edge(held_out)
        horizons[name] = fit_horizon(rows, name)  # same recipe on all data, for live use
    model = ForecastModel(horizons, f"{args.start} to {split}", f"{split} on", results, edge)
    model.save()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eval.json").write_text(
        json.dumps(
            clean(
                {
                    "run_at": date.today(),
                    "engine_version": ENGINE_VERSION,
                    "symbols": len(syms),
                    "observations": len(rows),
                    "split": split,
                    "test": results,
                    "has_edge": edge,
                    "coefs": {k: h.coefs for k, h in horizons.items()},
                }
            ),
            indent=2,
        )
    )
    for name, t in results.items():
        print(
            f"\n{name}: held-out n={t['n']} over {t.get('dates')} dates | rank IC {t.get('rank_ic')} "
            f"(t {t.get('rank_ic_t')}) | top-bottom fifth {t.get('top_minus_bottom')} | "
            f"direction right {t.get('direction_right')} vs base {t.get('base_rate_beat_nifty')} | "
            f"80% band held {t.get('coverage_80')} | edge: {edge[name]}"
        )
        print("   weights (per 1 sd):", {k: round(v, 4) for k, v in horizons[name].coefs.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
