"""Sector strength, valuation and co-movement from daily index closes.

Strength = performance relative to the Nifty 50 over 3 and 6 months plus the 200-day
trend. Co-movement uses weekly returns with the market's move removed, otherwise every
sector looks correlated with every other through the Nifty.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
TREND_DAYS = 200
MIN_TREND_DAYS = 60  # indices NSE launched recently get a trend over what exists
MIN_WEEKS = 26


def _ret(series: pd.Series, n: int) -> float:
    s = series.dropna()
    if len(s) <= n:
        return np.nan
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1)


def sector_scores(closes: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """One row per index: returns, relative strength, trend, distance from high, stance."""
    bench = closes[benchmark]
    rows = {}
    for name in closes.columns:
        s = closes[name].dropna()
        row = {f"ret_{k}": _ret(s, n) for k, n in DAYS.items()}
        row["rs_3m"] = row["ret_3m"] - _ret(bench, DAYS["3m"])
        row["rs_6m"] = row["ret_6m"] - _ret(bench, DAYS["6m"])
        trend_window = min(TREND_DAYS, len(s))
        row["vs_200dma"] = (
            float(s.iloc[-1] / s.iloc[-trend_window:].mean() - 1)
            if trend_window >= MIN_TREND_DAYS
            else np.nan
        )
        row["history_days"] = len(s)
        window = s.iloc[-DAYS["12m"] :]
        row["from_52w_high"] = float(s.iloc[-1] / window.max() - 1) if len(window) else np.nan
        rows[name] = row
    df = pd.DataFrame.from_dict(rows, orient="index")

    def stance(r: pd.Series) -> str:
        if pd.isna(r["rs_3m"]) or pd.isna(r["vs_200dma"]):
            return "insufficient history"
        short = pd.isna(r["rs_6m"])  # recently launched index: judge on 3 months + trend
        rs = [r["rs_3m"]] if short else [r["rs_3m"], r["rs_6m"]]
        if all(x > 0 for x in rs) and r["vs_200dma"] > 0:
            label = "bullish"
        elif all(x < 0 for x in rs) and r["vs_200dma"] < 0:
            label = "bearish"
        else:
            label = "neutral"
        return f"{label} (short history)" if short else label

    df["stance"] = df.apply(stance, axis=1)
    rs6 = df["rs_6m"].fillna(df["rs_3m"])  # short-history indices: 3-month strength stands in
    df["score"] = 0.4 * df["rs_3m"] + 0.4 * rs6 + 0.2 * df["vs_200dma"]
    return df.sort_values("score", ascending=False)


def weekly_excess(closes: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    weekly = closes.resample("W-FRI").last().pct_change(fill_method=None).iloc[1:]
    return weekly.sub(weekly[benchmark], axis=0).drop(columns=[benchmark])


def excess_correlations(closes: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """Correlation of weekly returns after removing the benchmark's move."""
    return weekly_excess(closes, benchmark).corr(min_periods=MIN_WEEKS)


def lead_lag(closes: pd.DataFrame, benchmark: str, leader: str, follower: str) -> float:
    """Correlation of leader's excess return this week with follower's next week."""
    ex = weekly_excess(closes, benchmark)
    if leader not in ex or follower not in ex:
        return np.nan
    pair = pd.concat([ex[leader], ex[follower].shift(-1)], axis=1).dropna()
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1])) if len(pair) >= MIN_WEEKS else np.nan


def pe_vs_history(pe: pd.DataFrame) -> pd.DataFrame:
    """Each index's latest P/E against its median over the window."""
    latest = pe.ffill().iloc[-1]
    median = pe.median()
    return pd.DataFrame({"pe": latest, "pe_median": median, "pe_premium": latest / median - 1})
