from datetime import date

import pytest

from eqr.sources.corporate_actions import parse_factor, share_factors


@pytest.mark.parametrize(
    ("subject", "factor"),
    [
        ("Bonus 4:1", 5.0),
        ("Bonus 1:1", 2.0),
        ("Bonus 3:2", 2.5),
        ("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share", 2.0),
        ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", 5.0),
        ("Dividend - Rs 12 Per Share", None),
        ("Rights 1:5 @ Premium Rs 100/-", None),
    ],
)
def test_parse_factor(subject, factor) -> None:
    assert parse_factor(subject) == factor


def test_share_factors_combine_same_day_actions() -> None:
    rows = [
        {
            "symbol": "BAJFINANCE",
            "series": "EQ",
            "exDate": "16-Jun-2025",
            "subject": "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share",
        },
        {"symbol": "BAJFINANCE", "series": "EQ", "exDate": "16-Jun-2025", "subject": "Bonus 4:1"},
        {
            "symbol": "TCS",
            "series": "EQ",
            "exDate": "16-Jun-2025",
            "subject": "Dividend - Rs 11 Per Share",
        },
    ]
    assert share_factors(rows) == {("BAJFINANCE", date(2025, 6, 16)): pytest.approx(10.0)}
