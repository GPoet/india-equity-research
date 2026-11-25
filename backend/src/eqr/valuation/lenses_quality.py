"""Quality, safety and screening lenses: scores and pass/fail tests, not prices."""

from __future__ import annotations

import statistics

from eqr.fundamentals import YearRow
from eqr.valuation import formulas as fx
from eqr.valuation.cashflows import ebit
from eqr.valuation.context import ValuationContext, owners_pat
from eqr.valuation.lenses_value import roe_samples
from eqr.valuation.models import LensResult, not_applicable
from eqr.xbrl import Metrics


def _ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b else None


def _cogs(m: Metrics) -> float | None:
    parts = [
        m.get("cost_of_materials"),
        m.get("purchases_stock_in_trade"),
        m.get("inventory_change"),
    ]
    known = [p for p in parts if p is not None]
    return sum(known) if known else None


def _gross_margin(m: Metrics) -> float | None:
    rev, cogs = m.get("revenue"), _cogs(m)
    return (rev - cogs) / rev if rev and cogs is not None else None


def _two_full_years(ctx: ValuationContext) -> tuple[YearRow, YearRow] | None:
    full = [y for y in ctx.years if y.balance and y.income.get("cfo") is not None]
    for a, b in zip(full, full[1:]):
        if a.fy_end.year - b.fy_end.year == 1:
            return a, b
    return None


def piotroski(ctx: ValuationContext) -> LensResult:
    key, name, school = "piotroski", "Piotroski F-score", "Joseph Piotroski"
    if ctx.f.is_financial:
        return not_applicable(key, name, school, "score", "Designed for non-financial companies")
    pair = _two_full_years(ctx)
    if pair is None:
        return not_applicable(
            key,
            name,
            school,
            "score",
            "Needs two consecutive years with balance sheet and cash flow",
        )
    cur, prev = pair
    c, p, cb, pb = cur.income, prev.income, cur.balance, prev.balance
    roa = _ratio(owners_pat(c), cb.get("total_assets"))
    roa_prev = _ratio(owners_pat(p), pb.get("total_assets"))
    lev = _ratio(cb.get("borrowings_noncurrent"), cb.get("total_assets"))
    lev_prev = _ratio(pb.get("borrowings_noncurrent"), pb.get("total_assets"))
    cr = _ratio(cb.get("current_assets"), cb.get("current_liabilities"))
    cr_prev = _ratio(pb.get("current_assets"), pb.get("current_liabilities"))
    gm, gm_prev = _gross_margin(c), _gross_margin(p)
    at = _ratio(c.get("revenue"), cb.get("total_assets"))
    at_prev = _ratio(p.get("revenue"), pb.get("total_assets"))
    shares, shares_prev = cb.get("equity_share_capital"), pb.get("equity_share_capital")

    def test(ok: bool | None) -> bool | None:
        return ok

    checks = {
        "positive ROA": test(None if roa is None else roa > 0),
        "positive operating cash flow": test(None if c.get("cfo") is None else c["cfo"] > 0),
        "ROA improved": test(None if roa is None or roa_prev is None else roa > roa_prev),
        "cash flow above profit": test(
            None if c.get("cfo") is None or owners_pat(c) is None else c["cfo"] > owners_pat(c)
        ),
        "long-term debt ratio fell": test(
            None if lev is None or lev_prev is None else lev <= lev_prev
        ),
        "current ratio improved": test(None if cr is None or cr_prev is None else cr > cr_prev),
        "no new shares issued": test(
            None if shares is None or shares_prev is None else shares <= shares_prev
        ),
        "gross margin improved": test(None if gm is None or gm_prev is None else gm > gm_prev),
        "asset turnover improved": test(None if at is None or at_prev is None else at > at_prev),
    }
    known = {k: v for k, v in checks.items() if v is not None}
    score = sum(known.values())
    if len(known) < 7:
        return not_applicable(
            key, name, school, "score", f"Only {len(known)} of 9 tests computable"
        )
    verdict = "strong" if score >= 7 else "weak" if score <= 3 else "average"
    failed = [k for k, v in known.items() if not v]
    return LensResult(
        key,
        name,
        school,
        "score",
        True,
        value=float(score),
        verdict=verdict,
        summary=f"{score}/{len(known)} for FY{cur.fy_end.year % 100} vs FY{prev.fy_end.year % 100}. Failed: {', '.join(failed) or 'none'}",
        inputs={k: (None if v is None else int(v)) for k, v in checks.items()},
    )


