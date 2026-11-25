"""Quarterly results filings from NSE.

Two feeds, because SEBI moved results into "Integrated Filing" in 2025:
- legacy:     /api/corporates-financial-results (history 2018 to Dec 2024)
- integrated: /api/integrated-filing-results    (2025 onward)
Both link to XBRL files with the same concept names, parsed by eqr.xbrl.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from eqr.nse_client import looks_like_xbrl
from eqr.xbrl import Filing, parse_filing

log = logging.getLogger(__name__)

LIST_TTL = 6 * 3600  # new filings appear a few times a year; 6h is plenty
_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ),
        start=1,
    )
}
_DATE_RE = re.compile(r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


class _Client(Protocol):
    def get_json(self, path: str, ttl: float | None) -> Any: ...
    def get_text(
        self, url: str, ttl: float | None, validate: Callable[[str], bool] | None = None
    ) -> str: ...


@dataclass(frozen=True)
class FilingRef:
    symbol: str
    period_end: date
    consolidated: bool
    xbrl_url: str
    filed_at: str
    source: str  # "integrated" | "legacy"


def parse_nse_datetime(text: str) -> datetime:
    """'08-Oct-2026 22:07:33' / '09-Jan-2025 21:39' / '30-SEP-2026', locale-independent."""
    m = _DATE_RE.match(text or "")
    if not m or m.group(2).upper() not in _MONTHS:
        raise ValueError(f"Unrecognised NSE date: {text!r}")
    day, mon, year, hh, mm, ss = m.groups()
    return datetime(
        int(year),
        _MONTHS[mon.upper()],
        int(day),
        int(hh or 0),
        int(mm or 0),
        int(ss or 0),
    )


def _filed_key(ref: FilingRef) -> datetime:
    try:
        return parse_nse_datetime(ref.filed_at)
    except ValueError:
        return datetime.min


def _consolidated(value: Any) -> bool | None:
    text = (value or "").strip().lower()
    if text == "consolidated":
        return True
    if text in ("standalone", "non-consolidated"):
        return False
    return None  # unknown: skip rather than assume standalone


def _build(
    rows: Iterable[dict[str, Any]], source: str, get: Callable[[dict[str, Any]], tuple]
) -> list[FilingRef]:
    refs: list[FilingRef] = []
    for row in rows:
        try:
            symbol, period, cons, url, filed = get(row)
            consolidated = _consolidated(cons)
            if not url or consolidated is None:
                continue
            refs.append(
                FilingRef(
                    symbol,
                    parse_nse_datetime(period).date(),
                    consolidated,
                    url,
                    filed or "",
                    source,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("Skipping malformed %s filing row: %s", source, exc)
    return sorted(refs, key=lambda r: r.period_end, reverse=True)


def parse_integrated(payload: dict[str, Any]) -> list[FilingRef]:
    rows = [r for r in payload.get("data", []) if r.get("type") == "Integrated Filing- Financials"]
    return _build(
        rows,
        "integrated",
        lambda r: (
            r["symbol"],
            r["qe_Date"],
            r.get("consolidated"),
            r.get("xbrl"),
            r.get("broadcast_Date"),
        ),
    )


def parse_legacy(payload: list[dict[str, Any]]) -> list[FilingRef]:
    rows = [r for r in payload if str(r.get("xbrl") or "").endswith(".xml")]
    return _build(
        rows,
        "legacy",
        lambda r: (
            r["symbol"],
            r["toDate"],
            r.get("consolidated"),
            r.get("xbrl"),
            r.get("filingDate"),
        ),
    )


def merge_refs(legacy: Iterable[FilingRef], integrated: Iterable[FilingRef]) -> list[FilingRef]:
    """One ref per (period, consolidated): integrated beats legacy, then the latest filing wins."""
    by_key: dict[tuple[date, bool], FilingRef] = {}
    for ref in [*legacy, *integrated]:
        key = (ref.period_end, ref.consolidated)
        current = by_key.get(key)
        rank = (ref.source == "integrated", _filed_key(ref))
        if current is None or rank > (
            current.source == "integrated",
            _filed_key(current),
        ):
            by_key[key] = ref
    return sorted(by_key.values(), key=lambda r: (r.period_end, r.consolidated), reverse=True)


class FilingsSource:
    def __init__(self, client: _Client) -> None:
        self._client = client

    def list(self, symbol: str) -> list[FilingRef]:
        sym = symbol.replace("&", "%26")
        integrated = self._client.get_json(
            f"integrated-filing-results?index=equities&symbol={sym}"
            "&type=Integrated%20Filing-%20Financials",
            ttl=LIST_TTL,
        )
        legacy = self._client.get_json(
            f"corporates-financial-results?index=equities&symbol={sym}&period=Quarterly",
            ttl=LIST_TTL,
        )
        if not isinstance(integrated, dict) or not isinstance(legacy, list):
            raise ValueError(f"Unexpected filings payload shape for {symbol}")
        return merge_refs(parse_legacy(legacy), parse_integrated(integrated))

    def fetch(self, ref: FilingRef) -> Filing:
        # Filed documents are immutable (revisions get a new URL), so cache forever;
        # the validator keeps HTML error pages out of the cache.
        filing = parse_filing(
            self._client.get_text(ref.xbrl_url, ttl=None, validate=looks_like_xbrl)
        )
        if filing.latest_period.end != ref.period_end:
            raise ValueError(
                f"{ref.symbol}: filing at {ref.xbrl_url} covers {filing.latest_period.end}, "
                f"listing says {ref.period_end}"
            )
        return filing
