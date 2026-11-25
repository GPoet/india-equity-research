"""Historical backtest of the valuation signal, strictly point-in-time.

At each past date the engine sees only filings already filed (by their NSE timestamp),
prices and dividends up to that date, and beta from the two years before it. Then the
signal is scored on what the share did next, against the Nifty 50.

Prices are put back on each date's share basis (Yahoo back-adjusts for later splits and
bonuses; the filings known then do not), using NSE's as-traded close for that date.
Only rows where a core model ran and confidence is not low are scored; the rest are counted
by reason. Known limits, reported with every run:
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
from eqr.sources.bhavcopy import DailyBar
from eqr.sources.filings import FilingRef, FilingsSource, merge_refs, parse_nse_datetime
from eqr.valuation.blend import CORE_FINANCIAL, CORE_OPERATING
from eqr.valuation.engine import value_company
from eqr.valuation.pricedata import MarketSeries, price_data_as_of, rebased
from eqr.xbrl import Filing

log = logging.getLogger(__name__)

LIMITATIONS = (
    "Universe is today's Nifty 50, so companies that dropped out are missing (survivorship bias).",
    "Market rates (G-sec yield, equity risk premium) are today's, not those at each date.",
    "Price returns only, for the stock and the Nifty 50 alike; dividends are excluded on both sides.",
    "Only the valuation engine is tested; research is scored forward in the journal instead.",
    "Promoter pledges and bank asset quality are not checked in the history test (live pages check them).",
    "Quarterly calls overlap at 6 and 12 months, so observations are not independent; treat small differences as noise.",
)

CORE = CORE_OPERATING | CORE_FINANCIAL
NO_CORE = "no core model (DCF, owner earnings, EPV, residual income, justified P/B)"
SPLIT_NOISE = 0.02  # as-traded / adjusted within 2% of 1 = no split since, just rounding


def share_basis_factor(as_traded: float | None, adjusted: float | None) -> float | None:
    """as-traded close / Yahoo's adjusted close on the same day. None when it cannot be trusted
    (missing, or below 1: adjustments only ever lower old prices)."""
    if not as_traded or not adjusted:
        return None
    f = as_traded / adjusted
    if abs(f - 1) <= SPLIT_NOISE:
        return 1.0
    return f if f > 1 else None


def usable(row: dict[str, Any]) -> tuple[bool, str]:
    if row.get("confidence") == "low":
        return False, "low confidence"
    if not CORE & set(row.get("used") or ()):
        return False, NO_CORE
    return True, ""


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
    as_traded: DailyBar | None,
) -> dict[str, Any] | str:
    """A valuation row, or the reason there is none."""
    known_urls = {r.xbrl_url for r in refs_known_on([r for r, _ in pairs], as_of)}
    chosen = [(r, f) for r, f in pairs if r.xbrl_url in known_urls]
    consolidated = any(r.consolidated for r, _ in chosen)
    chosen = [(r, f) for r, f in chosen if r.consolidated == consolidated]
    if len(chosen) < 8:
        return "under two years of filings"
    if as_traded is None:
        return "no as-traded NSE price"
    adjusted = series.closes.get(as_traded.trade_date)
    factor = share_basis_factor(as_traded.close, adjusted)
    if factor is None:
        return "price basis could not be matched"
    f = build_fundamentals(symbol, chosen)
    prices = price_data_as_of(rebased(series, factor), [y.fy_end for y in f.years], as_of)
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
        "used": sorted(r.used),
        "share_basis_factor": factor,
        "company_type": report.company_type,
    }


def run_symbol(
    source: FilingsSource,
    symbol: str,
    dates: list[date],
    series: MarketSeries,
    market: MarketInputs,
    as_traded: dict[date, DailyBar | None],
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    """(rows without scores, skipped dates by reason, errors). Errors include unreadable
    filings, which a later run may read; callers should not cache a run with errors."""
    refs = source.list_raw(symbol)
    pairs, errors = [], 0
    for r in refs:
        try:
            pairs.append((r, source.fetch(r)))
        except Exception as exc:  # noqa: BLE001 - one unreadable filing must not drop the company
            errors += 1
            log.warning("%s %s unreadable: %s", symbol, r.period_end, exc)
    out: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for d in dates:
        try:
            row = value_as_of(symbol, pairs, series, market, d, as_traded.get(d))
        except Exception as exc:  # noqa: BLE001 - record and continue
            errors += 1
            log.warning("%s as of %s failed: %s", symbol, d, exc)
            continue
        if isinstance(row, str):
            skipped[row] = skipped.get(row, 0) + 1
            continue
        out.append(row)
    return out, skipped, errors


def score_rows(
    rows: list[dict[str, Any]], series: MarketSeries, today: date
) -> list[dict[str, Any]]:
    """Scores use Yahoo's adjusted closes: returns are the same on any share basis."""
    return [
        {**r, "scores": score_entry(r, series.closes, series.index_closes, today)} for r in rows
    ]


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kept, excluded = [], {}
    for r in rows:
        ok, why = usable(r)
        if ok:
            kept.append(r)
        else:
            excluded[why] = excluded.get(why, 0) + 1
    by_horizon, base_rate = {}, {}
    for h in HORIZONS:
        flat = [{"upside": r["upside"], "excess": r["scores"][h].get("excess")} for r in kept]
        by_horizon[h] = upside_rank_stats(flat)
        scored = [x["excess"] for x in flat if x["excess"] is not None]
        # How often any stock beat the Nifty: the bar an "Undervalued" hit rate must clear.
        base_rate[h] = sum(e > 0 for e in scored) / len(scored) if scored else None
    return {
        "by_signal": summarise(kept),
        "upside_vs_return": by_horizon,
        "base_rate": base_rate,
        "observations": len(rows),
        "usable": len(kept),
        "excluded": excluded,
    }
