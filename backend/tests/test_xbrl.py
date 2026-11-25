from datetime import date
from pathlib import Path

import pytest

from eqr.xbrl import parse_filing

FIXTURE = Path(__file__).parent / "fixtures" / "nse" / "tcs_q2fy27_consolidated.xml"
CRORE = 10_000_000


@pytest.fixture(scope="module")
def filing():
    return parse_filing(FIXTURE.read_text())


def test_quarter_period(filing) -> None:
    q = filing.quarter
    assert q.start == date(2026, 7, 1)
    assert q.end == date(2026, 9, 30)


def test_quarter_income_statement(filing) -> None:
    q = filing.quarter
    assert q.get("RevenueFromOperations") == 731_880_000_000
    assert q.get("ProfitLossForPeriod") == 139_340_000_000
    assert q.get("ProfitOrLossAttributableToOwnersOfParent") == 138_840_000_000
    assert q.get("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations") == 38.37


def test_year_to_date_period(filing) -> None:
    ytd = filing.year_to_date
    assert ytd is not None
    assert ytd.start == date(2026, 4, 1)
    assert ytd.get("RevenueFromOperations") == 1_454_630_000_000
    assert ytd.get("CashFlowsFromUsedInOperatingActivities") == 258_010_000_000


def test_balance_sheet_instant(filing) -> None:
    bs = filing.balance_sheet
    assert bs is not None
    assert bs.end == date(2026, 9, 30)
    assert bs.get("Assets") == 1_907_820_000_000
    assert bs.get("EquityAttributableToOwnersOfParent") == 1_189_860_000_000


def test_missing_concept_is_none_not_zero(filing) -> None:
    assert filing.quarter.get("ConceptThatDoesNotExist") is None


def test_dimensional_facts_excluded_from_totals(filing) -> None:
    # Segment rows carry dimensions; totals must come from the plain context only.
    assert filing.quarter.get("RevenueFromOperations") == 731_880_000_000


def test_key_metrics_derived(filing) -> None:
    m = filing.quarter_metrics()
    assert m["revenue"] == 731_880_000_000
    assert m["pat"] == 139_340_000_000
    # EBITDA = PBT + finance costs + D&A - other income, so it must exceed PBT here.
    assert m["ebitda"] is not None
    assert m["ebitda"] > m["pbt"]
    assert round(m["ebitda"] / CRORE) > 0


def test_unparseable_input_raises() -> None:
    with pytest.raises(ValueError):
        parse_filing("not xml at all")


BANK = Path(__file__).parent / "fixtures" / "nse" / "hdfcbank_q2fy27_consolidated.xml"
NBFC = Path(__file__).parent / "fixtures" / "nse" / "bajfinance_q2fy27_consolidated.xml"


@pytest.fixture(scope="module")
def bank():
    return parse_filing(BANK.read_text())


@pytest.fixture(scope="module")
def nbfc():
    return parse_filing(NBFC.read_text())


def test_bank_detected(bank, filing, nbfc) -> None:
    assert bank.is_bank is True
    assert filing.is_bank is False
    assert nbfc.is_bank is False  # NBFCs file the Ind-AS (non-bank) taxonomy


def test_bank_income_metrics(bank) -> None:
    m = bank.quarter_metrics()
    assert m["interest_earned"] == 951_316_300_000
    assert m["interest_expended"] == 506_674_300_000
    assert m["nii"] == 951_316_300_000 - 506_674_300_000
    assert m["ppop"] == 328_715_400_000
    assert m["provisions"] == 42_090_000_000
    assert m["pat"] == 207_000_300_000
    assert m["eps_basic"] == 13.43


def test_bank_zero_ratios_are_missing_not_zero(bank) -> None:
    # Consolidated bank filings tag GNPA/NNPA/CET1/ROA as 0.0; those are blanks.
    m = bank.quarter_metrics()
    assert m["gnpa_pct"] is None
    assert m["nnpa_pct"] is None
    assert m["cet1_pct"] is None


def test_bank_balance_sheet(bank) -> None:
    b = bank.balance_metrics()
    assert b["advances"] == 33_160_575_400_000
    assert b["deposits"] == 33_241_463_600_000
    assert b["borrowings"] == 5_941_435_400_000
    assert b["total_assets"] == 51_658_415_800_000
    assert b["equity_owners"] is not None  # capital + reserves


def test_nbfc_total_debt_includes_debt_securities(nbfc) -> None:
    b = nbfc.balance_metrics()
    assert b["total_debt"] == 1_866_723_900_000 + 2_448_309_500_000 + 7_248_200_000
    assert b["deposits"] == 697_537_000_000


LEGACY_UNDECLARED = (
    Path(__file__).parent / "fixtures" / "nse" / "tcs_q1fy23_legacy_consolidated.xml"
)


def test_legacy_file_with_undeclared_contexts() -> None:
    # 2018-2023 legacy files reference OneD/OneI without declaring them; the period
    # comes from the DateOfStart/EndOfReportingPeriod facts instead.
    f = parse_filing(LEGACY_UNDECLARED.read_text())
    assert f.quarter is not None
    assert f.quarter.start == date(2022, 4, 1)
    assert f.quarter.end == date(2022, 6, 30)
    m = f.quarter_metrics()
    assert m["revenue"] == 527_580_000_000
    assert m["pat"] == 95_190_000_000


LEGACY_BANK = Path(__file__).parent / "fixtures" / "nse" / "hdfcbank_q4fy23_legacy_consolidated.xml"


def test_legacy_bank_file_period_from_sibling_contexts() -> None:
    f = parse_filing(LEGACY_BANK.read_text())
    assert f.is_bank
    assert f.quarter is not None
    assert (f.quarter.start, f.quarter.end) == (date(2023, 1, 1), date(2023, 3, 31))
    assert f.quarter_metrics()["pat"] == 126_340_100_000
    assert f.year_to_date is not None
    assert f.year_to_date.start == date(2022, 4, 1)
    assert f.year_to_date_metrics()["pat"] == 461_487_000_000


def test_equity_owners_from_parts_only_when_both_known() -> None:
    from datetime import date

    from eqr.xbrl import Period, _balance

    def p(values):
        return Period(None, date(2023, 9, 30), values)

    got = _balance(p({"EquityShareCapital": 1.2, "OtherEquity": 597.5, "Equity": 598.7}))
    assert got["equity_owners"] == pytest.approx(598.7)
    assert _balance(p({"OtherEquity": 597.5}))["equity_owners"] is None
