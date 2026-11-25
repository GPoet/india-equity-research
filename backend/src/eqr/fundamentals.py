"""Assemble a company's financial history from its quarterly results filings.

Produces fiscal-year rows (April-March), trailing-twelve-month figures and the
latest balance sheet. Every derived total is None when any input is missing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date

from eqr.sources.filings import FilingRef, FilingsSource
from eqr.xbrl import Filing, Metrics

log = logging.getLogger(__name__)

# Point-in-time or ratio fields: never summed across quarters.
NON_ADDITIVE = frozenset(
    {
        "paid_up_capital",
        "face_value",
        "gnpa_pct",
        "nnpa_pct",
        "cet1_pct",
        "roa_pct",
        "gross_npa",
        "net_npa",
    }
)
# Reported only in half-year and annual statements, never per quarter.
CASH_KEYS = frozenset(
    {
        "cfo",
        "cfi",
        "cff",
        "capex_ppe",
        "capex_intangibles",
        "dividends_paid",
        "interest_paid_operating",
    }
)


@dataclass(frozen=True)
class QuarterRow:
    period_end: date
    income: Metrics


@dataclass(frozen=True)
class YearRow:
    fy_end: date
    income: Metrics
    income_source: str  # "annual" | "sum_of_quarters"
    balance: Metrics  # at fy_end; {} when not filed
    shares: float | None = None  # share count for the year (see year_shares)
    shares_exact: bool = False  # paid-up capital / face value, confirmed by profit / EPS


@dataclass(frozen=True)
class Fundamentals:
    symbol: str
    consolidated: bool
    is_bank: bool
    is_financial: bool
    quarters: tuple[QuarterRow, ...]  # newest first
    years: tuple[YearRow, ...]  # newest first
    ttm: Metrics
    ttm_end: date | None
    ttm_cash_basis: str
    latest_balance: Metrics
    latest_balance_date: date | None
    shares: float | None
    face_value: float | None
    shares_note: str = ""
    # Banks: GNPA/NNPA/CET1 ratios from the latest standalone filing (consolidated filings
    # leave them blank). Empty for non-banks or when unavailable.
    asset_quality: Metrics = field(default_factory=dict)
    asset_quality_period: date | None = None

    def year(self, fy_end: date) -> YearRow | None:
        return next((y for y in self.years if y.fy_end == fy_end), None)


SHARE_TOLERANCE = 0.05


def owners_profit(m: Metrics) -> float | None:
    """Profit attributable to owners; falls back to total profit. Some older filings tag the
    owners' line as 0 while total profit is non-zero (BAJFINANCE FY20-21): that 0 is a blank."""
    pat, owners = m.get("pat"), m.get("pat_owners")
    if owners is None or (owners == 0 and pat):
        return pat
    return owners


def shares_from(m: Metrics) -> tuple[float | None, str]:
    """Share count from a period's metrics, cross-checking two independent routes.

    Paid-up capital / face value is exact when tagged right, but some filings swap or
    mis-scale those fields (BAJAJHLDNG). Profit / EPS is close (weighted-average shares)
    and hard to get wrong. Disagreement beyond 5% means the capital fields are bad.
    """
    paid_up, face = m.get("paid_up_capital"), m.get("face_value")
    pat = owners_profit(m)
    eps = m.get("eps_basic")
    by_capital = paid_up / face if paid_up and face else None
    by_eps = pat / eps if pat and eps and pat / eps > 0 else None
    if by_capital and by_eps:
        if abs(by_capital / by_eps - 1) <= SHARE_TOLERANCE:
            return by_capital, "paid-up capital / face value (matches profit / EPS)"
        return by_eps, (
            f"profit / EPS ({by_eps:,.0f}); paid-up capital / face value gave "
            f"{by_capital:,.0f}, a mis-tagged filing"
        )
    if by_capital:
        return by_capital, "paid-up capital / face value (EPS unavailable to cross-check)"
    if by_eps:
        return by_eps, "profit / EPS (capital fields missing)"
    return None, "share count unavailable"


# Bonus a:b (a new shares for every b held) multiplies shares by (a + b) / b. Limited to the
# forms Indian companies use (a, b up to 5, plus 1:10) so noise cannot match a rare ratio.
BONUS_RATIOS = tuple(sorted({(a + b) / b for a in range(1, 6) for b in range(1, 6)} | {1.1}))
SPLIT_RATIOS = (2.0, 2.5, 4.0, 5.0, 10.0, 20.0, 50.0, 100.0)  # face value 10 -> 1 = 10x
ACTION_TOLERANCE = 0.015  # employee stock options add ~1% a year on top of a bonus
# Equity may grow by at most the year's profit plus this share of opening equity for a
# share jump to count as a bonus: anything more means money came in (rights, QIP, merger).
BONUS_EQUITY_SLACK = 0.10


def _match(ratio: float, candidates: tuple[float, ...]) -> float | None:
    for c in candidates:
        for candidate in (c, 1 / c):  # reverse splits / consolidations too
            if abs(ratio / candidate - 1) <= ACTION_TOLERANCE:
                return candidate
    return None


