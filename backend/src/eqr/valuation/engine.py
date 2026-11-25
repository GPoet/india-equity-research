"""Run every valuation lens for one company and assemble the report."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from eqr.fundamentals import Fundamentals
from eqr.market import MarketInputs
from eqr.sources.prices import history, quote, yahoo_symbol
from eqr.sources.shareholding import Ownership
from eqr.valuation.blend import Blend, blend
from eqr.valuation.context import PriceData, ValuationContext, build_context
from eqr.valuation.lenses_quality import QUALITY_LENSES
from eqr.valuation.lenses_value import VALUE_LENSES, reverse_dcf, reverse_residual_income
from eqr.valuation.models import LensResult

log = logging.getLogger(__name__)

INDEX = "^NSEI"  # Nifty 50
BETA_PERIOD = "2y"
DEFAULT_BETA = 1.0
BETA_RANGE = (0.5, 2.0)  # outside this, a 2-year beta is noise (thin trading, one-off moves)
# Context notes that mean the inputs themselves are shaky; each lowers confidence.
DATA_WARNING_MARKERS = (
    "mis-tagged",
    "could not confirm a bonus",
    "missing in the window",
    "Market inputs are",
)


def _blume(beta: float) -> float:
    """Blume adjustment: betas drift toward 1 over time."""
    return 0.67 * beta + 0.33


def estimate_beta(symbol: str) -> tuple[float, str]:
    try:
        stock = history(symbol, period=BETA_PERIOD, interval="1wk")["Close"].pct_change()
        index = (
            yf.Ticker(INDEX)
            .history(period=BETA_PERIOD, interval="1wk", auto_adjust=False)["Close"]
            .pct_change()
        )
        joined = pd.concat([stock, index], axis=1, join="inner").dropna()
        if len(joined) < 50:
            return DEFAULT_BETA, f"default {DEFAULT_BETA} (only {len(joined)} weekly returns)"
        raw = joined.iloc[:, 0].cov(joined.iloc[:, 1]) / joined.iloc[:, 1].var()
        adjusted = _blume(raw)
        bounded = min(max(adjusted, BETA_RANGE[0]), BETA_RANGE[1])
        note = "" if bounded == adjusted else f", capped from {adjusted:.2f}"
        return bounded, f"2y weekly vs Nifty 50, raw {raw:.2f}, Blume-adjusted{note}"
    except Exception as exc:  # network / Yahoo errors: fall back, but say so
        log.warning("Beta for %s failed: %s", symbol, exc)
        return DEFAULT_BETA, f"default {DEFAULT_BETA} (beta download failed: {type(exc).__name__})"


def _fy_of(day: date) -> date:
    return date(day.year if day.month <= 3 else day.year + 1, 3, 31)


def fetch_price_data(symbol: str, fy_ends: list[date], today: date) -> PriceData:
    q = quote(symbol)
    beta, beta_source = estimate_beta(symbol)
    hist = history(symbol, period="max")
    closes = hist["Close"]
    closes.index = [ts.date() for ts in closes.index]
    fy_prices: dict[date, float] = {}
    for fy in fy_ends:
        before = closes[[d <= fy for d in closes.index]]
        if not before.empty and (fy - before.index[-1]).days <= 10:
            fy_prices[fy] = float(before.iloc[-1])
    # Bonus/split factors come from the filings (fundamentals.share_action_factors) because
    # Yahoo's split *list* misses Indian bonus issues. Its price and dividend *history* is
    # adjusted for them (checked on Bajaj Finance's 2025 bonus + split), so it is used as is.
    ticker = yf.Ticker(yahoo_symbol(symbol))
    try:
        divs = ticker.dividends
        by_fy = {fy: 0.0 for fy in fy_ends}
        for ts, amount in divs.items():
            fy = _fy_of(ts.date())
            if fy in by_fy:
                by_fy[fy] += float(amount)
        cutoff = today - timedelta(days=365)
        dps_ttm: float | None = float(sum(a for ts, a in divs.items() if ts.date() > cutoff))
    except Exception as exc:
        log.warning("Dividends for %s failed: %s", symbol, exc)
        by_fy, dps_ttm = {}, None  # unknown, not zero
    return PriceData(
        price=q.price,
        as_of=q.as_of.isoformat(),
        beta=beta,
        beta_source=beta_source,
        dps_ttm=dps_ttm,
        dps_by_fy=by_fy,
        fy_end_prices=fy_prices,
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
    company_type = (
        "bank"
        if f.is_bank
        else "financial (NBFC / insurer / holding)"
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
