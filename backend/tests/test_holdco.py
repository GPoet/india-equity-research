from datetime import date

from eqr.fundamentals import Fundamentals, YearRow
from eqr.valuation.holdco import is_holding_company


def f(ttm: dict, balance: dict, financial: bool = True) -> Fundamentals:
    year = YearRow(date(2026, 3, 31), ttm, "annual", balance)
    return Fundamentals(
        "X", True, False, financial, (), (year,), ttm, None, "none", balance, None, 100.0, 1.0, ""
    )


def test_profit_mostly_from_associates() -> None:
    yes, why = is_holding_company(
        f({"pat": 2000.0, "share_of_associates": 1700.0}, {"total_assets": 100.0})
    )
    assert yes and "associates" in why


def test_assets_mostly_investments() -> None:
    yes, why = is_holding_company(f({"pat": 100.0}, {"total_assets": 1000.0, "investments": 800.0}))
    assert yes and "investments" in why


def test_ordinary_lender_is_not_a_holdco() -> None:
    yes, _ = is_holding_company(
        f(
            {"pat": 100.0, "share_of_associates": 2.0},
            {"total_assets": 1000.0, "investments": 150.0, "loans": 800.0},
        )
    )
    assert not yes


def test_operating_company_never_holdco() -> None:
    yes, _ = is_holding_company(
        f({"pat": 100.0, "share_of_associates": 90.0}, {"total_assets": 100.0}, financial=False)
    )
    assert not yes