def altman(ctx: ValuationContext) -> LensResult:
    key, name, school = "altman_z", "Altman Z'' (emerging markets)", "Edward Altman"
    if ctx.f.is_financial:
        return not_applicable(key, name, school, "score", "Not designed for financial companies")
    y = next((y for y in ctx.years if y.balance), None)
    if y is None:
        return not_applicable(key, name, school, "score", "No annual balance sheet")
    b, m = y.balance, y.income
    ta, eq = b.get("total_assets"), b.get("total_equity")
    parts = (
        b.get("current_assets"),
        b.get("current_liabilities"),
        b.get("other_equity"),
        ebit(m),
        ta,
        eq,
    )
    if any(v is None for v in parts) or not ta or ta == eq:
        return not_applicable(
            key,
            name,
            school,
            "score",
            "Missing current assets/liabilities, reserves or operating profit",
        )
    ca, cl, re_, e, ta, eq = parts  # type: ignore[misc]
    z = fx.altman_z_em((ca - cl) / ta, re_ / ta, e / ta, eq / (ta - eq))
    verdict = "safe" if z > 5.85 else "grey zone" if z >= 4.15 else "distress"
    return LensResult(
        key,
        name,
        school,
        "score",
        True,
        value=z,
        verdict=verdict,
        summary=f"Z'' = {z:.2f} for FY{y.fy_end.year % 100} (safe above 5.85, distress below 4.15)",
        inputs={
            "working_capital/assets": (ca - cl) / ta,
            "reserves/assets": re_ / ta,
            "ebit/assets": e / ta,
            "equity/liabilities": eq / (ta - eq),
        },
    )


def beneish(ctx: ValuationContext) -> LensResult:
    key, name, school = "beneish_m", "Beneish M-score (earnings manipulation)", "Messod Beneish"
    if ctx.f.is_financial:
        return not_applicable(key, name, school, "score", "Not designed for financial companies")
    pair = _two_full_years(ctx)
    if pair is None:
        return not_applicable(
            key,
            name,
            school,
            "score",
            "Needs two consecutive years with balance sheet and cash flow",
        )
    cur, prev = pair
    c, p, cb, pb = cur.income, prev.income, cur.balance, prev.balance

    def get(*vals: float | None) -> bool:
        return all(v is not None for v in vals)

    rev, rev_p = c.get("revenue"), p.get("revenue")
    rec, rec_p = cb.get("trade_receivables"), pb.get("trade_receivables")
    gm, gm_p = _gross_margin(c), _gross_margin(p)
    ta, ta_p = cb.get("total_assets"), pb.get("total_assets")
    ca, ca_p = cb.get("current_assets"), pb.get("current_assets")
    ppe, ppe_p = cb.get("ppe"), pb.get("ppe")
    dep, dep_p = c.get("depreciation"), p.get("depreciation")
    sga, sga_p = c.get("other_expenses"), p.get("other_expenses")
    cl, cl_p = cb.get("current_liabilities"), pb.get("current_liabilities")
    ltd, ltd_p = cb.get("borrowings_noncurrent"), pb.get("borrowings_noncurrent")
    pat, cfo = owners_pat(c), c.get("cfo")
    if not get(
        rev,
        rev_p,
        rec,
        rec_p,
        gm,
        gm_p,
        ta,
        ta_p,
        ca,
        ca_p,
        ppe,
        ppe_p,
        dep,
        dep_p,
        sga,
        sga_p,
        cl,
        cl_p,
        pat,
        cfo,
    ):
        return not_applicable(
            key,
            name,
            school,
            "score",
            "Missing receivables, margins, fixed assets or expenses for two years",
        )
    ltd, ltd_p = ltd or 0.0, ltd_p or 0.0  # long-term borrowings line absent = none
    try:
        idx = {
            "dsri": (rec / rev) / (rec_p / rev_p),
            "gmi": gm_p / gm,
            "aqi": (1 - (ca + ppe) / ta) / (1 - (ca_p + ppe_p) / ta_p),
            "sgi": rev / rev_p,
            "depi": (dep_p / (dep_p + ppe_p)) / (dep / (dep + ppe)),
            "sgai": (sga / rev) / (sga_p / rev_p),
            "lvgi": ((cl + ltd) / ta) / ((cl_p + ltd_p) / ta_p),
            "tata": (pat - cfo) / ta,
        }
    except ZeroDivisionError:
        return not_applicable(key, name, school, "score", "A denominator was zero")
    m = fx.beneish_m(**idx)
    verdict = "possible manipulation" if m > -1.78 else "unlikely manipulator"
    return LensResult(
        key,
        name,
        school,
        "score",
        True,
        value=m,
        verdict=verdict,
        summary=f"M = {m:.2f} (above -1.78 is a red flag). SG&A proxied by 'other expenses'.",
        inputs={k: round(v, 3) for k, v in idx.items()},
    )


