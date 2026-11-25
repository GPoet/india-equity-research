"""Parse NSE/BSE results XBRL (in-bse-fin legacy and in-capmkt integrated filing).

Rules:
- Only non-dimensional facts count; segment rows carry dimensions and would double count.
- Missing is None, never 0. Totals built from parts are None unless every part is present.
- A "quarter" must be 80-100 days long; the balance sheet must be dated at the quarter end.
"""

from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

from eqr.xbrl_concepts import (
    BALANCE,
    BANK_BALANCE,
    BANK_BLANK_RATIOS,
    BANK_INCOME,
    FINANCIAL_MARKERS,
    INCOME,
    QUARTER_DAYS,
)

XBRLI = "{http://www.xbrl.org/2003/instance}"
log = logging.getLogger(__name__)
Metrics = dict[str, float | None]


@dataclass(frozen=True)
class Period:
    start: date | None  # None for an instant (balance sheet date)
    end: date
    values: Mapping[str, float] = field(default_factory=dict)

    @property
    def days(self) -> int:
        return 0 if self.start is None else (self.end - self.start).days + 1

    def get(self, concept: str) -> float | None:
        return self.values.get(concept)

    def pick(self, table: Mapping[str, tuple[str, ...]]) -> Metrics:
        return {key: _first(self.values, names) for key, names in table.items()}


@dataclass(frozen=True)
class Filing:
    latest_period: Period  # shortest duration ending on the latest date, whatever its length
    quarter: Period | None  # latest_period if it is 80-100 days, else None
    year_to_date: Period | None
    balance_sheet: Period | None  # dated at the quarter end and carrying Assets, else None
    previous_balance_sheet: Period | None
    periods: tuple[Period, ...]

    def _has_anywhere(self, concept: str) -> bool:
        return any(concept in p.values for p in self.periods)

    @property
    def is_bank(self) -> bool:
        return (
            self._has_anywhere("InterestEarned")
            and self._has_anywhere("InterestExpended")
            and not self._has_anywhere("RevenueFromOperations")
        )

    @property
    def is_financial(self) -> bool:
        return self.is_bank or any(self._has_anywhere(c) for c in FINANCIAL_MARKERS)

    def _income(self, period: Period | None) -> Metrics:
        if period is None:
            return {}
        if self.is_bank:
            return _bank_income(period)
        out = period.pick(INCOME)
        out["ebitda"] = None if self.is_financial else _ebitda(out)
        return out

    def quarter_metrics(self) -> Metrics:
        return self._income(self.quarter)

    def year_to_date_metrics(self) -> Metrics:
        return self._income(self.year_to_date)

    def balance_metrics(self) -> Metrics:
        return self.balance_metrics_for(self.balance_sheet)

    def balance_metrics_for(self, period: Period | None) -> Metrics:
        if period is None:
            return {}
        return _bank_balance(period) if self.is_bank else _balance(period)


