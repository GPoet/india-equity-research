"""Everything the valuation lenses need, derived once from fundamentals + market data.

Each derived number records how it was obtained (self.notes) so the report can show it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from eqr.fundamentals import (
    Fundamentals,
    YearRow,
    owners_profit,
    share_action_factors,
    year_shares,
)
from eqr.market import MarketInputs
from eqr.valuation.formulas import cagr
from eqr.xbrl import Metrics

MAX_GROWTH = 0.20  # cap on extrapolated historical growth
GROWTH_YEARS = 5


@dataclass(frozen=True)
class PriceData:
    price: float
    as_of: str
    beta: float
    beta_source: str
    dps_ttm: float | None  # dividends per share, last 12 months
    dps_by_fy: dict[date, float]  # fiscal year end -> dividends per share paid in that FY
    fy_end_prices: dict[date, float]  # fiscal year end -> split-adjusted close
    # fiscal year end -> product of split/bonus ratios after that date (1.0 = none since)
    split_factor_by_fy: dict[date, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ValuationContext:
    f: Fundamentals
    m: MarketInputs
    p: PriceData
    shares: float | None
    market_cap: float | None
    pat_ttm: float | None
    eps_ttm: float | None
    bvps: float | None
    equity: float | None
    debt: float | None
    cash_like: float | None
    minority: float
    tax_rate: float
    cost_of_equity: float
    cost_of_debt: float | None
    wacc: float | None
    growth: float | None  # expected growth used by the lenses
    growth_inputs: dict[str, float | None]
    notes: tuple[str, ...] = field(default_factory=tuple)
    # fiscal year end -> bonus/split multiple since then (shares then x factor = today's units)
    share_factors: dict[date, float] = field(default_factory=dict)

    @property
    def years(self) -> tuple[YearRow, ...]:
        return self.f.years

    def adjusted_shares(self, y: YearRow) -> float | None:
        """That year's share count in today's units (after later bonuses/splits), so it can
        be paired with Yahoo's adjusted prices and dividends. Real issuance stays visible."""
        shares = year_shares(y)
        return shares * self.share_factors.get(y.fy_end, 1.0) if shares else None

    def annual(self, key: str, n: int) -> list[float | None]:
        return [y.income.get(key) for y in self.f.years[:n]]


def owners_pat(m: Metrics) -> float | None:
    return owners_profit(m)


def _tax_rate(f: Fundamentals, default: float, notes: list[str]) -> float:
    for y in f.years[:3]:
        tax, pbt = y.income.get("tax"), y.income.get("pbt")
        if tax is not None and pbt and pbt > 0 and 0.10 <= tax / pbt <= 0.40:
            return tax / pbt
    notes.append(f"Tax rate: company rate unavailable, used default {default:.2%}")
    return default


def _debt(f: Fundamentals, notes: list[str]) -> float | None:
    debt = f.latest_balance.get("total_debt")
    if debt is not None:
        return debt
    b = f.latest_balance
    no_tags = all(
        b.get(k) is None
        for k in ("borrowings_current", "borrowings_noncurrent", "borrowings", "debt_securities")
    )
    fy = f.years[0].income if f.years else {}
    rev, fin = fy.get("revenue"), fy.get("finance_costs")
    if b and no_tags and rev and fin is not None and fin < 0.01 * rev:
        notes.append(
            "Debt: no borrowings reported and finance costs under 1% of revenue; treated as debt-free"
        )
        return 0.0
    return None


def cash_like(b: Metrics) -> float | None:
    """Cash + other bank balances + current investments. Ind-AS balance sheets omit a line
    that is nil, so the two optional lines count as zero when absent; cash itself is required."""
    cash = b.get("cash")
    if cash is None:
        return None
    extras = [b.get("bank_balances"), b.get("current_investments")]
    return cash + sum(x for x in extras if x is not None)


CYCLICAL_DROP = 0.30  # a year-on-year profit fall bigger than this marks a cyclical


def _per_share(y: YearRow, key: str, factors: dict[date, float], is_bank: bool) -> float | None:
    """A year's figure per bonus/split-adjusted share, so mergers paid in stock and
    rights issues do not show up as growth."""
    value = (
        owners_pat(y.income)
        if key == "profit"
        else y.income.get("total_income" if is_bank else "revenue")
    )
    shares = year_shares(y)
    if value is None or not shares:
        return None
    return value / (shares * factors.get(y.fy_end, 1.0))


