"""Track record: every valuation is saved with its price and signal, then scored against
what the share actually did over 1, 3, 6 and 12 months, relative to the Nifty 50.

The only honest test of the research (LLM) layer is forward like this: the model already
knows what happened before its training cutoff, so past-date tests of it are contaminated.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

HORIZONS = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}
FAIR_BAND = 0.10  # a "fairly valued" call holds if the stock stays within 10% of the market
FIELDS = ("day", "symbol", "price", "signal", "confidence", "low", "mid", "high", "upside")


class Journal:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY, day TEXT NOT NULL, symbol TEXT NOT NULL,
                    price REAL, signal TEXT, confidence TEXT, low REAL, mid REAL, high REAL,
                    upside REAL, engine_version TEXT, payload TEXT,
                    UNIQUE(symbol, day))"""
            )
            self._conn.commit()

    def record_raw(self, row: dict[str, Any], engine_version: str = "", payload: str = "") -> None:
        values = [row.get(k) for k in FIELDS]
        with self._lock:
            self._conn.execute(
                f"INSERT INTO entries ({', '.join(FIELDS)}, engine_version, payload) "
                f"VALUES ({', '.join('?' * (len(FIELDS) + 2))}) "
                "ON CONFLICT(symbol, day) DO UPDATE SET "
                + ", ".join(
                    f"{k}=excluded.{k}" for k in (*FIELDS[2:], "engine_version", "payload")
                ),
                [*values, engine_version, payload],
            )
            self._conn.commit()

    def record(self, report: Any, today: date, engine_version: str) -> None:
        r = report.result
        self.record_raw(
            {
                "day": today.isoformat(),
                "symbol": report.symbol,
                "price": report.price,
                "signal": r.signal,
                "confidence": r.confidence,
                "low": r.low,
                "mid": r.mid,
                "high": r.high,
                "upside": r.upside,
            },
            engine_version=engine_version,
            payload=json.dumps(
                {"implied": report.implied_growth.summary, "type": report.company_type}
            ),
        )

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT id, {', '.join(FIELDS)}, engine_version FROM entries ORDER BY day DESC, symbol"
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _close_on(series: pd.Series, day: date) -> float | None:
    """Last close on or before day (None if the series has nothing that early)."""
    before = series[[d <= day for d in series.index]]
    return float(before.iloc[-1]) if not before.empty else None


def _outcome(signal: str, excess: float) -> str:
    if signal == "Undervalued":
        return "hit" if excess > 0 else "miss"
    if signal == "Overvalued":
        return "hit" if excess < 0 else "miss"
    if signal == "Fairly valued":
        return "hit" if abs(excess) <= FAIR_BAND else "miss"
    return "n/a"


def score_entry(
    e: dict[str, Any], stock: pd.Series, index: pd.Series, today: date
) -> dict[str, Any]:
    """Price return of the stock and of the Nifty 50 from the entry day to each horizon."""
    start = date.fromisoformat(e["day"])
    s0, i0 = _close_on(stock, start), _close_on(index, start)
    out: dict[str, Any] = {}
    for name, days in HORIZONS.items():
        end = start + timedelta(days=days)
        if end > today:
            out[name] = {"outcome": "pending", "excess": None}
            continue
        s1, i1 = _close_on(stock, end), _close_on(index, end)
        if None in (s0, i0, s1, i1):
            out[name] = {"outcome": "no data", "excess": None}
            continue
        sr, ir = s1 / s0 - 1, i1 / i0 - 1  # type: ignore[operator]
        out[name] = {
            "stock_return": sr,
            "index_return": ir,
            "excess": sr - ir,
            "outcome": _outcome(e["signal"], sr - ir),
        }
    return out


def summarise(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per signal and horizon: how many calls have matured, hit rate, mean and median excess."""
    rows = []
    for signal in ("Undervalued", "Fairly valued", "Overvalued"):
        for h in HORIZONS:
            done = [
                s["scores"][h]
                for s in scored
                if s["signal"] == signal and s["scores"][h]["outcome"] in ("hit", "miss")
            ]
            pending = sum(
                1
                for s in scored
                if s["signal"] == signal and s["scores"][h]["outcome"] == "pending"
            )
            ex = [d["excess"] for d in done]
            rows.append(
                {
                    "signal": signal,
                    "horizon": h,
                    "n": len(done),
                    "pending": pending,
                    "hit_rate": (sum(d["outcome"] == "hit" for d in done) / len(done))
                    if done
                    else None,
                    "mean_excess": statistics.mean(ex) if ex else None,
                    "median_excess": statistics.median(ex) if ex else None,
                }
            )
    return rows