def _first(values: Mapping[str, float], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in values:
            return values[name]
    return None


def _sum_all(*values: float | None) -> float | None:
    """Sum only when every part is known; a partial sum is not a total."""
    return None if any(v is None for v in values) else sum(values)  # type: ignore[arg-type]


def _ebitda(m: Metrics) -> float | None:
    """Operating EBITDA = PBT before exceptional items + finance costs + D&A - other income."""
    return (
        None
        if any(
            m.get(k) is None
            for k in (
                "pbt_before_exceptional",
                "finance_costs",
                "depreciation",
                "other_income",
            )
        )
        else m["pbt_before_exceptional"]
        + m["finance_costs"]
        + m["depreciation"]
        - m["other_income"]  # type: ignore[operator]
    )


def _bank_income(period: Period) -> Metrics:
    out = period.pick(BANK_INCOME)
    all_blank = out["gnpa_pct"] == 0 and out["nnpa_pct"] == 0
    blanks = (
        set(BANK_BLANK_RATIOS) if all_blank else ({"cet1_pct"} if out["cet1_pct"] == 0 else set())
    )
    out = {k: (None if k in blanks else v) for k, v in out.items()}
    earned, expended = out["interest_earned"], out["interest_expended"]
    out["nii"] = None if earned is None or expended is None else earned - expended
    return out


def _bank_balance(period: Period) -> Metrics:
    out = period.pick(BANK_BALANCE)
    out["equity_owners"] = _sum_all(out["capital"], out["reserves"])
    out["total_debt"] = out["borrowings"]
    out["cash"] = _sum_all(out["cash_rbi"], out["cash_banks"])
    return out


def _balance(period: Period) -> Metrics:
    out = period.pick(BALANCE)
    if out["borrowings"] is not None or out["debt_securities"] is not None:
        # Division III: borrowings and debt securities are both required lines;
        # subordinated liabilities are optional and often absent.
        out["total_debt"] = _sum_all(out["borrowings"], out["debt_securities"])
        if out["total_debt"] is not None and out["subordinated_liabilities"] is not None:
            out["total_debt"] += out["subordinated_liabilities"]
    else:
        out["total_debt"] = _sum_all(out["borrowings_current"], out["borrowings_noncurrent"])
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(text: str | None) -> date | None:
    return date.fromisoformat(text.strip()[:10]) if text and text.strip() else None


def _contexts(root: ET.Element) -> dict[str, tuple[date | None, date]]:
    """Map plain (non-dimensional) context ids to (start, end)."""
    out: dict[str, tuple[date | None, date]] = {}
    for ctx in root.iter(f"{XBRLI}context"):
        if (
            ctx.find(f".//{XBRLI}segment") is not None
            or ctx.find(f".//{XBRLI}scenario") is not None
        ):
            continue
        period = ctx.find(f"{XBRLI}period")
        if period is None:
            continue
        instant = _parse_date(period.findtext(f"{XBRLI}instant"))
        if instant:
            out[ctx.get("id", "")] = (None, instant)
            continue
        start = _parse_date(period.findtext(f"{XBRLI}startDate"))
        end = _parse_date(period.findtext(f"{XBRLI}endDate"))
        if start and end:
            out[ctx.get("id", "")] = (start, end)
    return out


def _undeclared_contexts(
    root: ET.Element, declared: dict[str, tuple[date | None, date]]
) -> dict[str, tuple[date | None, date]]:
    """Periods for contexts that facts use but the file never declares.

    Legacy NSE files from 2018-2023 reference OneD/OneI etc. without declaring
    them. Duration contexts carry DateOfStart/EndOfReportingPeriod facts; an
    instant context "XI" takes the end date of its duration sibling "XD".
    """
    used = {el.get("contextRef") for el in root if el.get("contextRef")}
    # Every declared id, dimensional ones included: those are segment rows we skip on
    # purpose and must never be "inferred" back in as plain periods.
    all_declared = {ctx.get("id", "") for ctx in root.iter(f"{XBRLI}context")}
    dates: dict[str, dict[str, date]] = {}
    for el in root:
        name, ref = _local(el.tag), el.get("contextRef")
        if ref and name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"):
            try:
                parsed = _parse_date(el.text)
            except ValueError:
                parsed = None
            if parsed:
                dates.setdefault(ref, {})[name] = parsed
    fy_start = next(
        (_parse_date(el.text) for el in root if _local(el.tag) == "DateOfStartOfFinancialYear"),
        None,
    )
    siblings = _dimensional_periods(root)
    out: dict[str, tuple[date | None, date]] = {}
    # "One" (current quarter) first, so it wins any clash; instants after durations.
    order = sorted(used - all_declared, key=lambda r: (r.endswith("I"), not r.startswith("One")))
    for ref in order:
        found = dates.get(ref, {})
        start, end = (
            found.get("DateOfStartOfReportingPeriod"),
            found.get("DateOfEndOfReportingPeriod"),
        )
        if start and end:
            out[ref] = (start, end)
        elif (
            ref == "FourD"
            and fy_start
            and (end or dates.get("OneD", {}).get("DateOfEndOfReportingPeriod"))
        ):
            # NSE naming: FourD is year-to-date, from the start of the financial year.
            out[ref] = (fy_start, end or dates["OneD"]["DateOfEndOfReportingPeriod"])
        elif ref.endswith("D") and (period := _agreed_sibling_period(ref, siblings, end)):
            out[ref] = period
        elif ref.endswith("I"):
            duration = out.get(ref[:-1] + "D")
            sibling_end = duration[1] if duration else None
            sibling_end = sibling_end or dates.get(ref[:-1] + "D", {}).get(
                "DateOfEndOfReportingPeriod"
            )
            if sibling_end:
                out[ref] = (None, sibling_end)
    return _drop_clashes(out, declared)


def _drop_clashes(
    inferred: dict[str, tuple[date | None, date]], declared: dict[str, tuple[date | None, date]]
) -> dict[str, tuple[date | None, date]]:
    """An inferred period may not coincide with another context's period: merging two
    contexts into one bucket would let year-to-date values overwrite quarterly ones."""
    taken = set(declared.values())
    kept: dict[str, tuple[date | None, date]] = {}
    for ref, period in inferred.items():  # insertion order = priority order
        if period in taken:
            log.warning("Dropping XBRL context %s: period %s already used", ref, period)
            continue
        taken.add(period)
        kept[ref] = period
    return kept


def _dimensional_periods(root: ET.Element) -> dict[str, tuple[date, date]]:
    """Duration periods of declared dimensional contexts (segment rows etc.)."""
    out: dict[str, tuple[date, date]] = {}
    for ctx in root.iter(f"{XBRLI}context"):
        period = ctx.find(f"{XBRLI}period")
        if period is None:
            continue
        start = _parse_date(period.findtext(f"{XBRLI}startDate"))
        end = _parse_date(period.findtext(f"{XBRLI}endDate"))
        if start and end:
            out[ctx.get("id", "")] = (start, end)
    return out


def _agreed_sibling_period(
    ref: str, siblings: dict[str, tuple[date, date]], expected_end: date | None
) -> tuple[date, date] | None:
    """Period shared by every declared context with the same prefix ("One", "Four").

    Used only when all such siblings agree, and when the end matches the filing's
    own DateOfEndOfReportingPeriod if it states one.
    """
    m = re.match(r"^[A-Z][a-z]+", ref)
    if not m:
        return None
    prefix = m.group(0)
    found = {p for cid, p in siblings.items() if cid.startswith(prefix) and cid.endswith("D")}
    if len(found) != 1:
        return None
    period = found.pop()
    if expected_end is not None and period[1] != expected_end:
        return None
    return period


def _to_number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        value = float(text.strip().replace(",", ""))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _collect(root: ET.Element, contexts: dict[str, tuple[date | None, date]]) -> tuple[Period, ...]:
    buckets: dict[tuple[date | None, date], dict[str, float]] = {}
    for el in root:
        ref = el.get("contextRef")
        if ref not in contexts:
            continue
        number = _to_number(el.text)
        if number is not None:
            buckets.setdefault(contexts[ref], {}).setdefault(_local(el.tag), number)
    return tuple(
        Period(start=s, end=e, values=MappingProxyType(v)) for (s, e), v in buckets.items()
    )


def parse_filing(xml_text: str | bytes) -> Filing:
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Not a valid XBRL document: {exc}") from exc
    if _local(root.tag) != "xbrl":
        raise ValueError(f"Not an XBRL document (root element is {_local(root.tag)!r})")

    declared = _contexts(root)
    contexts = {**declared, **_undeclared_contexts(root, declared)}
    if not contexts:
        raise ValueError("XBRL document has no usable contexts")
    periods = _collect(root, contexts)

    durations = [p for p in periods if p.start is not None]
    if not durations:
        raise ValueError("XBRL document has no reporting period")
    latest_end = max(p.end for p in durations)
    current = [p for p in durations if p.end == latest_end]
    latest = min(current, key=lambda p: p.days)
    quarter = latest if latest.days in QUARTER_DAYS else None
    longer = [p for p in current if p.days > latest.days]
    year_to_date = max(longer, key=lambda p: p.days) if longer else None

    sheets = sorted(
        (p for p in periods if p.start is None and "Assets" in p.values),
        key=lambda p: p.end,
        reverse=True,
    )
    balance_sheet = next((p for p in sheets if p.end == latest_end), None)
    previous = next((p for p in sheets if p.end < latest_end), None)

    return Filing(
        latest_period=latest,
        quarter=quarter,
        year_to_date=year_to_date,
        balance_sheet=balance_sheet,
        previous_balance_sheet=previous,
        periods=periods,
    )
