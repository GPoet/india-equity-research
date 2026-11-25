"""Lenses that produce a value per share. Each takes the context and never raises on bad
data: it returns not_applicable with the reason instead."""

from __future__ import annotations

import statistics

from eqr.valuation import formulas as fx
from eqr.valuation.cashflows import (
    average_ebit,
    average_fcff,
    average_owner_earnings,
    maintenance_capex,
)
from eqr.valuation.context import ValuationContext, owners_pat
from eqr.valuation.models import LensResult, not_applicable

OWNER_EARNINGS_MAX_GROWTH = 0.15
RULE1_MAX_GROWTH = 0.15
GRAHAM_MAX_GROWTH_PCT = 15.0


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _equity_from_ev(ctx: ValuationContext, ev: float) -> float | None:
    if ctx.debt is None or ctx.cash_like is None:
        return None
    return ev - ctx.debt + ctx.cash_like - ctx.minority


def _per_share(ctx: ValuationContext, equity_value: float | None) -> float | None:
    return equity_value / ctx.shares if equity_value is not None and ctx.shares else None


def _dcf_value(ctx: ValuationContext, base: float, g1: float) -> float | None:
    ev = fx.two_stage_pv(base, g1, ctx.m.terminal_growth, ctx.wacc)  # type: ignore[arg-type]
    return _per_share(ctx, _equity_from_ev(ctx, ev))


def dcf(ctx: ValuationContext) -> LensResult:
    key, name, school = "dcf", "Discounted cash flow (FCFF)", "Damodaran / institutional standard"
    if ctx.f.is_financial:
        return not_applicable(
            key, name, school, "value", "Free cash flow is not meaningful for lenders"
        )
    base, samples = average_fcff(ctx)
    if base is None:
        return not_applicable(
            key, name, school, "value", "No year with both operating cash flow and capex"
        )
    if base <= 0:
        return not_applicable(
            key, name, school, "value", f"Average free cash flow is negative ({base:,.0f})"
        )
    if ctx.wacc is None or ctx.growth is None:
        return not_applicable(key, name, school, "value", "Cost of capital or growth unavailable")
    value = _dcf_value(ctx, base, ctx.growth)
    if value is None:
        return not_applicable(
            key, name, school, "value", "Debt or cash unknown for the equity bridge"
        )
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary=(
            f"Average free cash flow of {len(samples)} yr grown {_pct(ctx.growth)} for 5 yrs, "
            f"fading to {_pct(ctx.m.terminal_growth)}, discounted at WACC {_pct(ctx.wacc)}"
        ),
        inputs={
            "base_fcff": base,
            "growth": ctx.growth,
            "wacc": ctx.wacc,
            "terminal_growth": ctx.m.terminal_growth,
            "years_sampled": len(samples),
        },
    )


def reverse_dcf(ctx: ValuationContext) -> LensResult:
    key, name, school = "reverse_dcf", "Reverse DCF (growth priced in)", "Michael Mauboussin"
    if ctx.f.is_financial:
        return not_applicable(
            key, name, school, "metric", "Free cash flow is not meaningful for lenders"
        )
    base, _ = average_fcff(ctx)
    if base is None or base <= 0 or ctx.wacc is None:
        return not_applicable(key, name, school, "metric", "Needs positive free cash flow and WACC")
    if _dcf_value(ctx, base, 0.0) is None:
        return not_applicable(
            key, name, school, "metric", "Debt or cash unknown for the equity bridge"
        )
    implied = fx.solve_growth(lambda g: _dcf_value(ctx, base, g) or 0.0, ctx.p.price)
    if implied is None:
        return not_applicable(
            key, name, school, "metric", "Price is outside what -30% to +60% growth can justify"
        )
    hist = ctx.growth
    verdict = (
        None
        if hist is None
        else (
            "priced below its track record"
            if implied < hist
            else "prices in more than its track record"
        )
    )
    return LensResult(
        key,
        name,
        school,
        "metric",
        True,
        value=implied,
        verdict=verdict,
        summary=(
            f"Today's price implies {_pct(implied)} free-cash-flow growth for 5 years "
            f"(historical growth {_pct(hist)})"
        ),
        inputs={"implied_growth": implied, "historical_growth": hist, "price": ctx.p.price},
    )


