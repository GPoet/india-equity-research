from datetime import date

import pytest

from eqr.fundamentals import build_fundamentals
from eqr.sources.filings import FilingRef
from eqr.xbrl import Filing, Period


def q(start: date, end: date, **values: float) -> Period:
    return Period(start=start, end=end, values=values)


def bs(day: date, **values: float) -> Period:
    return Period(start=None, end=day, values=values)


def filing(
    quarter: Period,
    ytd: Period | None = None,
    sheet: Period | None = None,
    prev: Period | None = None,
) -> Filing:
    periods = tuple(p for p in (quarter, ytd, sheet, prev) if p is not None)
    return Filing(
        latest_period=quarter,
        quarter=quarter,
        year_to_date=ytd,
        balance_sheet=sheet,
        previous_balance_sheet=prev,
        periods=periods,
    )


def ref(end: date) -> FilingRef:
    return FilingRef("X", end, True, f"https://x/{end}.xml", "", "integrated")


QTRS = [
    (date(2025, 4, 1), date(2025, 6, 30)),
    (date(2025, 7, 1), date(2025, 9, 30)),
    (date(2025, 10, 1), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 3, 31)),
    (date(2026, 4, 1), date(2026, 6, 30)),
    (date(2026, 7, 1), date(2026, 9, 30)),
]
BASE = {"PaidUpValueOfEquityShareCapital": 1000.0, "FaceValueOfEquityShareCapital": 10.0}


def series(revenues: list[float], with_fy_ytd: bool = True):
    out = []
    for (start, end), rev in zip(QTRS, revenues):
        quarter = q(start, end, RevenueFromOperations=rev, ProfitLossForPeriod=rev / 10, **BASE)
        ytd = sheet = prev = None
        if end == date(2026, 3, 31) and with_fy_ytd:
            ytd = q(
                date(2025, 4, 1),
                end,
                RevenueFromOperations=sum(revenues[:4]) + 1,
                ProfitLossForPeriod=40.0,
                CashFlowsFromUsedInOperatingActivities=500.0,
                **BASE,
            )
            sheet = bs(end, Assets=9000.0, EquityAttributableToOwnersOfParent=5000.0)
        if end == date(2025, 9, 30):
            ytd = q(date(2025, 4, 1), end, CashFlowsFromUsedInOperatingActivities=200.0)
        if end == date(2026, 9, 30):
            ytd = q(date(2026, 4, 1), end, CashFlowsFromUsedInOperatingActivities=260.0)
            sheet = bs(end, Assets=9500.0, EquityAttributableToOwnersOfParent=5300.0)
            prev = bs(date(2026, 3, 31), Assets=9000.0, EquityAttributableToOwnersOfParent=5000.0)
        out.append((ref(end), filing(quarter, ytd, sheet, prev)))
    return out


def test_annual_prefers_reported_full_year() -> None:
    f = build_fundamentals("X", series([100, 110, 120, 130, 140, 150]))
    fy26 = f.year(date(2026, 3, 31))
    assert fy26 is not None
    assert fy26.income["revenue"] == 461  # reported 12-month figure, not the quarter sum
    assert fy26.income_source == "annual"
    assert fy26.balance["total_assets"] == 9000


def test_annual_falls_back_to_sum_of_quarters() -> None:
    f = build_fundamentals("X", series([100, 110, 120, 130, 140, 150], with_fy_ytd=False))
    fy26 = f.year(date(2026, 3, 31))
    assert fy26.income["revenue"] == 460
    assert fy26.income_source == "sum_of_quarters"
    assert fy26.income["cfo"] is None  # cash flow is not reported quarterly
    # March balance sheet recovered from the later half-year filing
    assert fy26.balance["total_assets"] == 9000


def test_ttm_sums_last_four_quarters() -> None:
    f = build_fundamentals("X", series([100, 110, 120, 130, 140, 150]))
    assert f.ttm_end == date(2026, 9, 30)
    assert f.ttm["revenue"] == 120 + 130 + 140 + 150


