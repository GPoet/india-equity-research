"""Market overview for the home page, from NSE's daily files: movers over a day, week and
month, unusual volume, most traded, sector moves, and the filings behind the week's biggest
moves. Returns are chained from daily close / previous close, with split and bonus ex-dates
divided out (NSE does not adjust the previous close on those days)."""

from __future__ import annotations

import re
from datetime import date
from statistics import fmean
from typing import Any

import pandas as pd

from eqr.sources.bhavcopy import DailyBar

WINDOWS = {"day": 1, "week": 5, "month": 21}
MIN_TURNOVER = 1e8  # Rs 10 crore a day on average: below this, moves are mostly noise
VOLUME_DAYS = 20

DayFiles = list[tuple[date, dict[str, DailyBar]]]  # oldest first


def window_returns(
    files: DayFiles, factors: dict[tuple[str, date], float], k: int
) -> dict[str, float]:
    """Return over the last k trading days per symbol; a symbol missing on more than one of
    those days (new listing, suspension) is left out."""
    window = files[-k:]
    out: dict[str, float] = {}
    for sym in window[-1][1]:
        growth, missing = 1.0, 0
        for d, bars in window:
            b = bars.get(sym)
            if b is None or not b.prev_close:
                missing += 1
                continue
            growth *= b.close * factors.get((sym, d), 1.0) / b.prev_close
        if missing <= (0 if k == 1 else 1):
            out[sym] = growth - 1
    return out


def avg_turnover(files: DayFiles, k: int) -> dict[str, float]:
    tot: dict[str, list[float]] = {}
    for _, bars in files[-k:]:
        for s, b in bars.items():
            tot.setdefault(s, []).append(b.turnover)
    return {s: fmean(v) for s, v in tot.items()}


def unusual_volume(
    files: DayFiles, factors: dict[tuple[str, date], float], n: int = 10
) -> list[dict[str, Any]]:
    """Today's volume against the average of the previous 20 days (put on today's share basis
    when a split or bonus happened in between). Only liquid stocks."""
    today_day, today = files[-1]
    prior = files[-1 - VOLUME_DAYS : -1]
    out = []
    for sym, b in today.items():
        if b.turnover < MIN_TURNOVER:
            continue
        vols = []
        for d, bars in prior:
            p = bars.get(sym)
            if p is None:
                continue
            later = 1.0
            for (s, ex), f in factors.items():
                if s == sym and d < ex <= today_day:
                    later *= f
            vols.append(p.volume * later)
        if len(vols) < VOLUME_DAYS // 2 or fmean(vols) == 0:
            continue
        out.append(
            {
                "symbol": sym,
                "ratio": b.volume / fmean(vols),
                "change": _change(b, factors, today_day),
                "turnover": b.turnover,
            }
        )
    return sorted(out, key=lambda x: x["ratio"], reverse=True)[:n]


def _change(b: DailyBar, factors: dict[tuple[str, date], float], d: date) -> float | None:
    return b.close * factors.get((b.symbol, d), 1.0) / b.prev_close - 1 if b.prev_close else None


def most_traded(
    today: dict[str, DailyBar],
    n: int = 10,
    day: date | None = None,
    factors: dict[tuple[str, date], float] | None = None,
) -> list[dict[str, Any]]:
    top = sorted(today.values(), key=lambda b: b.turnover, reverse=True)[:n]
    return [
        {
            "symbol": b.symbol,
            "turnover": b.turnover,
            "close": b.close,
            "change": _change(b, factors or {}, day or b.trade_date),
        }
        for b in top
    ]


def movers(
    files: DayFiles, factors: dict[tuple[str, date], float], universe: set[str], n: int = 10
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Best and worst per window among the universe's liquid stocks."""
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, k in WINDOWS.items():
        rets = window_returns(files, factors, k)
        turn = avg_turnover(files, k)
        rows = [
            {"symbol": s, "change": r, "close": files[-1][1][s].close}
            for s, r in rets.items()
            if s in universe and turn.get(s, 0) >= MIN_TURNOVER
        ]
        rows.sort(key=lambda x: x["change"], reverse=True)
        out[name] = {"best": rows[:n], "worst": rows[::-1][:n]}
    return out


def sector_moves(closes: pd.DataFrame, indices: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """indices: label -> NSE index name. Change over each window from daily index closes."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name, k in WINDOWS.items():
        rows = []
        for label, idx in indices.items():
            if idx not in closes:
                continue
            s = closes[idx].dropna()
            if len(s) <= k or s.index[-1] != closes.index[-1]:
                continue  # not enough history or no close on the latest day
            rows.append(
                {"sector": label, "index": idx, "change": float(s.iloc[-1] / s.iloc[-1 - k] - 1)}
            )
        out[name] = sorted(rows, key=lambda x: x["change"], reverse=True)
    return out


_BOILERPLATE = re.compile(
    r"^.*?has informed the Exchange\s+(?:regarding|about|that|of)?\s*", re.I | re.S
)


def headline(text: str) -> str:
    """'APL Apollo Tubes Limited has informed the Exchange regarding Outcome of Board Meeting held
    on ...' -> 'Outcome of Board Meeting held on ...'."""
    out = _BOILERPLATE.sub("", text.strip(), count=1).strip()
    return (out[:1].upper() + out[1:]) if out else text.strip()