def buffett_owner_earnings(ctx: ValuationContext) -> LensResult:
    key, name, school = "owner_earnings", "Owner earnings value", "Warren Buffett"
    if ctx.f.is_financial:
        return not_applicable(
            key, name, school, "value", "Owner earnings need capex; not meaningful for lenders"
        )
    base, samples, how = average_owner_earnings(ctx)
    if base is None or base <= 0:
        return not_applicable(key, name, school, "value", "Owner earnings unavailable or negative")
    if ctx.growth is None or not ctx.shares:
        return not_applicable(key, name, school, "value", "Growth or share count unavailable")
    g = min(ctx.growth, OWNER_EARNINGS_MAX_GROWTH)
    value = fx.two_stage_pv(base, g, ctx.m.terminal_growth, ctx.cost_of_equity) / ctx.shares
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary=(
            f"Owner earnings (profit + D&A - maintenance capex, {how}) averaged over "
            f"{len(samples)} yr, grown {_pct(g)}, discounted at cost of equity {_pct(ctx.cost_of_equity)}. "
            "Buffett discounts at the bond rate and demands a wide margin of safety instead."
        ),
        inputs={"owner_earnings": base, "growth": g, "cost_of_equity": ctx.cost_of_equity},
    )


def earnings_power_value(ctx: ValuationContext) -> LensResult:
    key, name, school = "epv", "Earnings power value (no growth)", "Bruce Greenwald"
    if ctx.f.is_financial:
        return not_applicable(key, name, school, "value", "Not meaningful for lenders")
    ebit, samples = average_ebit(ctx)
    if ebit is None or ebit <= 0 or ctx.wacc is None:
        return not_applicable(
            key, name, school, "value", "Needs positive operating profit and WACC"
        )
    adj = 0.0
    gaps = []  # depreciation minus maintenance capex, over the same years as the EBIT average
    for i, y in enumerate(ctx.years[: len(samples)]):
        maint, _ = maintenance_capex(y, ctx.years[i + 1] if i + 1 < len(ctx.years) else None)
        if maint is not None and y.income.get("depreciation") is not None:
            gaps.append(y.income["depreciation"] - maint)
    if gaps:
        # Depreciation above upkeep spending adds to earnings power; below it subtracts.
        adj = statistics.mean(gaps) * (1 - ctx.tax_rate)
    epv_firm = (ebit * (1 - ctx.tax_rate) + adj) / ctx.wacc
    value = _per_share(ctx, _equity_from_ev(ctx, epv_firm))
    if value is None:
        return not_applicable(
            key, name, school, "value", "Debt or cash unknown for the equity bridge"
        )
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary=(
            f"Average operating profit of {len(samples)} yr after tax, as a perpetuity at WACC "
            f"{_pct(ctx.wacc)}. Value of today's business with zero growth: a floor."
        ),
        inputs={
            "avg_ebit": ebit,
            "tax_rate": ctx.tax_rate,
            "wacc": ctx.wacc,
            "excess_depreciation": adj,
        },
    )


def graham_number(ctx: ValuationContext) -> LensResult:
    key, name, school = "graham_number", "Graham number", "Benjamin Graham"
    if ctx.eps_ttm is None or ctx.bvps is None:
        return not_applicable(key, name, school, "value", "EPS or book value per share unavailable")
    value = fx.graham_number(ctx.eps_ttm, ctx.bvps)
    if value is None:
        return not_applicable(key, name, school, "value", "Needs positive earnings and book value")
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary="Highest price a defensive investor should pay: sqrt(22.5 x EPS x book value per share)",
        inputs={"eps_ttm": ctx.eps_ttm, "bvps": ctx.bvps},
    )


def graham_formula(ctx: ValuationContext) -> LensResult:
    key, name, school = "graham_formula", "Graham growth formula (1974)", "Benjamin Graham"
    if ctx.eps_ttm is None or ctx.eps_ttm <= 0 or ctx.growth is None:
        return not_applicable(
            key, name, school, "value", "Needs positive EPS and a growth estimate"
        )
    g_pct = min(ctx.growth * 100, GRAHAM_MAX_GROWTH_PCT)
    y_pct = ctx.m.aaa_yield * 100
    value = fx.graham_formula(ctx.eps_ttm, g_pct, y_pct)
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary=f"EPS x (8.5 + 2 x {g_pct:.1f}) x 4.4 / {y_pct:.2f} (Indian AAA yield)",
        inputs={"eps_ttm": ctx.eps_ttm, "growth_pct": g_pct, "aaa_yield_pct": y_pct},
    )


