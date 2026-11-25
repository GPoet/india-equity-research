"""NSE corporate announcements: the company's own filings of events (orders, acquisitions,
results, board outcomes, analyst meets). Primary-source input for the research agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from eqr.nse_client import NseClient
from eqr.sources.filings import parse_nse_datetime

log = logging.getLogger(__name__)

LIST_TTL = 3 * 3600

# Categories that never carry investment information.
NOISE = frozenset(
    {
        "Copy of Newspaper Publication",
        "Loss of Share Certificates",
        "Loss of share certificate",
        "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
        "Trading Window",
        "Closure of Trading Window",
        "Duplicate Share Certificate",
    }
)


@dataclass(frozen=True)
class Announcement:
    symbol: str
    when: datetime
    category: str
    text: str
    url: str | None
    industry: str | None


def window_path(symbol: str, start: date, end: date) -> str:
    return (
        f"corporate-announcements?index=equities&symbol={symbol.replace('&', '%26')}"
        f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"
    )


def parse_announcements(rows: list[dict[str, Any]]) -> list[Announcement]:
    out: list[Announcement] = []
    for row in rows:
        try:
            category = (row.get("desc") or "").strip()
            if category in NOISE:
                continue
            text = (row.get("attchmntText") or row.get("voiceSummary") or "").strip()
            url = row.get("attchmntFile")
            out.append(
                Announcement(
                    symbol=row["symbol"],
                    when=parse_nse_datetime(row["an_dt"]),
                    category=category,
                    text=text,
                    url=url if isinstance(url, str) and url.startswith("https://") else None,
                    industry=row.get("smIndustry"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("Skipping malformed announcement: %s", exc)
    return sorted(out, key=lambda a: a.when, reverse=True)


def fetch_market_announcements(client: NseClient, day: date) -> list[Announcement]:
    """Every company's announcements on one day, main board and SME."""
    out: list[Announcement] = []
    for index in ("equities", "sme"):
        rows = client.get_json(
            f"corporate-announcements?index={index}&from_date={day:%d-%m-%Y}&to_date={day:%d-%m-%Y}",
            ttl=LIST_TTL if day >= date.today() else 7 * 24 * 3600,
        )
        if isinstance(rows, list):
            out.extend(parse_announcements(rows))
    return out


def fetch_announcements(
    client: NseClient, symbol: str, start: date, end: date
) -> list[Announcement]:
    rows = client.get_json(window_path(symbol, start, end), ttl=LIST_TTL)
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected announcements payload for {symbol}")
    return parse_announcements(rows)
