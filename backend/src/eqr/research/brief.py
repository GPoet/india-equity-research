"""Turn computed fundamentals and valuation into the facts block given to the research agent."""

from __future__ import annotations

from eqr.fundamentals import Fundamentals, owners_profit
from eqr.research.agent import CompanyBrief
from eqr.valuation.engine import ValuationReport

CRORE = 1e7


def _cr(x: float | None) -> str:
    return "n/a" if x is None else f"{x / CRORE:,.0f} cr"


def _yoy(now: float | None, then: float | None) -> str:
    if now is None or then is None or then <= 0:
        return ""
    return f" ({now / then - 1:+.0%} YoY)"


def build_brief(
    name: str, industry: str | None, f: Fundamentals, v: ValuationReport
) -> CompanyBrief:
    facts: dict[str, str] = {}
    if f.quarters:
        q = f.quarters[0]
        prior = next(
            (p for p in f.quarters if (q.period_end - p.period_end).days in range(360, 370)), None
        )
        top_key = "total_income" if f.is_bank else "revenue"
        top, top_then = q.income.get(top_key), prior.income.get(top_key) if prior else None
        pat, pat_then = owners_profit(q.income), owners_profit(prior.income) if prior else None
        label = "Total income" if f.is_bank else "Revenue"
        facts[f"Latest quarter (ended {q.period_end})"] = (
            f"{label} {_cr(top)}{_yoy(top, top_then)}, profit attributable to shareholders "
            f"{_cr(pat)}{_yoy(pat, pat_then)} (excludes minority partners' share)"
        )
    a, r = v.assumptions, v.result
    if a.get("market_cap"):
        facts["Market cap"] = _cr(a["market_cap"])
    if a.get("eps_ttm"):
        facts["P/E (trailing)"] = f"{v.price / a['eps_ttm']:.1f}"
    facts["Company type"] = v.company_type
    if r.mid is not None:
        facts["Our valuation"] = (
            f"{r.signal} (fair value range {r.low:,.0f}-{r.high:,.0f}, mid {r.mid:,.0f}, "
            f"price {v.price:,.0f}, confidence {r.confidence})"
        )
    if v.implied_growth.applicable:
        facts["Priced in"] = v.implied_growth.summary
    return CompanyBrief(symbol=f.symbol, name=name, industry=industry, facts=facts)