def _growth(
    f: Fundamentals, factors: dict[date, float], notes: list[str]
) -> tuple[float | None, dict[str, float | None]]:
    """Conservative expected growth: the lower of revenue and profit growth per share over
    up to 5 years (margins cannot expand forever); revenue only for cyclical profits."""
    years = f.years
    if len(years) < 3:
        notes.append("Growth: fewer than 3 fiscal years of history")
        return None, {}
    n = min(GROWTH_YEARS, len(years) - 1)
    first, last = years[n], years[0]
    span = last.fy_end.year - first.fy_end.year  # actual years elapsed, even if a row is missing
    rev = cagr(
        _per_share(first, "revenue", factors, f.is_bank),
        _per_share(last, "revenue", factors, f.is_bank),
        span,
    )
    pat = cagr(
        _per_share(first, "profit", factors, f.is_bank),
        _per_share(last, "profit", factors, f.is_bank),
        span,
    )
    if span != n:
        notes.append(
            f"Growth: {span - n} fiscal year(s) missing in the window; CAGR uses {span} years"
        )
    inputs: dict[str, float | None] = {
        f"revenue_per_share_cagr_{n}y": rev,
        f"profit_per_share_cagr_{n}y": pat,
    }
    profits = [owners_pat(y.income) for y in years[: n + 1]]
    known_profits = [p for p in profits if p is not None]
    drops = [
        newer < older * (1 - CYCLICAL_DROP)
        for newer, older in zip(known_profits, known_profits[1:])
        if older > 0
    ]
    cyclical = any(p <= 0 for p in known_profits) or any(drops)
    if cyclical and rev is not None:
        notes.append(
            "Growth: profits are cyclical (loss or deep trough in window); used revenue growth only"
        )
        raw = rev
    else:
        known = [g for g in (rev, pat) if g is not None]
        if not known:
            return None, inputs
        raw = min(known)
    used = max(0.0, min(raw, MAX_GROWTH))
    if used != raw:
        notes.append(
            f"Growth: historical {raw:.1%} clamped to {used:.1%} (range 0-{MAX_GROWTH:.0%})"
        )
    inputs["growth_used"] = used
    return used, inputs


def _cost_of_debt(f: Fundamentals, debt: float | None, m: MarketInputs) -> float | None:
    if not debt:
        return None
    fin = f.years[0].income.get("finance_costs") if f.years else None
    if fin is None:
        return None
    floor, cap = m.gsec_10y, m.gsec_10y + 0.06
    return min(max(fin / debt, floor), cap)


def build_context(f: Fundamentals, m: MarketInputs, p: PriceData) -> ValuationContext:
    notes: list[str] = []
    shares = f.shares
    pat = owners_pat(f.ttm)
    b = f.latest_balance
    equity = b.get("equity_owners")
    tax = _tax_rate(f, m.default_tax_rate, notes)
    debt = _debt(f, notes)
    cash = cash_like(b)
    mcap = p.price * shares if shares else None
    ke = m.cost_of_equity(p.beta)
    kd = _cost_of_debt(f, debt, m)
    if mcap is None or debt is None:
        wacc = None
    elif debt == 0 or kd is None:
        wacc = ke if debt == 0 else None
    else:
        wacc = (mcap * ke + debt * kd * (1 - tax)) / (mcap + debt)
    if not f.shares_note.startswith("paid-up capital / face value (matches"):
        notes.append(f"Shares: {f.shares_note}")
    detected, action_notes = share_action_factors(f.years)
    notes.extend(action_notes)
    factors = {**detected, **p.split_factor_by_fy}
    growth, growth_inputs = _growth(f, factors, notes)
    minority = b.get("minority_interest")
    if minority is None and f.consolidated and b:
        notes.append("Minority interest not reported in the balance sheet; treated as none")
    return ValuationContext(
        f=f,
        m=m,
        p=p,
        shares=shares,
        market_cap=mcap,
        pat_ttm=pat,
        eps_ttm=pat / shares if pat is not None and shares else None,
        bvps=equity / shares if equity is not None and shares else None,
        equity=equity,
        debt=debt,
        cash_like=cash,
        minority=minority or 0.0,
        tax_rate=tax,
        cost_of_equity=ke,
        cost_of_debt=kd,
        wacc=wacc,
        growth=growth,
        growth_inputs=growth_inputs,
        notes=tuple(notes),
        share_factors=factors,
    )
