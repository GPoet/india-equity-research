"""NSE daily closing values for all ~170 indices (ind_close_all_DDMMYYYY.csv), including
each index's P/E, P/B and dividend yield. Official, free, one file per trading day."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from eqr.cache import Cache
from eqr.nse_client import NseClient, NseNotFound

log = logging.getLogger(__name__)

ARCHIVE = "https://nsearchives.nseindia.com/content/indices/"


@dataclass(frozen=True)
class IndexClose:
    name: str
    day: date
    close: float
    pe: float | None
    pb: float | None
    div_yield: float | None


def index_close_url(day: date) -> str:
    return f"{ARCHIVE}ind_close_all_{day:%d%m%Y}.csv"


def _num(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "", "-") else None  # type: ignore[arg-type]
    except ValueError:
        return None


def parse_index_closes(csv_text: str) -> list[IndexClose]:
    out = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        close = _num(row.get("Closing Index Value"))
        try:
            day = datetime.strptime((row.get("Index Date") or "").strip(), "%d-%m-%Y").date()
        except ValueError:
            continue
        if close is None:
            continue
        out.append(
            IndexClose(
                name=(row.get("Index Name") or "").strip(),
                day=day,
                close=close,
                pe=_num(row.get("P/E")),
                pb=_num(row.get("P/B")),
                div_yield=_num(row.get("Div Yield")),
            )
        )
    return out


class IndexHistory:
    def __init__(self, client: NseClient, cache: Cache) -> None:
        self._client = client
        self._cache = cache

    def day(self, d: date) -> list[IndexClose] | None:
        key = f"indices:{d.isoformat()}"
        text = self._cache.get(key)
        if text is None:
            if self._cache.get(f"indices-missing:{d.isoformat()}") is not None:
                return None
            try:
                text = self._client.get_bytes(index_close_url(d)).decode("utf-8", "replace")
            except NseNotFound:
                # Holiday or not yet published. Past days are final; today may still appear.
                if d < date.today():
                    self._cache.set(f"indices-missing:{d.isoformat()}", "1", ttl=None)
                return None
            if not text.startswith("Index Name"):
                log.warning("Unexpected index file for %s", d)
                return None
            self._cache.set(key, text, ttl=None)  # a published day never changes
        return parse_index_closes(text)

    def frame(self, end: date, days: int = 400) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(closes, pe): DataFrames indexed by date, one column per index."""
        rows: list[IndexClose] = []
        for offset in range(days):
            d = end - timedelta(days=offset)
            if d.weekday() >= 5:
                continue
            got = self.day(d)
            if got:
                rows.extend(got)
        if not rows:
            raise ValueError("No NSE index data available")
        df = pd.DataFrame([r.__dict__ for r in rows])
        df["day"] = pd.to_datetime(df["day"])
        closes = df.pivot_table(
            index="day", columns="name", values="close", aggfunc="last"
        ).sort_index()
        pe = df.pivot_table(index="day", columns="name", values="pe", aggfunc="last").sort_index()
        return closes, pe
