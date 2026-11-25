"""Sector strength, valuation and co-movement from daily index closes.

Strength = performance relative to the Nifty 50 over 3 and 6 months plus the trend, always
measured on dates where both the index and the benchmark have values. Co-movement uses
weekly returns with each sector's own market exposure (beta) removed; otherwise two
defensive, low-beta sectors look related just because both lag the market.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
TREND_DAYS = 200
MIN_TREND_DAYS = 60  # indices NSE launched recently get a trend over what exists
MIN_WEEKS = 20
MIN_PE_DAYS = 200  # under this the P/E "median" is not a year of history


def _ret(series: pd.Series, n: int) -> float:
    if len(series) <= n:
        return np.nan
    return float(series.iloc[-1] / series.iloc[-1 - n] - 1)


def sector_scores(closes: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """One row per index: returns, relative strength, trend, distance from high, stance."""
    last_day = closes.index[-1]
    rows = {}
    for name in closes.columns:
        # Only dates where both have a close, so the windows cover the same days.
        pair = closes[[name, benchmark]].dropna() if name != benchmark else closes[[name]].dropna()
        s = pair[name]
        b = pair[benchmark] if name != benchmark else s
        row: dict[str, object] = {f"ret_{k}": _ret(s, n) for k, n in DAYS.items()}
        row["rs_3m"] = _ret(s, DAYS["3m"]) - _ret(b, DAYS["3m"])
        row["rs_6m"] = _ret(s, DAYS["6m"]) - _ret(b, DAYS["6m"])
        trend_window = min(TREND_DAYS, len(s))
        row["vs_200dma"] = (
            float(s.iloc[-1] / s.iloc[-trend_window:].mean() - 1)
            if trend_window >= MIN_TREND_DAYS
            else np.nan
        )
        row["history_days"] = len(s)
        window = s.iloc[-DAYS["12m"] :]
        row["from_52w_high"] = float(s.iloc[-1] / window.max() - 1) if len(window) else np.nan
        row["stale"] = len(s) == 0 or s.index[-1] != last_day
        rows[name] = row
    df = pd.DataFrame.from_dict(rows, orient="index")

    def stance(r: pd.Series) -> str:
        if r["stale"]:
            return "stale data"
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


def weekly_returns(closes: pd.DataFrame) -> pd.DataFrame:
    weekly = closes.resample("W-FRI").last()
    if closes.index[-1] < weekly.index[-1]:
        weekly = weekly.iloc[:-1]  # the last week is not over yet
    return weekly.pct_change(fill_method=None).iloc[1:]


def market_residuals(closes: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """Weekly returns minus beta x market, with beta fitted per index on its own history."""
    weekly = weekly_returns(closes)
    m = weekly[benchmark]
    out = {}
    for name in weekly.columns.drop(benchmark):
        pair = pd.concat([weekly[name], m], axis=1).dropna()
        if len(pair) < MIN_WEEKS:
            continue
        beta = pair.iloc[:, 0].cov(pair.iloc[:, 1]) / pair.iloc[:, 1].var()
        out[name] = weekly[name] - beta * m
    return pd.DataFrame(out, index=weekly.index)


def excess_correlations(closes: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """Correlation of weekly returns after removing each index's market exposure."""
    return market_residuals(closes, benchmark).corr(min_periods=MIN_WEEKS)


def pe_vs_history(pe: pd.DataFrame) -> pd.DataFrame:
    """Each index's latest P/E against its median over the window. P/E of 0 or below is
    treated as missing; the premium needs ~a year of history and a P/E on the last day."""
    clean = pe.where(pe > 0)
    latest = clean.iloc[-1]
    median = clean.median()
    days = clean.notna().sum()
    premium = latest / median - 1
    premium = premium.where((days >= MIN_PE_DAYS) & (median > 0) & latest.notna())
    return pd.DataFrame({"pe": latest, "pe_median": median, "pe_premium": premium, "pe_days": days})