def year_shares(y: YearRow) -> float | None:
    return y.shares if y.shares is not None else shares_from(y.income)[0]


def _bonus_confirmed(newer: YearRow, older: YearRow) -> bool:
    eq_new, eq_old = newer.balance.get("equity_owners"), older.balance.get("equity_owners")
    pat = owners_profit(newer.income)
    if eq_new is None or eq_old is None or pat is None or eq_old <= 0:
        return False
    return eq_new - eq_old <= max(pat, 0.0) + BONUS_EQUITY_SLACK * eq_old


def share_action_factors(years: tuple[YearRow, ...]) -> tuple[dict[date, float], list[str]]:
    """For each fiscal year, the bonus/split multiple applied to shares since then.

    Splits are read from face-value changes, which are exact. A remaining round jump
    (a:b bonus) counts only when the balance sheets show no money came in; otherwise
    it is treated as real issuance (dilution) and noted. Yahoo's split list is not used:
    it misses Indian bonus issues (Bajaj Finance 2025).
    """
    factors: dict[date, float] = {}
    notes: list[str] = []
    cumulative = 1.0
    newer: YearRow | None = None
    newer_shares: float | None = None
    for y in years:  # newest first
        shares = year_shares(y)
        exact = y.shares_exact and newer is not None and newer.shares_exact
        if newer is not None and newer_shares and shares and exact:
            ratio = newer_shares / shares
            split = 1.0
            fv_old, fv_new = y.income.get("face_value"), newer.income.get("face_value")
            if fv_old and fv_new and (found := _match(fv_old / fv_new, SPLIT_RATIOS)):
                split = found
            bonus = _match(ratio / split, BONUS_RATIOS)
            if bonus and bonus != 1.0:
                if _bonus_confirmed(newer, y):
                    split *= bonus
                else:
                    notes.append(
                        f"Shares rose {ratio / split:.2f}x in FY{newer.fy_end.year % 100}; could not "
                        "confirm a bonus from the balance sheet, so treated as dilution"
                    )
            cumulative *= split
        factors[y.fy_end] = cumulative
        if shares:
            newer, newer_shares = y, shares
    return factors, notes


def _fy_end(day: date) -> date:
    return date(day.year if day.month <= 3 else day.year + 1, 3, 31)


def _sum_metrics(rows: list[Metrics]) -> Metrics:
    keys = set().union(*rows) - NON_ADDITIVE - CASH_KEYS
    out: Metrics = {}
    for key in keys:
        values = [r.get(key) for r in rows]
        out[key] = None if any(v is None for v in values) else sum(values)  # type: ignore[arg-type]
    for key in CASH_KEYS:
        out[key] = None
    for key in NON_ADDITIVE:
        out[key] = rows[0].get(key)  # latest quarter's value
    return out


def _consecutive(quarters: list[QuarterRow]) -> bool:
    gaps = [(a.period_end - b.period_end).days for a, b in zip(quarters, quarters[1:])]
    return all(80 <= g <= 100 for g in gaps)


def _ttm(quarters: list[QuarterRow]) -> tuple[Metrics, date | None]:
    last4 = quarters[:4]
    if len(last4) < 4 or not _consecutive(last4):
        keys = set().union(*(q.income for q in last4)) if last4 else set()
        return {k: None for k in keys}, (last4[0].period_end if last4 else None)
    return _sum_metrics([q.income for q in last4]), last4[0].period_end


def _ttm_cash(by_end: dict[date, Filing], years: list[YearRow]) -> tuple[Metrics, str]:
    if not by_end:
        return {}, "none"
    latest_end = max(by_end)
    latest = by_end[latest_end]
    # The fiscal year that ended just before the latest quarter; no older substitute.
    prev_fy_end = date(latest_end.year - (0 if latest_end.month > 3 else 1), 3, 31)
    fy = next((y for y in years if y.fy_end == prev_fy_end), None)
    if latest_end.month == 3 and latest.year_to_date and latest.year_to_date.days >= 360:
        ytd = latest.year_to_date_metrics()
        return {k: ytd.get(k) for k in CASH_KEYS}, "latest FY"
    prior = by_end.get(date(latest_end.year - 1, latest_end.month, latest_end.day))
    if fy and latest.year_to_date and prior and prior.year_to_date:
        cur, old = latest.year_to_date_metrics(), prior.year_to_date_metrics()
        rolled = {}
        for k in CASH_KEYS:
            parts = (fy.income.get(k), cur.get(k), old.get(k))
            rolled[k] = None if any(p is None for p in parts) else parts[0] + parts[1] - parts[2]  # type: ignore[operator]
        if rolled.get("cfo") is not None:
            return rolled, "FY + YTD rolled forward"
    if fy:
        return {k: fy.income.get(k) for k in CASH_KEYS}, f"FY ending {fy.fy_end}"
    return {k: None for k in CASH_KEYS}, "none"