def test_ttm_cash_flow_rolls_forward_half_year() -> None:
    f = build_fundamentals("X", series([100, 110, 120, 130, 140, 150]))
    # FY26 CFO 500 + H1 FY27 260 - H1 FY26 200
    assert f.ttm["cfo"] == 560
    assert f.ttm_cash_basis == "FY + YTD rolled forward"


def test_ttm_none_when_quarters_not_consecutive() -> None:
    rows = series([100, 110, 120, 130, 140, 150])
    del rows[3]  # drop the March quarter
    f = build_fundamentals("X", rows)
    assert f.ttm["revenue"] is None


def test_shares_and_latest_balance() -> None:
    f = build_fundamentals("X", series([100, 110, 120, 130, 140, 150]))
    assert f.shares == 100  # paid-up 1000 / face value 10
    assert f.latest_balance_date == date(2026, 9, 30)
    assert f.latest_balance["equity_owners"] == 5300


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        build_fundamentals("X", [])


def test_shares_cross_checked_against_eps() -> None:
    # A filing with garbage share-capital fields (seen in BAJAJHLDNG): profit / EPS wins.
    rows = series([100, 110, 120, 130, 140, 150])
    ref_last, last = rows[-1]
    bad = dict(last.quarter.values)
    bad.update(
        PaidUpValueOfEquityShareCapital=100.0,
        FaceValueOfEquityShareCapital=111.29,
        ProfitLossForPeriod=15.0,
        BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations=0.15,
    )
    quarter = q(last.quarter.start, last.quarter.end, **bad)
    rows[-1] = (
        ref_last,
        filing(quarter, last.year_to_date, last.balance_sheet, last.previous_balance_sheet),
    )
    f = build_fundamentals("X", rows)
    assert f.shares == pytest.approx(100.0)
    assert "profit / EPS" in f.shares_note


def test_year_sheet_falls_back_to_capital_plus_reserves() -> None:
    from eqr.fundamentals import _year_sheet

    assert _year_sheet({}, {"paid_up_capital": 5.0, "reserves_ex_revaluation": 95.0}) == {
        "equity_owners": 100.0
    }
    assert _year_sheet({}, {"paid_up_capital": 5.0}) == {}  # partial: not a total
    real = {"equity_owners": 99.0}
    assert _year_sheet(real, {"paid_up_capital": 5.0, "reserves_ex_revaluation": 95.0}) is real


def test_load_fundamentals_skips_unreadable_filings(monkeypatch) -> None:
    from types import SimpleNamespace

    from eqr import fundamentals as fm

    good = SimpleNamespace(name="good", consolidated=True, period_end=None)
    bad = SimpleNamespace(name="bad", consolidated=True, period_end=None)

    class Src:
        def list(self, symbol):
            return [good, bad]

        def fetch(self, ref):
            if ref is bad:
                raise ValueError("filing covers another period")
            return "filing"

    seen = {}

    def fake_build(symbol, pairs):
        seen["pairs"] = pairs

        class F:
            is_bank = False

        return F()

    monkeypatch.setattr(fm, "build_fundamentals", fake_build)
    fm.load_fundamentals(Src(), "X")
    assert seen["pairs"] == [(good, "filing")]


def test_main_basis_prefers_consolidated_only_with_enough_history() -> None:
    from datetime import date
    from types import SimpleNamespace

    from eqr.fundamentals import main_basis

    def refs(n_cons, n_stand):
        out = [
            SimpleNamespace(consolidated=True, period_end=date(2020 + i // 4, 3 * (i % 4) + 1, 1))
            for i in range(n_cons)
        ]
        out += [
            SimpleNamespace(consolidated=False, period_end=date(2020 + i // 4, 3 * (i % 4) + 1, 1))
            for i in range(n_stand)
        ]
        return out

    assert main_basis(refs(9, 38)) is False  # sparse consolidated history (ABB on BSE)
    assert main_basis(refs(30, 32)) is True
    assert main_basis(refs(5, 0)) is True
    assert main_basis(refs(0, 5)) is False
