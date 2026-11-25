from datetime import date

import pytest

from eqr.fundamentals import Fundamentals, YearRow
from eqr.market import load_market_inputs
from eqr.valuation.context import PriceData, build_context


def year(fy: int, revenue: float, pat: float, shares: float) -> YearRow:
    income = {
        "revenue": revenue,
        "pat": pat,
        "pat_owners": pat,
        "eps_basic": pat / shares,
        "tax": pat * 0.25,
        "pbt": pat * 1.25,
    }
    return YearRow(date(fy, 3, 31), income, "annual", {})


def fundamentals(years: list[YearRow]) -> Fundamentals:
    return Fundamentals(
        "X", True, False, False, (), tuple(years), {}, None, "none", {}, None, 100.0, 1.0, ""
    )


def prices(splits: dict[date, float] | None = None) -> PriceData:
    return PriceData(100.0, "now", 1.0, "test", None, {}, {}, splits or {})


def test_growth_is_lower_of_revenue_and_profit_per_share() -> None:
    ys = [year(2026 - i, 100 * 1.10 ** (5 - i), 10 * 1.20 ** (5 - i), 100) for i in range(6)]
    ctx = build_context(fundamentals(ys), load_market_inputs(), prices())
    assert ctx.growth == pytest.approx(0.10, abs=1e-6)


def test_dilution_removed_from_growth() -> None:
    # Revenue and profit jump 1.36x via a merger paid in shares (HDFC 2023): per-share growth ~0.
    ys = [
        year(2026 - i, 136 if i < 3 else 100, 13.6 if i < 3 else 10, 136 if i < 3 else 100)
        for i in range(6)
    ]
    ctx = build_context(fundamentals(ys), load_market_inputs(), prices())
    assert ctx.growth == pytest.approx(0.0, abs=1e-6)


def test_bonus_issue_does_not_look_like_dilution() -> None:
    # 1:1 bonus in FY24: share count doubles, but split factor restores comparability.
    ys = [
        year(2026 - i, 100 * 1.10 ** (5 - i), 10 * 1.10 ** (5 - i), 200 if i < 3 else 100)
        for i in range(6)
    ]
    ctx = build_context(fundamentals(ys), load_market_inputs(), prices())  # detected from filings
    assert ctx.growth == pytest.approx(0.10, abs=1e-6)


def test_cyclical_profit_uses_revenue_growth_only() -> None:
    pats = [50, 40, -5, 8, 30, 20]  # a loss inside the window
    ys = [year(2026 - i, 100 * 1.06 ** (5 - i), pats[i], 100) for i in range(6)]
    ctx = build_context(fundamentals(ys), load_market_inputs(), prices())
    assert ctx.growth == pytest.approx(0.06, abs=1e-6)
    assert any("cyclical" in n for n in ctx.notes)


def test_bonus_plus_split_detected() -> None:
    # Bajaj Finance 2025: 4:1 bonus + 2:1 split = 10x shares, no money raised.
    ys = [
        year(2026 - i, 100 * 1.15 ** (5 - i), 10 * 1.15 ** (5 - i), 1000 if i == 0 else 100)
        for i in range(6)
    ]
    ctx = build_context(fundamentals(ys), load_market_inputs(), prices())
    assert ctx.growth == pytest.approx(0.15, abs=1e-6)


def test_fast_steady_growth_is_not_cyclical() -> None:
    ys = [year(2026 - i, 100 * 1.25 ** (5 - i), 10 * 1.25 ** (5 - i), 100) for i in range(6)]
    ctx = build_context(fundamentals(ys), load_market_inputs(), prices())
    assert not any("cyclical" in n for n in ctx.notes)


def test_merger_ratio_is_dilution_not_bonus() -> None:
    from eqr.fundamentals import share_action_factors

    ys = [year(2026 - i, 100, 10, 136 if i < 2 else 100) for i in range(4)]
    assert all(v == 1.0 for v in share_action_factors(tuple(ys)).values())


def test_split_from_face_value_plus_small_merger() -> None:
    # Tata Steel: 10:1 split (face value 10 -> 1) plus ~2% merger shares, across a missing year.
    from eqr.fundamentals import share_action_factors

    def row(fy: int, shares: float, face: float) -> YearRow:
        income = {
            "revenue": 100.0,
            "pat": 10.0,
            "paid_up_capital": shares * face,
            "face_value": face,
            "eps_basic": 10.0 / shares,
        }
        return YearRow(date(fy, 3, 31), income, "annual", {})

    ys = (row(2024, 1247, 1.0), row(2022, 122.1, 10.0))
    assert share_action_factors(ys)[date(2022, 3, 31)] == pytest.approx(10.0)


def test_zero_owners_profit_with_real_profit_is_missing() -> None:
    from eqr.fundamentals import owners_profit

    assert owners_profit({"pat": 4420.0, "pat_owners": 0.0}) == 4420.0
    assert owners_profit({"pat": 0.0, "pat_owners": 0.0}) == 0.0
    assert owners_profit({"pat": 100.0, "pat_owners": 95.0}) == 95.0
