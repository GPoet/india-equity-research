"""NSE end-of-day "bhavcopy" (UDiFF format): official daily OHLCV for every stock."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta

from eqr.cache import Cache
from eqr.nse_client import NseClient, NseError, NseNotFound

log = logging.getLogger(__name__)

ARCHIVE = "https://nsearchives.nseindia.com/content/cm/"
EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    isin: str
    series: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    volume: int
    turnover: float

    @property
    def change_pct(self) -> float | None:
        return (self.close / self.prev_close - 1) * 100 if self.prev_close else None


def bhavcopy_url(day: date) -> str:
    return f"{ARCHIVE}BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def parse_bhavcopy(csv_text: str) -> dict[str, DailyBar]:
    bars: dict[str, DailyBar] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("FinInstrmTp") != "STK" or row.get("SctySrs") not in EQUITY_SERIES:
            continue
        try:
            bar = _bar(row)
        except (KeyError, ValueError) as exc:
            log.warning("Skipping bad bhavcopy row %s: %s", row.get("TckrSymb"), exc)
            continue
        # EQ series wins if a symbol trades in more than one series.
        if bar.symbol not in bars or bar.series == "EQ":
            bars[bar.symbol] = bar
    return bars


def _bar(row: dict[str, str]) -> DailyBar:
    return DailyBar(
        symbol=row["TckrSymb"],
        isin=row["ISIN"],
        series=row["SctySrs"],
        trade_date=date.fromisoformat(row["TradDt"]),
        open=float(row["OpnPric"]),
        high=float(row["HghPric"]),
        low=float(row["LwPric"]),
        close=float(row["ClsPric"]),
        prev_close=float(row["PrvsClsgPric"]),
        volume=int(float(row["TtlTradgVol"])),
        turnover=float(row["TtlTrfVal"]),
    )


class BhavcopySource:
    def __init__(self, client: NseClient, cache: Cache) -> None:
        self._client = client
        self._cache = cache

    def for_day(self, day: date) -> dict[str, DailyBar] | None:
        """Bars for a trading day, or None when no file exists (holiday/weekend/not yet out)."""
        key = f"bhav:{day.isoformat()}"
        text = self._cache.get(key)
        if text is None:
            try:
                raw = self._client.get_bytes(bhavcopy_url(day))
            except NseNotFound:
                return None  # no file for this day: holiday, weekend, or not published yet
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    text = zf.read(zf.namelist()[0]).decode("utf-8")
            except (zipfile.BadZipFile, IndexError, UnicodeDecodeError) as exc:
                raise NseError(f"Bhavcopy for {day} is not a valid zip (blocked?): {exc}") from exc
            self._cache.set(key, text, ttl=None)  # a published day never changes
        return parse_bhavcopy(text)

    def latest(self, today: date, lookback_days: int = 10) -> dict[str, DailyBar] | None:
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            bars = self.for_day(day)
            if bars:
                return bars
        return None
