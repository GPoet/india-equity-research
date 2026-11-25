"""Daily price history for BSE-listed companies, from BSE itself (Yahoo barely covers BSE:
ABB.BO had 8 days). BSE's history is as traded, so splits and bonuses from its corporate
actions are divided out to put old prices on today's share basis, as Yahoo does for NSE."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from eqr.nse_client import NseClient
from eqr.valuation.pricedata import MarketSeries

HISTORY_YEARS = 6  # beta (2y), forecast (1y) and fiscal-year-end prices for the valued years
PRICE_TTL = 20 * 3600
ACTIONS_TTL = 7 * 24 * 3600
_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
_SPLIT = re.compile(r"From\s*R[se]\.?\s*([\d.]+)\s*/?-?.*?to\s*R[se]\.?\s*([\d.]+)", re.I)


def share_factor(text: str) -> float | None:
    """New shares per old share: bonus a:b -> (a+b)/b; split from X to Y -> X/Y."""
    t = text or ""
    if "split" in t.lower() and (m := _SPLIT.search(t)):
        old, new = float(m.group(1)), float(m.group(2))
        return old / new if new else None
    if ("bonus" in t.lower() or t.lower().startswith("issue")) and (m := _RATIO.search(t)):
        new, held = float(m.group(1)), float(m.group(2))
        return (new + held) / held if held else None
    return None


def _day(text: str) -> date | None:
    for fmt in ("%d %b %Y", "%d-%B-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime((text or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_actions(payload: dict[str, Any]) -> tuple[dict[date, float], dict[date, float]]:
    """(share factor by ex-date, dividend per share by ex/record date)."""
    seen: dict[tuple[date, str], float] = {}
    for row in payload.get("Table2") or []:
        d, f = _day(row.get("Ex_date")), share_factor(row.get("purpose") or "")
        if d and f:
            kind = "split" if "split" in (row.get("purpose") or "").lower() else "bonus"
            seen[(d, kind)] = f
    for row in payload.get("Table1") or []:  # longer bonus/split history
        d = _day(row.get("BCRD_FROM"))
        kind = (row.get("XTYPE") or "").strip().lower()
        f = share_factor(f"{kind} {row.get('VALUE') or ''}")
        if d and f:
            seen.setdefault((d, "split" if "split" in kind else "bonus"), f)
    factors: dict[date, float] = {}
    for (d, _), f in seen.items():
        factors[d] = factors.get(d, 1.0) * f
    divs: dict[date, float] = {}
    for row in payload.get("Table") or []:
        d, amt = _day(row.get("BCRD_from")), row.get("Amount")
        if d and isinstance(amt, (int, float)) and amt > 0:
            divs[d] = divs.get(d, 0.0) + float(amt)
    return factors, divs


def parse_price_csv(text: str) -> pd.DataFrame:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        d = _day(r.get("Date") or "")
        try:
            close = float(r["Close Price"])
        except (KeyError, ValueError, TypeError):
            continue
        if d:
            rows.append(
                {
                    "day": d,
                    "close": close,
                    "volume": float(r.get("No.of Shares") or 0),
                    "turnover": float(r.get("Total Turnover (Rs.)") or 0),
                }
            )
    df = (
        pd.DataFrame(rows).drop_duplicates("day").set_index("day").sort_index()
        if rows
        else pd.DataFrame()
    )
    return df


def adjust(
    closes: pd.Series, factors: dict[date, float], divs: dict[date, float]
) -> tuple[pd.Series, pd.Series]:
    """Divide every price (and dividend) before each ex-date by that action's factor."""
    out = closes.astype(float).copy()
    d_out = pd.Series(divs, dtype=float).sort_index() if divs else pd.Series(dtype=float)
    for ex, f in factors.items():
        out[[d < ex for d in out.index]] /= f
        if len(d_out):
            d_out[[d < ex for d in d_out.index]] /= f
    return out, d_out


def bse_market_series(
    client: NseClient, code: str, nifty: pd.Series, today: date | None = None
) -> MarketSeries:
    today = today or date.today()
    start = today - timedelta(days=365 * HISTORY_YEARS)
    text = client.get_text(
        f"{client_api(client)}StockPriceCSVDownload/w?pageType=0&rbType=D&Scode={code}"
        f"&FDates={start:%d/%m/%Y}&TDates={today:%d/%m/%Y}&Seg=C",
        ttl=PRICE_TTL,
        validate=lambda t: t.lstrip("﻿").startswith("Date,"),
    )
    px = parse_price_csv(text.lstrip("﻿"))
    if px.empty:
        raise ValueError(f"No BSE price history for {code}")
    payload = client.get_json(f"CorporateAction/w?scripcode={code}", ttl=ACTIONS_TTL)
    factors, divs = parse_actions(payload if isinstance(payload, dict) else {})
    closes, dividends = adjust(px["close"], factors, divs)
    return MarketSeries(closes, nifty, dividends)


def client_api(client: NseClient) -> str:
    return client._api  # noqa: SLF001 - the BSE client's API root
