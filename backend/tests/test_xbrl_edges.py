"""Edge cases found in review, built from minimal synthetic XBRL."""

from __future__ import annotations

import math

import pytest

from eqr.xbrl import parse_filing

NS = "http://www.xbrl.org/2003/instance"


def ctx_duration(cid: str, start: str, end: str) -> str:
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        f"</xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate>"
        f"<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>"
    )


def ctx_instant(cid: str, day: str) -> str:
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        f"</xbrli:entity><xbrli:period><xbrli:instant>{day}</xbrli:instant></xbrli:period></xbrli:context>"
    )


def doc(contexts: list[str], facts: list[tuple[str, str, str]]) -> str:
    body = "".join(contexts) + "".join(
        f'<in-capmkt:{name} contextRef="{ref}" unitRef="INR" decimals="0">{value}</in-capmkt:{name}>'
        for name, ref, value in facts
    )
    return (
        f'<xbrli:xbrl xmlns:xbrli="{NS}" xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/in-capmkt">'
        f"{body}</xbrli:xbrl>"
    )


Q = ctx_duration("Q", "2026-07-01", "2026-09-30")
H = ctx_duration("H", "2026-04-01", "2026-09-30")
BS = ctx_instant("I", "2026-09-30")

PNL = [
    ("RevenueFromOperations", "Q", "1000"),
    ("ProfitBeforeExceptionalItemsAndTax", "Q", "100"),
    ("FinanceCosts", "Q", "10"),
    ("DepreciationDepletionAndAmortisationExpense", "Q", "20"),
    ("OtherIncome", "Q", "5"),
]


def test_ebitda_normal() -> None:
    f = parse_filing(doc([Q], PNL))
    assert f.quarter_metrics()["ebitda"] == 100 + 10 + 20 - 5


def test_ebitda_none_when_other_income_missing() -> None:
    facts = [x for x in PNL if x[0] != "OtherIncome"]
    assert parse_filing(doc([Q], facts)).quarter_metrics()["ebitda"] is None


def test_ebitda_none_without_pre_exceptional_pbt() -> None:
    facts = [x for x in PNL if x[0] != "ProfitBeforeExceptionalItemsAndTax"] + [
        ("ProfitBeforeTax", "Q", "90")
    ]
    assert parse_filing(doc([Q], facts)).quarter_metrics()["ebitda"] is None


def test_ebitda_none_for_ind_as_financials() -> None:
    facts = PNL + [
        ("InterestEarned", "Q", "900"),
        ("ImpairmentOnFinancialInstruments", "Q", "30"),
    ]
    f = parse_filing(doc([Q], facts))
    assert f.is_financial is True
    assert f.is_bank is False
    assert f.quarter_metrics()["ebitda"] is None


def test_nine_month_only_is_not_a_quarter() -> None:
    nine = ctx_duration("N", "2026-04-01", "2026-12-31")
    f = parse_filing(doc([nine], [("RevenueFromOperations", "N", "900")]))
    assert f.quarter is None
    assert f.quarter_metrics() == {}
    assert f.latest_period.days > 200


def test_half_year_context_is_year_to_date() -> None:
    f = parse_filing(doc([Q, H], PNL + [("RevenueFromOperations", "H", "1900")]))
    assert f.quarter is not None and f.quarter.get("RevenueFromOperations") == 1000
    assert f.year_to_date is not None and f.year_to_date.get("RevenueFromOperations") == 1900


def test_stray_instant_is_not_the_balance_sheet() -> None:
    stray = ctx_instant("S", "2026-11-10")
    f = parse_filing(
        doc(
            [Q, BS, stray],
            PNL + [("Assets", "I", "5000"), ("EquityShareCapital", "S", "10")],
        )
    )
    assert f.balance_sheet is not None
    assert f.balance_sheet.get("Assets") == 5000


def test_no_balance_sheet_at_quarter_end_gives_none() -> None:
    march = ctx_instant("M", "2026-03-31")
    f = parse_filing(doc([Q, march], PNL + [("Assets", "M", "4000")]))
    assert f.balance_sheet is None
    assert f.previous_balance_sheet is not None
    assert f.balance_metrics() == {}