def magic_formula(ctx: ValuationContext) -> LensResult:
    key, name, school = "magic_formula", "Magic formula inputs", "Joel Greenblatt"
    if ctx.f.is_financial:
        return not_applicable(
            key, name, school, "metric", "Greenblatt excludes financial companies"
        )
    y = next((y for y in ctx.years if y.balance), None)
    e = ebit(ctx.f.ttm) if ebit(ctx.f.ttm) is not None else (ebit(y.income) if y else None)
    if (
        y is None
        or e is None
        or ctx.market_cap is None
        or ctx.debt is None
        or ctx.cash_like is None
    ):
        return not_applicable(
            key, name, school, "metric", "Needs operating profit, balance sheet, debt and cash"
        )
    b = y.balance
    if any(b.get(k) is None for k in ("current_assets", "current_liabilities", "ppe")):
        return not_applicable(
            key, name, school, "metric", "Missing working capital or fixed assets"
        )
    nwc = (b["current_assets"] - ctx.cash_like) - (
        b["current_liabilities"] - (b.get("borrowings_current") or 0.0)
    )
    capital = max(nwc, 0.0) + b["ppe"]
    ev = ctx.market_cap + ctx.debt - ctx.cash_like
    ey, roc = e / ev if ev > 0 else None, e / capital if capital > 0 else None
    if ey is None or roc is None:
        return not_applicable(
            key, name, school, "metric", "Enterprise value or capital not positive"
        )
    verdict = "passes" if ey >= ctx.m.gsec_10y and roc >= 0.25 else "fails"
    return LensResult(
        key,
        name,
        school,
        "metric",
        True,
        value=ey,
        verdict=verdict,
        summary=(
            f"Earnings yield (EBIT/EV) {ey:.1%}, return on capital {roc:.0%}. Greenblatt ranks the market on both; "
            f"here the bar is yield above the G-sec ({ctx.m.gsec_10y:.2%}) and ROC 25%+."
        ),
        inputs={"earnings_yield": ey, "return_on_capital": roc, "ebit": e, "enterprise_value": ev},
    )