def _year_sheet(sheet: Metrics, income: Metrics) -> Metrics:
    """Older annual results (banks especially) carry no balance sheet, but do report paid-up
    capital and reserves excluding revaluation reserves: together, owners' equity."""
    if sheet.get("equity_owners") is not None:
        return sheet
    cap, res = income.get("paid_up_capital"), income.get("reserves_ex_revaluation")
    if cap is None or res is None:
        return sheet
    return {**sheet, "equity_owners": cap + res}


def _years(by_end: dict[date, Filing], quarters: list[QuarterRow]) -> list[YearRow]:
    march_sheets: dict[date, Metrics] = {}
    for filing in by_end.values():
        for period in (filing.balance_sheet, filing.previous_balance_sheet):
            if period is not None and period.end.month == 3 and period.end.day == 31:
                march_sheets.setdefault(period.end, filing.balance_metrics_for(period))
    fy_ends = sorted({_fy_end(q.period_end) for q in quarters}, reverse=True)
    years: list[YearRow] = []
    for fy_end in fy_ends:
        q4 = by_end.get(fy_end)
        if q4 and q4.year_to_date and q4.year_to_date.days >= 360:
            income, source = q4.year_to_date_metrics(), "annual"
            shares, how = shares_from(income)
        else:
            in_year = [q for q in quarters if _fy_end(q.period_end) == fy_end]
            if len(in_year) != 4 or not _consecutive(in_year):
                continue  # incomplete year (e.g. current FY in progress): no row
            income, source = _sum_metrics([q.income for q in in_year]), "sum_of_quarters"
            # Summed EPS is not restated for a mid-year bonus: take shares from the last quarter.
            shares, how = shares_from(in_year[0].income)
        exact = how.startswith("paid-up capital / face value (matches")
        years.append(
            YearRow(
                fy_end,
                income,
                source,
                _year_sheet(march_sheets.get(fy_end, {}), income),
                shares,
                exact,
            )
        )
    return years


def build_fundamentals(symbol: str, filings: Iterable[tuple[FilingRef, Filing]]) -> Fundamentals:
    pairs = list(filings)
    if not pairs:
        raise ValueError(f"No filings for {symbol}")
    consolidated = any(r.consolidated for r, _ in pairs)
    by_end = {r.period_end: f for r, f in pairs if r.consolidated == consolidated and f.quarter}
    if not by_end:
        raise ValueError(f"No quarterly filings for {symbol}")
    quarters = sorted(
        (QuarterRow(end, f.quarter_metrics()) for end, f in by_end.items()),
        key=lambda q: q.period_end,
        reverse=True,
    )
    latest = by_end[quarters[0].period_end]
    years = _years(by_end, quarters)
    ttm, ttm_end = _ttm(quarters)
    cash, basis = _ttm_cash(by_end, years)
    sheets = sorted(
        ((end, f) for end, f in by_end.items() if f.balance_sheet is not None), reverse=True
    )
    latest_bs_end, latest_bs = (
        (sheets[0][0], sheets[0][1].balance_metrics()) if sheets else (None, {})
    )
    q0 = quarters[0].income
    face = q0.get("face_value")
    shares, shares_note = shares_from(q0)
    return Fundamentals(
        symbol=symbol,
        consolidated=consolidated,
        is_bank=latest.is_bank,
        is_financial=latest.is_financial,
        quarters=tuple(quarters),
        years=tuple(years),
        ttm={**ttm, **cash},
        ttm_end=ttm_end,
        ttm_cash_basis=basis,
        latest_balance=latest_bs,
        latest_balance_date=latest_bs_end,
        shares=shares,
        face_value=face,
        shares_note=shares_note,
    )


def load_fundamentals(source: FilingsSource, symbol: str) -> Fundamentals:
    """Fetch every results filing for a symbol (cached) and assemble its history."""
    refs = source.list(symbol)
    if not refs:
        raise ValueError(f"NSE lists no results filings for {symbol}")
    consolidated = any(r.consolidated for r in refs)
    chosen = [r for r in refs if r.consolidated == consolidated]
    f = build_fundamentals(symbol, [(r, source.fetch(r)) for r in chosen])
    if f.is_bank:
        f = _with_asset_quality(source, f, refs)
    return f


AQ_KEYS = ("gnpa_pct", "nnpa_pct", "cet1_pct", "roa_pct", "gross_npa", "net_npa")


def _with_asset_quality(
    source: FilingsSource, f: Fundamentals, refs: list[FilingRef]
) -> Fundamentals:
    """Asset-quality ratios come from the standalone filing; consolidated ones leave them blank."""
    standalone = [r for r in refs if not r.consolidated]
    if not standalone:
        return f
    latest = max(standalone, key=lambda r: r.period_end)
    try:
        m = source.fetch(latest).quarter_metrics()
    except Exception as exc:  # noqa: BLE001 - optional data: leave the ratios missing, say so
        log.warning("Standalone filing for %s unreadable: %s", f.symbol, exc)
        return f
    aq = {k: m.get(k) for k in AQ_KEYS if m.get(k) is not None}
    return replace(f, asset_quality=aq, asset_quality_period=latest.period_end)
