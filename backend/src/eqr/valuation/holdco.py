"""Holding companies (Bajaj Holdings, Tata Investment, ...): their value is the market value
of stakes in other companies, so the usual formulas misstate it. Detected from the filings
because NSE labels them simply "Finance"."""

from __future__ import annotations

from eqr.fundamentals import Fundamentals, owners_profit

ASSOCIATE_SHARE = 0.5  # half or more of profit comes from associates and joint ventures
INVESTMENT_SHARE = 0.7  # 70%+ of assets are investments


def is_holding_company(f: Fundamentals) -> tuple[bool, str]:
    if not f.is_financial or f.is_bank:
        return False, ""
    income = f.ttm if f.ttm.get("pat") is not None else (f.years[0].income if f.years else {})
    pat, assoc = owners_profit(income), income.get("share_of_associates")
    if pat and pat > 0 and assoc is not None and assoc / pat >= ASSOCIATE_SHARE:
        return (
            True,
            f"{assoc / pat:.0%} of profit is its share of associates' and joint ventures' profit",
        )
    b = f.latest_balance or (f.years[0].balance if f.years else {})
    assets = b.get("total_assets")
    held = sum(
        v for v in (b.get("investments"), b.get("equity_method_investments")) if v is not None
    )
    if assets and held / assets >= INVESTMENT_SHARE:
        return True, f"{held / assets:.0%} of assets are investments in other companies"
    return False, ""