def coffee_can(ctx: ValuationContext) -> LensResult:
    key, name, school = "coffee_can", "Coffee Can screen", "Saurabh Mukherjea (Marcellus)"
    ys = list(ctx.years[:11])
    if len(ys) < 4:
        return not_applicable(key, name, school, "screen", "Needs at least 4 years of history")
    top = "total_income" if ctx.f.is_bank else "revenue"
    growth = [_ratio(a.income.get(top), b.income.get(top)) for a, b in zip(ys, ys[1:])]
    growth_ok = [g - 1 >= 0.10 for g in growth if g is not None]
    if ctx.f.is_financial:
        returns = roe_samples(ctx, n=10)
        label, bar = "ROE", 0.15
    else:
        returns = []
        for y in ys:
            e, b = ebit(y.income), y.balance
            ce = (
                None
                if b.get("total_equity") is None or b.get("total_debt") is None
                else b["total_equity"] + b["total_debt"]
            )
            if e is not None and ce:
                returns.append(e / ce)
        label, bar = "ROCE", 0.15
    returns_ok = [r >= bar for r in returns]
    passed = bool(growth_ok) and bool(returns_ok) and all(growth_ok) and all(returns_ok)
    verdict = "passes" if passed else "fails"
    return LensResult(
        key,
        name,
        school,
        "screen",
        True,
        value=float(sum(growth_ok) + sum(returns_ok)),
        verdict=verdict,
        summary=(
            f"Revenue growth >=10% in {sum(growth_ok)}/{len(growth_ok)} years; {label} >=15% in "
            f"{sum(returns_ok)}/{len(returns_ok)} years. Rule needs all of 10 years; "
            f"{len(growth_ok)} growth and {len(returns_ok)} return years available."
        ),
        inputs={
            "growth_years": len(growth_ok),
            "return_years": len(returns_ok),
            "min_growth": min((g - 1 for g in growth if g is not None), default=None),
            f"min_{label.lower()}": min(returns, default=None),
        },
    )


def buffett_checks(ctx: ValuationContext) -> LensResult:
    key, name, school = "buffett_checks", "Buffett quality checks", "Warren Buffett"
    roes = roe_samples(ctx, n=5)
    pats = [owners_pat(y.income) for y in ctx.years[:6]]
    known = [p for p in pats if p is not None]
    checks: dict[str, bool | None] = {
        "ROE 15%+ in every available year": (all(r >= 0.15 for r in roes) if roes else None),
        "profit grew in most of the last 5 years": (
            sum(a > b for a, b in zip(known, known[1:])) >= 3 if len(known) >= 5 else None
        ),
        "no losses in the last 5 years": (
            all(p > 0 for p in known[:5]) if len(known) >= 5 else None
        ),
    }
    if not ctx.f.is_financial:
        eq = ctx.f.latest_balance.get("total_equity")
        checks["debt below half of equity"] = (
            None if ctx.debt is None or not eq else ctx.debt / eq < 0.5
        )
    known_checks = {k: v for k, v in checks.items() if v is not None}
    if len(known_checks) < 2:
        return not_applicable(key, name, school, "screen", "Not enough history")
    passed = sum(known_checks.values())
    verdict = (
        "passes"
        if passed == len(known_checks)
        else "mixed"
        if passed >= len(known_checks) - 1
        else "fails"
    )
    return LensResult(
        key,
        name,
        school,
        "screen",
        True,
        value=float(passed),
        verdict=verdict,
        summary=f"{passed}/{len(known_checks)}: "
        + "; ".join(f"{k} {'yes' if v else 'NO'}" for k, v in known_checks.items()),
        inputs={k: (None if v is None else int(v)) for k, v in checks.items()}
        | {"avg_roe": statistics.mean(roes) if roes else None},
    )


def retained_earnings_test(ctx: ValuationContext) -> LensResult:
    key, name, school = "one_dollar_test", "$1 retained-earnings test", "Warren Buffett"
    ys = ctx.years[:5]
    if len(ys) < 5 or not ctx.shares:
        return not_applicable(key, name, school, "screen", "Needs 5 fiscal years")
    # Price at the end of the oldest year, against earnings retained in the 4 years after it.
    start = ctx.p.fy_end_prices.get(ys[-1].fy_end)
    retained = 0.0
    for y in ys[:-1]:
        pat, dps = owners_pat(y.income), ctx.p.dps_by_fy.get(y.fy_end)
        if pat is None or dps is None:
            return not_applicable(
                key,
                name,
                school,
                "screen",
                f"Profit or dividends missing for FY{y.fy_end.year % 100}",
            )
        retained += pat - dps * ctx.shares
    earned = sum(owners_pat(y.income) or 0.0 for y in ys[:-1])
    if start is None or earned <= 0:
        return not_applicable(key, name, school, "screen", "Start price unavailable or no profit")
    if retained < 0.20 * earned:
        return not_applicable(
            key,
            name,
            school,
            "screen",
            f"Pays out {1 - retained / earned:.0%} of profit; the test needs material retained earnings",
        )
    gain = (ctx.p.price - start) * ctx.shares
    ratio = gain / retained
    return LensResult(
        key,
        name,
        school,
        "screen",
        True,
        value=ratio,
        verdict="passes" if ratio >= 1 else "fails",
        summary=(
            f"Each rupee kept back over 4 years created {ratio:.2f} rupees of market value "
            "(Buffett wants at least 1)."
        ),
        inputs={"retained_earnings": retained, "market_value_gain": gain, "start_price": start},
    )


