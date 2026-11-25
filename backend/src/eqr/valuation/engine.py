"""Run every valuation lens for one company and assemble the report."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Any

import pandas as pd
import yfinance as yf

from eqr.fundamentals import Fundamentals
from eqr.market import MarketInputs
from eqr.sources.prices import history, quote, yahoo_symbol
from eqr.sources.shareholding import Ownership
from eqr.valuation.blend import Blend, blend
from eqr.valuation.context import PriceData, ValuationContext, build_context
from eqr.valuation.holdco import is_holding_company
from eqr.valuation.lenses_quality import QUALITY_LENSES
from eqr.valuation.lenses_value import VALUE_LENSES, reverse_dcf, reverse_residual_income
from eqr.valuation.models import LensResult
from eqr.valuation.pricedata import MarketSeries, price_data_as_of

log = logging.getLogger(__name__)

INDEX = "^NSEI"  # Nifty 50
# Context notes that mean the inputs themselves are shaky; each lowers confidence.
DATA_WARNING_MARKERS = (
    "mis-tagged",
    "could not confirm a bonus",
    "missing in the window",
    "Market inputs are",
)


def _dated(s: pd.Series) -> pd.Series:
    out = s.dropna().copy()
    out.index = [ts.date() for ts in out.index]
    return out


def fetch_nifty() -> pd.Series:
    return _dated(yf.Ticker(INDEX).history(period="max", auto_adjust=False)["Close"])


def fetch_market_series(
    symbol: str, index: pd.Series | None = None, yahoo: str | None = None
) -> MarketSeries:
    """Full daily history for the stock and the Nifty 50, plus dividends (None if Yahoo fails).
    Bonus/split factors come from the filings (fundamentals.share_action_factors) because
    Yahoo's split *list* misses Indian bonus issues; its price and dividend *history* is
    adjusted for them (checked on Bajaj Finance's 2025 bonus + split), so it is used as is."""
    closes = _dated(history(symbol, period="max", yahoo=yahoo)["Close"])
    index = fetch_nifty() if index is None else index  # pass it in when scanning many stocks
    try:
        divs: pd.Series | None = yf.Ticker(yahoo or yahoo_symbol(symbol)).dividends
        divs = _dated(divs) if divs is not None else None
    except Exception as exc:  # noqa: BLE001 - dividends are optional; None means unknown
        log.warning("Dividends for %s failed: %s", symbol, exc)
        divs = None
    return MarketSeries(closes, index, divs)


def fetch_price_data(symbol: str, fy_ends: list[date], today: date) -> PriceData:
    q = quote(symbol)
    return price_data_as_of(
        fetch_market_series(symbol), fy_ends, today, price=q.price, price_as_of=q.as_of.isoformat()
    )


@dataclass(frozen=True)
class ValuationReport:
    symbol: str
    price: float
    price_as_of: str
    company_type: str
    lenses: tuple[LensResult, ...]
    implied_growth: LensResult
    result: Blend
    assumptions: dict[str, Any]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "price_as_of": self.price_as_of,
            "company_type": self.company_type,
            "lenses": [r.to_dict() for r in self.lenses],
            "implied_growth": self.implied_growth.to_dict(),
            "result": asdict(self.result),
            "assumptions": self.assumptions,
            "warnings": list(self.warnings),
        }


def _run(lens: Any, ctx: ValuationContext) -> LensResult:
    try:
        return lens(ctx)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as exc:  # bad data
        name = getattr(lens, "__name__", "lens")
        log.warning("Lens %s failed: %s", name, exc)
        return LensResult(
            name,
            name.replace("_", " "),
            "",
            "value",
            False,
            reason=f"Failed on this company's data: {type(exc).__name__}: {exc}",
        )


def value_company(
    f: Fundamentals,
    market: MarketInputs,
    prices: PriceData,
    today: date,
    ownership: Ownership | None = None,
) -> ValuationReport:
    ctx = build_context(f, market, prices, ownership)
    lenses = tuple(_run(lens, ctx) for lens in (*VALUE_LENSES, *QUALITY_LENSES))
    implied = _run(reverse_residual_income if f.is_financial else reverse_dcf, ctx)
    warnings = [w for w in (market.staleness_warning(today),) if w]
    data_warnings = sum(
        any(marker in note for marker in DATA_WARNING_MARKERS) for note in (*ctx.notes, *warnings)
    )
    result = blend(
        list(lenses), prices.price, f.is_financial, market.margin_of_safety, data_warnings
    )
    if f.is_bank and not f.asset_quality:
        warnings.append(
            "Bank asset-quality ratios (GNPA/NNPA/CET1) could not be read from the standalone filing"
        )
    if ownership is None:
        warnings.append("Shareholding pattern unavailable: promoter and pledge check skipped")
    holdco, holdco_why = is_holding_company(f)
    if holdco:
        warnings.append(
            f"Holding company ({holdco_why}). Its value is the market value of its stakes, so a "
            "sum-of-the-parts at those companies' share prices is the right method; the formula "
            "values here do not capture it."
        )
        result = replace(
            result,
            confidence="low",
            reasons=(
                *result.reasons,
                "Holding company: formula values understate or misstate its stakes",
            ),
        )
    company_type = (
        "holding company"
        if holdco
        else "bank"
        if f.is_bank
        else "financial (NBFC / insurer)"
        if f.is_financial
        else "operating company"
    )
    assumptions = {
        "cost_of_equity": ctx.cost_of_equity,
        "wacc": ctx.wacc,
        "cost_of_debt": ctx.cost_of_debt,
        "beta": prices.beta,
        "beta_source": prices.beta_source,
        "tax_rate": ctx.tax_rate,
        "growth": ctx.growth,
        "growth_inputs": ctx.growth_inputs,
        "risk_free_inr": market.risk_free_inr,
        "gsec_10y": market.gsec_10y,
        "equity_risk_premium": market.equity_risk_premium,
        "terminal_growth": market.terminal_growth,
        "market_inputs_as_of": market.as_of.isoformat(),
        "market_sources": market.sources,
        "shares": ctx.shares,
        "eps_ttm": ctx.eps_ttm,
        "bvps": ctx.bvps,
        "market_cap": ctx.market_cap,
        "debt": ctx.debt,
        "cash_like": ctx.cash_like,
        "ttm_end": f.ttm_end.isoformat() if f.ttm_end else None,
        "ttm_cash_basis": f.ttm_cash_basis,
        "basis": "consolidated" if f.consolidated else "standalone",
        "years_of_history": len(f.years),
        "notes": list(ctx.notes),
    }
    return ValuationReport(
        symbol=f.symbol,
        price=prices.price,
        price_as_of=prices.as_of,
        company_type=company_type,
        lenses=lenses,
        implied_growth=implied,
        result=result,
        assumptions=assumptions,
        warnings=tuple(warnings),
    )