def lynch(ctx: ValuationContext) -> LensResult:
    key, name, school = "lynch", "PEG fair value", "Peter Lynch"
    g = ctx.growth
    if ctx.eps_ttm is None or ctx.eps_ttm <= 0 or g is None or g <= 0:
        return not_applicable(
            key, name, school, "value", "Needs positive EPS and positive earnings growth"
        )
    g_pct = g * 100
    pe = ctx.p.price / ctx.eps_ttm
    dy_known = ctx.p.dps_ttm is not None
    dy_pct = (ctx.p.dps_ttm or 0.0) / ctx.p.price * 100  # unknown dividend: ratio excludes it
    ratio = fx.lynch_ratio(pe, g_pct, dy_pct)
    verdict = (
        "very attractive"
        if ratio >= 2
        else "attractive"
        if ratio >= 1.5
        else "fair"
        if ratio >= 1
        else "expensive"
    )
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=fx.lynch_fair_value(ctx.eps_ttm, g_pct),
        verdict=verdict,
        summary=(
            f"Fair P/E = earnings growth ({g_pct:.1f}%, capped at 25). (Growth + yield) / P/E = "
            f"{ratio:.2f}; Lynch wanted 2 or more"
            + ("" if dy_known else " (dividend yield unknown, left out)")
        ),
        inputs={
            "eps_ttm": ctx.eps_ttm,
            "growth_pct": g_pct,
            "pe": pe,
            "dividend_yield_pct": dy_pct,
            "lynch_ratio": ratio,
        },
    )


def _historical_pe(ctx: ValuationContext) -> float | None:
    pes = []
    for y in ctx.years[:10]:
        price, pat, shares = (
            ctx.p.fy_end_prices.get(y.fy_end),
            owners_pat(y.income),
            ctx.adjusted_shares(y),
        )
        if price and pat and pat > 0 and shares:
            pes.append(price / (pat / shares))
    return statistics.median(pes) if len(pes) >= 3 else None


def rule_one(ctx: ValuationContext) -> LensResult:
    key, name, school = "rule1", "Sticker price and margin-of-safety price", "Phil Town (Rule #1)"
    if ctx.eps_ttm is None or ctx.eps_ttm <= 0 or ctx.growth is None or ctx.growth <= 0:
        return not_applicable(key, name, school, "value", "Needs positive EPS and positive growth")
    g = min(ctx.growth, RULE1_MAX_GROWTH)
    pe_hist = _historical_pe(ctx)
    sticker = fx.rule1_sticker(ctx.eps_ttm, g, pe_hist)
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=sticker,
        summary=(
            f"EPS grown {_pct(g)} for 10 years x future P/E (lower of {2 * g * 100:.0f} and "
            f"historical {pe_hist:.1f}) discounted at 15%/yr. Buy below {sticker / 2:,.0f} (50% margin)."
            if pe_hist
            else f"EPS grown {_pct(g)} for 10 years x P/E {2 * g * 100:.0f}, discounted at 15%/yr. "
            f"Buy below {sticker / 2:,.0f} (50% margin). Historical P/E unavailable."
        ),
        inputs={
            "eps_ttm": ctx.eps_ttm,
            "growth": g,
            "historical_pe": pe_hist,
            "mos_price": sticker / 2,
        },
    )


def dividend_discount(ctx: ValuationContext) -> LensResult:
    key, name, school = "ddm", "Dividend discount (two-stage)", "John Burr Williams / Gordon"
    dps = ctx.p.dps_ttm
    if dps is None or dps <= 0 or ctx.pat_ttm is None or ctx.pat_ttm <= 0 or not ctx.shares:
        return not_applicable(key, name, school, "value", "No regular dividend or no profit")
    payout = dps * ctx.shares / ctx.pat_ttm
    paid_years = sum(1 for v in ctx.p.dps_by_fy.values() if v > 0)
    if payout < 0.30 or paid_years < 4:
        return not_applicable(
            key,
            name,
            school,
            "value",
            f"Payout {payout:.0%} / {paid_years} paying years: dividends are not the main return",
        )
    if ctx.growth is None:
        return not_applicable(key, name, school, "value", "Growth estimate unavailable")
    g = min(ctx.growth, OWNER_EARNINGS_MAX_GROWTH)
    value = fx.two_stage_pv(dps, g, ctx.m.terminal_growth, ctx.cost_of_equity)
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary=f"Dividend {dps:,.2f}/share grown {_pct(g)}, fading to {_pct(ctx.m.terminal_growth)}, at cost of equity {_pct(ctx.cost_of_equity)}",
        inputs={
            "dps_ttm": dps,
            "payout": payout,
            "growth": g,
            "cost_of_equity": ctx.cost_of_equity,
        },
    )


def roe_samples(ctx: ValuationContext, n: int = 3) -> list[float]:
    out: list[float] = []
    ys = ctx.years
    for i, y in enumerate(ys):
        pat, eq = owners_pat(y.income), y.balance.get("equity_owners")
        older = ys[i + 1] if i + 1 < len(ys) else None
        adjacent = older is not None and y.fy_end.year - older.fy_end.year == 1
        prev = older.balance.get("equity_owners") if adjacent else None
        if pat is None or eq is None or eq <= 0:
            continue
        out.append(pat / ((eq + prev) / 2) if prev else pat / eq)
        if len(out) == n:
            break
    return out