def earnings_yield_vs_bonds(ctx: ValuationContext) -> LensResult:
    key, name, school = "earnings_yield", "Earnings yield vs 10-year G-sec", "Buffett / Fed model"
    if ctx.eps_ttm is None:
        return not_applicable(key, name, school, "metric", "EPS unavailable")
    ey = ctx.eps_ttm / ctx.p.price
    spread = ey - ctx.m.gsec_10y
    return LensResult(
        key,
        name,
        school,
        "metric",
        True,
        value=ey,
        verdict="beats bonds" if spread > 0 else "below bonds",
        summary=(
            f"Earnings yield {ey:.2%} vs G-sec {ctx.m.gsec_10y:.2%}: a {abs(spread):.2%} "
            f"{'premium' if spread > 0 else 'shortfall'} that growth must make up"
        ),
        inputs={
            "earnings_yield": ey,
            "gsec_10y": ctx.m.gsec_10y,
            "pe": ctx.p.price / ctx.eps_ttm if ctx.eps_ttm else None,
        },
    )


def roic_vs_wacc(ctx: ValuationContext) -> LensResult:
    key, name, school = (
        "roic",
        "Return on capital vs cost of capital (moat)",
        "Buffett / Munger / Mauboussin",
    )
    if ctx.f.is_financial:
        roes = roe_samples(ctx)
        if not roes:
            return not_applicable(key, name, school, "metric", "ROE unavailable")
        roe = statistics.mean(roes)
        return LensResult(
            key,
            name,
            school,
            "metric",
            True,
            value=roe,
            verdict="creates value" if roe > ctx.cost_of_equity else "destroys value",
            summary=f"ROE {roe:.1%} vs cost of equity {ctx.cost_of_equity:.1%}",
            inputs={"roe": roe, "cost_of_equity": ctx.cost_of_equity},
        )
    y = next((y for y in ctx.years if y.balance), None)
    if y is None or ctx.wacc is None:
        return not_applicable(key, name, school, "metric", "Needs a balance sheet and WACC")
    e, b = ebit(y.income), y.balance
    if (
        e is None
        or b.get("total_equity") is None
        or b.get("total_debt") is None
        or b.get("cash") is None
    ):
        return not_applicable(
            key, name, school, "metric", "Missing operating profit, equity, debt or cash"
        )
    invested = b["total_equity"] + b["total_debt"] - b["cash"]
    if invested <= 0:
        return not_applicable(
            key,
            name,
            school,
            "metric",
            "Invested capital not positive (cash exceeds debt + equity)",
        )
    roic = e * (1 - ctx.tax_rate) / invested
    return LensResult(
        key,
        name,
        school,
        "metric",
        True,
        value=roic,
        verdict="creates value" if roic > ctx.wacc else "destroys value",
        summary=f"After-tax ROIC {roic:.1%} vs WACC {ctx.wacc:.1%} (FY{y.fy_end.year % 100})",
        inputs={"roic": roic, "wacc": ctx.wacc, "invested_capital": invested},
    )


QUALITY_LENSES = (
    piotroski,
    altman,
    beneish,
    magic_formula,
    coffee_can,
    buffett_checks,
    retained_earnings_test,
    earnings_yield_vs_bonds,
    roic_vs_wacc,
)
