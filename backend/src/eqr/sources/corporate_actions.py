"""NSE corporate actions: splits and bonuses with their ex-dates. NSE's bhavcopy does not
adjust the previous close on an ex-date (Bajaj Finance 16 Jun 2025: 9,331 then 938), so any
return chained from daily files must divide out these factors."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from eqr.nse_client import NseClient

_BONUS = re.compile(r"\bBonus\s+(\d+)\s*:\s*(\d+)", re.I)
_SPLIT = re.compile(r"Split.*?From\s+R[se]\.?\s*([\d.]+)/?-?.*?To\s+R[se]\.?\s*([\d.]+)", re.I)


def parse_factor(subject: str) -> float | None:
    """Shares per old share created by the action (Bonus a:b -> (a+b)/b; split X to Y -> X/Y).
    None for anything that does not change the share count (dividends, rights, buybacks)."""
    if m := _BONUS.search(subject):
        new, held = float(m.group(1)), float(m.group(2))
        return (new + held) / held if held else None
    if m := _SPLIT.search(subject):
        old, new = float(m.group(1)), float(m.group(2))
        return old / new if new else None
    return None


def share_factors(rows: list[dict[str, Any]]) -> dict[tuple[str, date], float]:
    out: dict[tuple[str, date], float] = {}
    for r in rows:
        f = parse_factor(r.get("subject") or "")
        if f is None or f == 1:
            continue
        try:
            ex = datetime.strptime((r.get("exDate") or "").strip(), "%d-%b-%Y").date()
        except ValueError:
            continue
        key = ((r.get("symbol") or "").strip(), ex)
        out[key] = out.get(key, 1.0) * f  # split and bonus on the same day multiply
    return out


def fetch_share_factors(client: NseClient, start: date, end: date) -> dict[tuple[str, date], float]:
    rows = client.get_json(
        f"corporates-corporateActions?index=equities&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}",
        ttl=6 * 3600,
    )
    return share_factors(rows if isinstance(rows, list) else [])
