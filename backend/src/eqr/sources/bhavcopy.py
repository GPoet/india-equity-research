"""NSE end-of-day "bhavcopy": official daily OHLCV for every stock, as traded (not adjusted
for later splits or bonuses). UDiFF format from July 2024, the legacy cm...bhav.csv before."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta

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


LEGACY_ARCHIVE = "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
UDIFF_FROM = date(2024, 7, 8)


def bhavcopy_url(day: date) -> str:
    return f"{ARCHIVE}BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def legacy_bhavcopy_url(day: date) -> str:
    mon = day.strftime("%b").upper()
    return f"{LEGACY_ARCHIVE}{day.year}/{mon}/cm{day:%d}{mon}{day.year}bhav.csv.zip"


def bhavcopy_urls(day: date) -> list[str]:
    """Most likely format for the date first, the other as a fallback."""
    new, old = bhavcopy_url(day), legacy_bhavcopy_url(day)
    return [new, old] if day >= UDIFF_FROM else [old, new]


def _legacy_bar(row: dict[str, str]) -> DailyBar:
    return DailyBar(
        symbol=row["SYMBOL"].strip(),
        isin=row["ISIN"].strip(),
        series=row["SERIES"].strip(),
        trade_date=datetime.strptime(row["TIMESTAMP"].strip(), "%d-%b-%Y").date(),
        open=float(row["OPEN"]),
        high=float(row["HIGH"]),
        low=float(row["LOW"]),
        close=float(row["CLOSE"]),
        prev_close=float(row["PREVCLOSE"]),
        volume=int(float(row["TOTTRDQTY"])),
        turnover=float(row["TOTTRDVAL"]),
    )


def _parse_legacy(csv_text: str) -> dict[str, DailyBar]:
    bars: dict[str, DailyBar] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if (row.get("SERIES") or "").strip() not in EQUITY_SERIES:
            continue
        try:
            bar = _legacy_bar(row)
        except (KeyError, ValueError) as exc:
            log.warning("Skipping bad legacy bhavcopy row %s: %s", row.get("SYMBOL"), exc)
            continue
        if bar.symbol not in bars or bar.series == "EQ":
            bars[bar.symbol] = bar
    return bars


def parse_bhavcopy(csv_text: str) -> dict[str, DailyBar]:
    if csv_text.lstrip().startswith("SYMBOL,"):
        return _parse_legacy(csv_text)
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
            raw = None
            for url in bhavcopy_urls(day):
                try:
                    raw = self._client.get_bytes(url)
                    break
                except NseNotFound:
                    continue
            if raw is None:
                return None  # no file for this day: holiday, weekend, or not published yet
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    text = zf.read(zf.namelist()[0]).decode("utf-8")
            except (zipfile.BadZipFile, IndexError, UnicodeDecodeError) as exc:
                raise NseError(f"Bhavcopy for {day} is not a valid zip (blocked?): {exc}") from exc
            self._cache.set(key, text, ttl=None)  # a published day never changes
        return parse_bhavcopy(text)

    def on_or_before(self, day: date, lookback_days: int = 7) -> dict[str, DailyBar]:
        """All bars of the last trading day on or before `day` ({} if none found)."""
        for offset in range(lookback_days):
            d = day - timedelta(days=offset)
            if d.weekday() >= 5:
                continue
            bars = self.for_day(d)
            if bars:
                return bars
        return {}

    def latest(self, today: date, lookback_days: int = 10) -> dict[str, DailyBar] | None:
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            bars = self.for_day(day)
            if bars:
                return bars
        return None
