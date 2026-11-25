"""Historical backtest of the valuation signal, strictly point-in-time.

At each past date the engine sees only filings already filed (by their NSE timestamp),
prices and dividends up to that date, and beta from the two years before it. Then the
signal is scored on what the share did next, against the Nifty 50.

Known limits, reported with every run:
- Universe is today's Nifty 50: companies that fell out of the index are missing
  (survivorship bias, flatters results).
- Market inputs (G-sec, risk premium) are today's values, not those of each date.
- Price returns only, for both the stock and the Nifty (dividends excluded on both sides).
- Only the valuation engine is tested. The research layer cannot be backtested honestly:
  the model knows what happened before its training cutoff. It is scored forward instead.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import pandas as pd

from eqr.fundamentals import build_fundamentals
from eqr.journal import HORIZONS, score_entry, summarise
from eqr.market import MarketInputs
from eqr.sources.filings import FilingRef, FilingsSource, merge_refs, parse_nse_datetime
from eqr.valuation.engine import value_company
from eqr.valuation.pricedata import MarketSeries, price_data_as_of
from eqr.xbrl import Filing

log = logging.getLogger(__name__)

LIMITATIONS = (
    "Universe is today's Nifty 50, so companies that dropped out are missing (survivorship bias).",
    "Market rates (G-sec yield, equity risk premium) are today's, not those at each date.",
    "Price returns only, for the stock and the Nifty 50 alike; dividends are excluded on both sides.",
    "Only the valuation engine is tested; research is scored forward in the journal instead.",
)


def _filed(ref: FilingRef) -> datetime | None:
    try:
        return parse_nse_datetime(ref.filed_at)
    except ValueError:
        return None


def refs_known_on(refs: Iterable[FilingRef], as_of: date) -> list[FilingRef]:
    """Filings already public on as_of (filed before that day), one per period, the latest
    version filed by then. Filings without a filing timestamp are excluded: they cannot be
    shown to have been public."""
    cutoff = datetime(as_of.year, as_of.month, as_of.day)
    known = [r for r in refs if (f := _filed(r)) is not None and f < cutoff]
    by_key: dict[tuple[date, bool], FilingRef] = {}
    for r in sorted(known, key=lambda r: _filed(r)):  # type: ignore[arg-type, return-value]
        by_key[(r.period_end, r.consolidated)] = r  # later filing (revision) replaces earlier
    return merge_refs([], by_key.values())


def quarterly_dates(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        month = d.month + 3
        d = date(d.year + (month - 1) // 12, (month - 1) % 12 + 1, d.day)
    return out


def upside_rank_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Does a bigger estimated upside come before a bigger excess return? Spearman rank
    correlation plus the top-fifth vs bottom-fifth excess return."""
    df = pd.DataFrame(
        [r for r in rows if r.get("upside") is not None and r.get("excess") is not None]
    )
    if len(df) < 5:
        return {
            "n": len(df),
            "spearman": None,
            "top_quintile_excess": None,
            "bottom_quintile_excess": None,
        }
    df = df.sort_values("upside")
    fifth = max(len(df) // 5, 1)
    return {
        "n": len(df),
        "spearman": float(
            df["upside"].rank().corr(df["excess"].rank())
        ),  # Spearman = Pearson on ranks
        "top_quintile_excess": float(df["excess"].iloc[-fifth:].mean()),
        "bottom_quintile_excess": float(df["excess"].iloc[:fifth].mean()),
    }


def value_as_of(
    symbol: str,
    pairs: list[tuple[FilingRef, Filing]],
    series: MarketSeries,
    market: MarketInputs,
    as_of: date,
) -> dict[str, Any] | None:
    known_urls = {r.xbrl_url for r in refs_known_on([r for r, _ in pairs], as_of)}
    chosen = [(r, f) for r, f in pairs if r.xbrl_url in known_urls]
    consolidated = any(r.consolidated for r, _ in chosen)
    chosen = [(r, f) for r, f in chosen if r.consolidated == consolidated]
    if len(chosen) < 8:
        return None  # under two years of filings: not enough to value
    f = build_fundamentals(symbol, chosen)
    prices = price_data_as_of(series, [y.fy_end for y in f.years], as_of)
    report = value_company(f, market, prices, as_of)
    r = report.result
    return {
        "symbol": symbol,
        "day": as_of.isoformat(),
        "price": prices.price,
        "signal": r.signal,
        "confidence": r.confidence,
        "mid": r.mid,
        "low": r.low,
        "high": r.high,
        "upside": r.upside,
        "company_type": report.company_type,
    }


def run_symbol(
    source: FilingsSource,
    symbol: str,
    dates: list[date],
    series: MarketSeries,
    market: MarketInputs,
    today: date,
) -> list[dict[str, Any]]:
    refs = source.list_raw(symbol)
    pairs = []
    for r in refs:
        try:
            pairs.append((r, source.fetch(r)))
        except Exception as exc:  # noqa: BLE001 - one unreadable filing must not drop the company
            log.warning("%s %s unreadable: %s", symbol, r.period_end, exc)
    out = []
    for d in dates:
        try:
            row = value_as_of(symbol, pairs, series, market, d)
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("%s as of %s failed: %s", symbol, d, exc)
            continue
        if row is None:
            continue
        row["scores"] = score_entry(row, series.closes, series.index_closes, today)
        out.append(row)
    return out


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_horizon = {}
    for h in HORIZONS:
        flat = [{"upside": r["upside"], "excess": r["scores"][h].get("excess")} for r in rows]
        by_horizon[h] = upside_rank_stats(flat)
    return {"by_signal": summarise(rows), "upside_vs_return": by_horizon, "observations": len(rows)}
