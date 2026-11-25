"""Daily scan of the Nifty 500: every company gets the full valuation, its quality and
red-flag checks, ownership, and the Agents Forecast, priced at NSE's official close.
Companies are ranked by the forecast's odds of beating the Nifty over the next month.

The held-out test of that forecast showed no edge (see forecast.model), so the ranking is a
screen, not a prediction. Every day's ranking is saved so it can be scored as time passes."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from eqr.backtest import refs_known_on
from eqr.forecast.dataset import observation
from eqr.forecast.model import ForecastModel, forecast
from eqr.fundamentals import load_fundamentals
from eqr.market import MarketInputs
from eqr.nse_client import NseError
from eqr.pipeline import Context, ownership
from eqr.sources.announcements import Announcement
from eqr.sources.bhavcopy import DailyBar
from eqr.sources.filings import FilingRef
from eqr.valuation.blend import RED_FLAG_VERDICTS
from eqr.valuation.engine import fetch_market_series, value_company
from eqr.valuation.pricedata import beta_as_of, price_data_as_of

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


PICK_MIN_TURNOVER = 1e7  # Rs 1 crore traded on the day: below this a stock cannot really be bought
RESULT_CATEGORIES = frozenset(
    {"Financial Result Updates", "Outcome of Board Meeting", "Integrated Filing- Financials"}
)


def symbols_with_new_results(anns: list[Announcement]) -> set[str]:
    return {a.symbol for a in anns if a.category in RESULT_CATEGORIES}


def rank(
    rows: list[dict[str, Any]], n: int = 20
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(top picks: no red flags and liquid enough to buy, every forecast row ranked by odds of
    beating the Nifty)."""
    ranked = sorted(
        (r for r in rows if r.get("forecast")),
        key=lambda r: r["forecast"]["1m"]["p_beat_nifty"],
        reverse=True,
    )
    picks = [
        r
        for r in ranked
        if not r.get("red_flags") and (r.get("turnover") or 0) >= PICK_MIN_TURNOVER
    ][:n]
    return picks, ranked


def _valuation(
    ctx: Context, symbol: str, series: Any, bar: DailyBar, market: MarketInputs
) -> dict[str, Any]:
    """Valuation fields for the row. Raises when the company cannot be valued (no usable
    filings: new listings, SME half-yearly filers, unusual formats)."""
    day = bar.trade_date
    f = load_fundamentals(ctx.filings, symbol)
    prices = price_data_as_of(
        series, [y.fy_end for y in f.years], day, price=bar.close, price_as_of=day.isoformat()
    )
    report = value_company(f, market, prices, day, ownership(ctx, symbol))
    r = report.result
    return {
        "signal": r.signal,
        "confidence": r.confidence,
        "fair_value": r.mid,
        "upside": r.upside,
        "used": list(r.used),
        "beta": prices.beta,
        # Risk verdicts from the investor checks keep a stock out of the picks; model notes
        # (a formula giving a negative equity value) are shown but do not.
        "red_flags": [
            f"{lens.name}: {lens.verdict}"
            for lens in report.lenses
            if lens.applicable and lens.verdict in RED_FLAG_VERDICTS.get(lens.key, set())
        ],
        "model_notes": [f for f in r.red_flags if "negative equity value" in f],
        "company_type": report.company_type,
    }


def _current_refs(refs: list[FilingRef], day: date) -> list[FilingRef]:
    """The filings a scan on `day` needs: the latest version of each quarter on the company's
    main basis (consolidated when it reports one). The same set the valuation already
    downloaded, so the forecast adds no NSE requests."""
    known = refs_known_on(refs, day + timedelta(days=1))  # filed up to the end of `day`
    consolidated = any(r.consolidated for r in known)
    return [r for r in known if r.consolidated == consolidated]


def scan_symbol(
    ctx: Context,
    symbol: str,
    name: str,
    bar: DailyBar,
    nifty: pd.Series,
    market: MarketInputs,
    model: ForecastModel | None,
) -> dict[str, Any]:
    """One row per traded stock. Prices are required; the valuation is not: a company that
    cannot be valued still gets its price-based forecast, with the reason noted."""
    day = bar.trade_date
    series = fetch_market_series(symbol, index=nifty)
    row: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "series": bar.series,
        "price": bar.close,
        "change_day": bar.close / bar.prev_close - 1 if bar.prev_close else None,
        "volume": bar.volume,
        "turnover": bar.turnover,
        "signal": "Not valued",
        "confidence": None,
        "fair_value": None,
        "upside": None,
        "red_flags": [],
        "model_notes": [],
        "company_type": None,
        "valuation_note": None,
        "forecast": None,
    }
    try:
        v = _valuation(ctx, symbol, series, bar, market)
        beta = v.pop("beta")
        row.update(v)
    except (ValueError, NseError, KeyError, ZeroDivisionError) as exc:
        row["valuation_note"] = f"Could not be valued: {str(exc)[:160]}"
        beta, _ = beta_as_of(series.closes, series.index_closes, day)
    if model is None:
        return row
    pairs = []
    try:
        refs = _current_refs(ctx.filings.list_raw(symbol), day)
    except (ValueError, NseError):
        refs = []
    for ref in refs:
        try:
            pairs.append((ref, ctx.filings.fetch(ref)))
        except Exception as exc:  # noqa: BLE001 - one unreadable filing must not drop the company
            log.warning("Scan: %s %s unreadable: %s", symbol, ref.period_end, exc)
    value_row = (
        {"upside": row["upside"], "confidence": row["confidence"], "used": row.get("used", [])}
        if row["confidence"]
        else None
    )
    x = observation(symbol, pairs, series, day, value_row)
    if x is None:
        row["forecast_note"] = "Under a year of trading: no forecast"
        return row
    fc = forecast(model, x, bar.close, beta, market.cost_of_equity(1.0) / 100, day)
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
