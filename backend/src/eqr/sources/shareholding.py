"""Shareholding pattern from NSE (quarterly SHP XBRL): promoter stake, pledges, and who
else owns the company (foreign and domestic institutions, mutual funds, retail)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from eqr.nse_client import NseClient, looks_like_xbrl
from eqr.sources.filings import parse_nse_datetime

log = logging.getLogger(__name__)
LIST_TTL = 12 * 3600

_FACT = re.compile(r'<in-[a-z\-]+:([A-Za-z]+) contextRef="([^"]+)"[^>]*>([^<]*)<')
_INSTANT = re.compile(r"<xbrli:instant>(\d{4}-\d{2}-\d{2})</xbrli:instant>")

PROMOTER = "ShareholdingOfPromoterAndPromoterGroup_ContextI"
PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"


@dataclass(frozen=True)
class Shareholding:
    as_of: date
    promoter_pct: float | None
    pledged_of_promoter: float | None  # share of the promoters' own holding that is pledged
    encumbered_of_promoter: float | None  # pledge + non-disposal undertakings + other
    public_pct: float | None
    fpi_pct: float | None  # foreign institutions
    dii_pct: float | None  # domestic institutions (MFs, insurers, banks, pension funds)
    mf_pct: float | None
    insurance_pct: float | None
    retail_pct: float | None  # resident individuals
    government_pct: float | None


def _facts(xml: str) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for name, ctx, value in _FACT.findall(xml):
        try:
            out.setdefault((name, ctx), float(value))
        except ValueError:
            continue
    return out


def parse_shp(xml: str) -> Shareholding:
    if not looks_like_xbrl(xml):
        raise ValueError("Not a shareholding-pattern XBRL document")
    days = _INSTANT.findall(xml)
    if not days:
        raise ValueError("Shareholding pattern has no date")
    f = _facts(xml)

    def pct(ctx: str) -> float | None:
        return f.get((PCT, f"{ctx}_ContextI"))

    shares = f.get(("NumberOfShares", PROMOTER))
    pledged = f.get(("NumberOfSharesEncumberedUnderPledged", PROMOTER))
    retail_parts = [
        pct("ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh"),
        pct("ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh"),
    ]
    return Shareholding(
        as_of=date.fromisoformat(days[0]),
        promoter_pct=pct("ShareholdingOfPromoterAndPromoterGroup"),
        pledged_of_promoter=(pledged / shares) if pledged is not None and shares else None,
        encumbered_of_promoter=f.get(
            ("EncumberedSharesHeldAsPercentageOfTotalNumberOfShares", PROMOTER)
        ),
        public_pct=pct("PublicShareholding"),
        fpi_pct=pct("InstitutionsForeign"),
        dii_pct=pct("InstitutionsDomestic"),
        mf_pct=pct("MutualFundsOrUTI"),
        insurance_pct=pct("InsuranceCompanies"),
        retail_pct=None if any(p is None for p in retail_parts) else sum(retail_parts),  # type: ignore[arg-type]
        government_pct=pct("Governments"),
    )


def promoter_history(rows: list[dict[str, Any]]) -> list[tuple[date, float]]:
    """(quarter end, promoter %) from NSE's shareholding master list, newest first."""
    out = []
    for r in rows:
        try:
            out.append((parse_nse_datetime(r["date"]).date(), float(r["pr_and_prgrp"]) / 100))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(set(out), reverse=True)


@dataclass(frozen=True)
class Ownership:
    latest: Shareholding
    year_ago: Shareholding | None
    promoter_history: list[tuple[date, float]]


def fetch_ownership(client: NseClient, symbol: str) -> Ownership | None:
    rows = client.get_json(
        f"corporate-share-holdings-master?index=equities&symbol={symbol.replace('&', '%26')}",
        ttl=LIST_TTL,
    )
    if not isinstance(rows, list) or not rows:
        return None
    dated = []
    for r in rows:
        try:
            dated.append((parse_nse_datetime(r["date"]).date(), r))
        except (KeyError, ValueError, TypeError):
            continue
    dated = [(d, r) for d, r in sorted(dated, key=lambda x: x[0], reverse=True) if r.get("xbrl")]
    if not dated:
        return None

    def load(r: dict[str, Any]) -> Shareholding | None:
        try:
            return parse_shp(client.get_text(r["xbrl"], ttl=None, validate=looks_like_xbrl))
        except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
            log.warning("Shareholding file %s unreadable: %s", r.get("xbrl"), exc)
            return None

    latest = load(dated[0][1])
    if latest is None:
        return None
    target = date(latest.as_of.year - 1, latest.as_of.month, latest.as_of.day)
    prior = next((r for d, r in dated if d == target), None)
    return Ownership(latest, load(prior) if prior else None, promoter_history(rows))