def test_partial_debt_is_not_a_total() -> None:
    f = parse_filing(
        doc([Q, BS], PNL + [("Assets", "I", "5000"), ("BorrowingsCurrent", "I", "50")])
    )
    assert f.balance_metrics()["total_debt"] is None


def test_full_debt_is_summed() -> None:
    facts = PNL + [
        ("Assets", "I", "5000"),
        ("BorrowingsCurrent", "I", "50"),
        ("BorrowingsNoncurrent", "I", "70"),
    ]
    assert parse_filing(doc([Q, BS], facts)).balance_metrics()["total_debt"] == 120


BANK_PNL = [
    ("InterestEarned", "Q", "900"),
    ("InterestExpended", "Q", "500"),
    ("ProfitLossForThePeriod", "Q", "100"),
]


def test_bank_equity_needs_capital_and_reserves() -> None:
    f = parse_filing(doc([Q, BS], BANK_PNL + [("Assets", "I", "9000"), ("Capital", "I", "76")]))
    assert f.is_bank
    assert f.balance_metrics()["equity_owners"] is None


def test_bank_genuine_zero_net_npa_kept() -> None:
    facts = BANK_PNL + [
        ("PercentageOfGrossNpa", "Q", "0.8"),
        ("PercentageOfNpa", "Q", "0"),
    ]
    m = parse_filing(doc([Q], facts)).quarter_metrics()
    assert m["gnpa_pct"] == 0.8
    assert m["nnpa_pct"] == 0.0


def test_bank_all_zero_ratios_are_blanks() -> None:
    facts = BANK_PNL + [
        ("PercentageOfGrossNpa", "Q", "0"),
        ("PercentageOfNpa", "Q", "0"),
        ("CET1Ratio", "Q", "0"),
    ]
    m = parse_filing(doc([Q], facts)).quarter_metrics()
    assert m["gnpa_pct"] is None and m["nnpa_pct"] is None and m["cet1_pct"] is None


def test_bank_detected_from_year_to_date_context() -> None:
    facts = [
        ("ProfitLossForThePeriod", "Q", "100"),
        ("InterestEarned", "H", "1800"),
        ("InterestExpended", "H", "1000"),
    ]
    assert parse_filing(doc([Q, H], facts)).is_bank is True


@pytest.mark.parametrize("bad", ["NaN", "inf", "-inf"])
def test_non_finite_values_dropped(bad: str) -> None:
    f = parse_filing(doc([Q], PNL + [("TaxExpense", "Q", bad)]))
    value = f.quarter.get("TaxExpense")
    assert value is None or math.isfinite(value)
    assert value is None


def test_undeclared_contexts_never_share_a_period() -> None:
    # Two undeclared contexts whose only evidence points at the same period must not be
    # merged into one bucket (year-to-date figures would overwrite quarterly ones).
    seg_q = (
        '<xbrli:context id="OneSegD"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        "</xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate>"
        "<xbrli:endDate>2023-03-31</xbrli:endDate></xbrli:period>"
        '<xbrli:scenario><xbrldi:explicitMember xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'dimension="a:B">a:C</xbrldi:explicitMember></xbrli:scenario></xbrli:context>'
    )
    seg_y = seg_q.replace("OneSegD", "TwoSegD")
    facts = [("ProfitLossForPeriod", "OneD", "100"), ("ProfitLossForPeriod", "TwoD", "400")]
    f = parse_filing(doc([seg_q, seg_y], facts))
    assert f.quarter is not None
    assert f.quarter.get("ProfitLossForPeriod") == 100
    assert len([p for p in f.periods if p.start is not None]) == 1


def test_dimensional_contexts_never_inferred_as_plain() -> None:
    seg = (
        '<xbrli:context id="OneSegD"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        "</xbrli:entity><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate>"
        "<xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>"
        '<xbrli:scenario><xbrldi:explicitMember xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        'dimension="a:B">a:C</xbrldi:explicitMember></xbrli:scenario></xbrli:context>'
    )
    facts = PNL + [("RevenueFromOperations", "OneSegD", "123")]
    f = parse_filing(doc([Q, seg], facts))
    assert f.quarter.get("RevenueFromOperations") == 1000
