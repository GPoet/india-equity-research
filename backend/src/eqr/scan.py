"""Daily scan of the Nifty 500: every company gets the full valuation, its quality and
red-flag checks, ownership, and the Agents Forecast, priced at NSE's official close.
Companies are ranked by the forecast's odds of beating the Nifty over the next month.

The held-out test of that forecast showed no edge (see forecast.model), so the ranking is a
screen, not a prediction. Every day's ranking is saved so it can be scored as time passes."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from eqr.forecast.dataset import observation
from eqr.forecast.model import ForecastModel, forecast
from eqr.fundamentals import load_fundamentals
from eqr.market import MarketInputs
from eqr.pipeline import Context, ownership
from eqr.sources.bhavcopy import DailyBar
from eqr.valuation.blend import RED_FLAG_VERDICTS
from eqr.valuation.engine import fetch_market_series, value_company
from eqr.valuation.pricedata import price_data_as_of

log = logging.getLogger(__name__)


def should_run(last_price_day: date | None, latest_file_day: date | None) -> bool:
    """Scan when NSE has published a trading day the last scan did not use. Covers the evening
    run and catching up after days the app was off."""
    if latest_file_day is None:
        return False
    return last_price_day is None or latest_file_day > last_price_day


def order_universe(symbols: list[str], nifty50: set[str], turnover: dict[str, float]) -> list[str]:
    """Nifty 50 first (useful results early on a first, slow run), then by traded value."""
    return sorted(symbols, key=lambda s: (s not in nifty50, -turnover.get(s, 0.0)))


def rank(
    rows: list[dict[str, Any]], n: int = 20
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(top picks without red flags, every forecast row ranked by odds of beating the Nifty)."""
    ranked = sorted(
        (r for r in rows if r.get("forecast")),
        key=lambda r: r["forecast"]["1m"]["p_beat_nifty"],
        reverse=True,
    )
    picks = [r for r in ranked if not r.get("red_flags")][:n]
    return picks, ranked


def scan_symbol(
    ctx: Context,
    symbol: str,
    name: str,
    bar: DailyBar,
    nifty: pd.Series,
    market: MarketInputs,
    model: ForecastModel | None,
) -> dict[str, Any]:
    day = bar.trade_date
    f = load_fundamentals(ctx.filings, symbol)
    series = fetch_market_series(symbol, index=nifty)
    prices = price_data_as_of(
        series, [y.fy_end for y in f.years], day, price=bar.close, price_as_of=day.isoformat()
    )
    report = value_company(f, market, prices, day, ownership(ctx, symbol))
    r = report.result
    row: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "price": bar.close,
        "change_day": bar.close / bar.prev_close - 1 if bar.prev_close else None,
        "volume": bar.volume,
        "turnover": bar.turnover,
        "signal": r.signal,
        "confidence": r.confidence,
        "fair_value": r.mid,
        "upside": r.upside,
        # Risk verdicts from the investor checks keep a stock out of the picks; model notes
        # (a formula giving a negative equity value) are shown but do not.
        "red_flags": [
            f"{lens.name}: {lens.verdict}"
            for lens in report.lenses
            if lens.applicable and lens.verdict in RED_FLAG_VERDICTS.get(lens.key, set())
        ],
        "model_notes": [f for f in r.red_flags if "negative equity value" in f],
        "company_type": report.company_type,
        "forecast": None,
    }
    if model is None:
        return row
    pairs = []
    for ref in ctx.filings.list_raw(symbol):
        try:
            pairs.append((ref, ctx.filings.fetch(ref)))
        except Exception as exc:  # noqa: BLE001 - one unreadable filing must not drop the company
            log.warning("Scan: %s %s unreadable: %s", symbol, ref.period_end, exc)
    x = observation(
        symbol,
        pairs,
        series,
        day,
        {"upside": r.upside, "confidence": r.confidence, "used": list(r.used)},
    )
    if x is None:
        return row
    fc = forecast(model, x, bar.close, prices.beta, market.cost_of_equity(1.0) / 100, day)
    row["forecast"] = {
        h.horizon: {
            "target_date": h.target_date,
            "median": h.median,
            "expected_return": h.median / bar.close - 1,
            "band80": list(h.band80),
            "p_up": h.p_up,
            "p_beat_nifty": h.p_beat_nifty,
            "results_in_window": h.results_in_window,
            "lean": h.lean,
        }
        for h in fc
    }
    return row