def _retention(ctx: ValuationContext) -> float | None:
    ratios = []
    for y in ctx.years[:5]:
        dps, pat, shares = (
            ctx.p.dps_by_fy.get(y.fy_end),
            owners_pat(y.income),
            ctx.adjusted_shares(y),
        )
        if dps is not None and pat and pat > 0 and shares:
            ratios.append(min(max(1 - dps * shares / pat, 0.0), 1.0))
    return statistics.mean(ratios) if ratios else None


def residual_income(ctx: ValuationContext) -> LensResult:
    key, name, school = (
        "residual_income",
        "Residual income (excess return on book)",
        "Edwards-Bell-Ohlson, used for banks",
    )
    roes = roe_samples(ctx)
    if not roes or ctx.equity is None or not ctx.shares:
        return not_applicable(
            key, name, school, "value", "Needs book value and at least one year of ROE"
        )
    retention = _retention(ctx)
    if retention is None:
        return not_applicable(
            key, name, school, "value", "Dividend history unavailable for retention ratio"
        )
    roe = statistics.mean(roes)
    value = (
        fx.residual_income_value(
            ctx.equity, roe, ctx.cost_of_equity, retention, ctx.m.terminal_growth
        )
        / ctx.shares
    )
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=value,
        summary=(
            f"Book value plus the present value of returns above the {_pct(ctx.cost_of_equity)} cost of equity; "
            f"ROE {_pct(roe)} (avg {len(roes)} yr) held 5 yrs then fading to the cost of equity"
        ),
        inputs={
            "book_value": ctx.equity,
            "roe": roe,
            "retention": retention,
            "cost_of_equity": ctx.cost_of_equity,
        },
    )


def justified_pb(ctx: ValuationContext) -> LensResult:
    key, name, school = "justified_pb", "Justified price-to-book", "Gordon growth, used for banks"
    roes = roe_samples(ctx)
    if not roes or ctx.bvps is None or ctx.bvps <= 0:
        return not_applicable(key, name, school, "value", "Needs book value and ROE")
    roe, g = statistics.mean(roes), ctx.m.terminal_growth
    pb = fx.justified_pb(roe, ctx.cost_of_equity, g)
    if pb <= 0:
        return not_applicable(
            key, name, school, "value", f"ROE {_pct(roe)} below long-run growth: no positive value"
        )
    return LensResult(
        key,
        name,
        school,
        "value",
        True,
        value=pb * ctx.bvps,
        summary=f"Fair P/B = (ROE {_pct(roe)} - g {_pct(g)}) / (Ke {_pct(ctx.cost_of_equity)} - g) = {pb:.2f}x book",
        inputs={
            "roe": roe,
            "growth": g,
            "cost_of_equity": ctx.cost_of_equity,
            "fair_pb": pb,
            "bvps": ctx.bvps,
        },
    )


def reverse_residual_income(ctx: ValuationContext) -> LensResult:
    """For lenders: the ROE the market price implies, against what the company has earned."""
    key, name, school = (
        "reverse_ri",
        "Reverse residual income (ROE priced in)",
        "Damodaran, for banks",
    )
    roes = roe_samples(ctx)
    retention = _retention(ctx)
    if not roes or ctx.equity is None or not ctx.shares or retention is None:
        return not_applicable(
            key, name, school, "metric", "Needs book value, ROE history and dividends"
        )

    def value_at(roe: float) -> float:
        return (
            fx.residual_income_value(
                ctx.equity, roe, ctx.cost_of_equity, retention, ctx.m.terminal_growth
            )
            / ctx.shares
        )

    implied = fx.solve_growth(value_at, ctx.p.price, lo=-0.20, hi=0.80)
    if implied is None:
        return not_applicable(
            key,
            name,
            school,
            "metric",
            "Price is outside what any ROE from -20% to 80% can justify",
        )
    actual = statistics.mean(roes)
    return LensResult(
        key,
        name,
        school,
        "metric",
        True,
        value=implied,
        verdict="priced below its track record"
        if implied < actual
        else "prices in more than its track record",
        summary=(
            f"Today's price implies an ROE of {_pct(implied)} for 5 years (fading after), against "
            f"{_pct(actual)} earned recently, at a {_pct(ctx.cost_of_equity)} cost of equity"
        ),
        inputs={"implied_roe": implied, "recent_roe": actual, "price": ctx.p.price},
    )


VALUE_LENSES = (
    dcf,
    buffett_owner_earnings,
    earnings_power_value,
    residual_income,
    justified_pb,
    dividend_discount,
    graham_formula,
    graham_number,
    lynch,
    rule_one,
)
