"""Cash-flow building blocks: free cash flow, owner earnings, maintenance capex, EBIT."""

from __future__ import annotations

import statistics

from eqr.fundamentals import YearRow
from eqr.valuation.context import ValuationContext, owners_pat
from eqr.xbrl import Metrics

SAMPLE_YEARS = 3


def capex(m: Metrics) -> float | None:
    """Capital spending (positive). Intangibles capex is an optional line: absent means nil."""
    ppe = m.get("capex_ppe")
    if ppe is None:
        return None
    return abs(ppe) + abs(m.get("capex_intangibles") or 0.0)


def fcff(m: Metrics, tax_rate: float) -> float | None:
    """Free cash flow to the firm = CFO - capex (+ after-tax interest if it sits inside CFO)."""
    cfo, cx = m.get("cfo"), capex(m)
    if cfo is None or cx is None:
        return None
    interest_in_cfo = abs(m.get("interest_paid_operating") or 0.0)
    return cfo - cx + interest_in_cfo * (1 - tax_rate)


def ebit(m: Metrics) -> float | None:
    """Operating profit = PBT before exceptional items + finance costs - other income."""
    parts = [m.get("pbt_before_exceptional"), m.get("finance_costs"), m.get("other_income")]
    if any(p is None for p in parts):
        return None
    return parts[0] + parts[1] - parts[2]  # type: ignore[operator]


def maintenance_capex(cur: YearRow, prev: YearRow | None) -> tuple[float | None, str]:
    """Bruce Greenwald's estimate: capex minus growth capex, where growth capex is
    (PPE / sales) x increase in sales. Falls back to min(capex, depreciation)."""
    cx = capex(cur.income)
    if cx is None:
        return None, "capex unknown"
    if prev is not None:
        ppe_now, ppe_then = cur.balance.get("ppe"), prev.balance.get("ppe")
        rev_now, rev_then = cur.income.get("revenue"), prev.income.get("revenue")
        if (
            all(v is not None for v in (ppe_now, ppe_then, rev_now, rev_then))
            and rev_now
            and rev_then
        ):
            ratio = (ppe_now / rev_now + ppe_then / rev_then) / 2  # type: ignore[operator]
            growth_capex = ratio * max(rev_now - rev_then, 0.0)  # type: ignore[operator]
            return min(max(cx - growth_capex, 0.0), cx), "Greenwald (PPE/sales x sales growth)"
    dep = cur.income.get("depreciation")
    if dep is None:
        return None, "depreciation unknown"
    return min(cx, dep), "approximated as min(capex, depreciation)"


def owner_earnings(cur: YearRow, prev: YearRow | None) -> tuple[float | None, str]:
    """Warren Buffett (1986 letter): net income + depreciation/amortisation - maintenance capex."""
    pat, dep = owners_pat(cur.income), cur.income.get("depreciation")
    maint, how = maintenance_capex(cur, prev)
    if pat is None or dep is None or maint is None:
        return None, how
    return pat + dep - maint, how


def _year_pairs(ctx: ValuationContext) -> list[tuple[YearRow, YearRow | None]]:
    ys = ctx.years
    return [(ys[i], ys[i + 1] if i + 1 < len(ys) else None) for i in range(len(ys))]


def average_fcff(ctx: ValuationContext) -> tuple[float | None, list[float]]:
    samples = [v for y in ctx.years if (v := fcff(y.income, ctx.tax_rate)) is not None]
    samples = samples[:SAMPLE_YEARS]
    return (statistics.mean(samples) if samples else None), samples


def average_owner_earnings(ctx: ValuationContext) -> tuple[float | None, list[float], str]:
    samples, how = [], ""
    for cur, prev in _year_pairs(ctx):
        value, method = owner_earnings(cur, prev)
        if value is not None:
            samples.append(value)
            how = how or method
        if len(samples) == SAMPLE_YEARS:
            break
    return (statistics.mean(samples) if samples else None), samples, how


def average_ebit(ctx: ValuationContext) -> tuple[float | None, list[float]]:
    samples = [v for y in ctx.years[:SAMPLE_YEARS] if (v := ebit(y.income)) is not None]
    return (statistics.mean(samples) if samples else None), samples
