"""Intraday quote and price history via yfinance (Yahoo, about 15 minutes delayed)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import yfinance as yf


class PriceError(RuntimeError):
    """No usable price data came back."""


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    prev_close: float | None
    as_of: datetime  # time of the last traded bar, exchange timezone
    source: str = "yfinance (delayed)"


def yahoo_symbol(nse_symbol: str) -> str:
    return f"{nse_symbol}.NS"


def quote(nse_symbol: str) -> Quote:
    ticker = yf.Ticker(yahoo_symbol(nse_symbol))
    daily = ticker.history(period="5d", interval="1d", auto_adjust=False).dropna(subset=["Close"])
    if daily.empty:
        raise PriceError(f"No Yahoo price data for {nse_symbol}")
    minute = ticker.history(period="1d", interval="1m", auto_adjust=False).dropna(subset=["Close"])
    if not minute.empty and minute.index[-1].date() == daily.index[-1].date():
        price, as_of = float(minute.iloc[-1]["Close"]), minute.index[-1].to_pydatetime()
    else:
        price, as_of = float(daily.iloc[-1]["Close"]), daily.index[-1].to_pydatetime()
    prev = float(daily.iloc[-2]["Close"]) if len(daily) > 1 else None
    return Quote(symbol=nse_symbol, price=price, prev_close=prev, as_of=as_of)


def history(nse_symbol: str, period: str = "10y", interval: str = "1d") -> pd.DataFrame:
    """OHLCV history. Close is split/bonus-adjusted only (what traded, comparable across
    splits); Adj Close also folds in dividends, for total-return use. NaN rows dropped."""
    hist = yf.Ticker(yahoo_symbol(nse_symbol)).history(
        period=period, interval=interval, auto_adjust=False
    )
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise PriceError(f"No Yahoo history for {nse_symbol}")
    return hist[["Open", "High", "Low", "Close", "Adj Close", "Volume"]].copy()
