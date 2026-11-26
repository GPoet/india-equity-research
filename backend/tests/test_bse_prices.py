from datetime import date

import pytest

from eqr.sources.bse_prices import adjust, parse_actions, parse_price_csv, share_factor

CSV = """Date,Open Price,High Price,Low Price,Close Price,WAP,No.of Shares,No. of Trades,Total Turnover (Rs.),Deliverable Quantity,% Deli. Qty to Traded Qty,Spread High-Low,Spread Close-Open
17-June-2025,943.90,943.90,917.65,922.90,925.4,328099,1174,1,,,1,1
16-June-2025,954.50,957.30,925.05,937.75,937.4,544250,10,1,,,1,1
13-June-2025,9259.80,9360.60,9155.00,9334.15,9284.1,3,1,1,,,1,1
"""

ACTIONS = {
    "Table": [{"purpose_name": "Final Dividend", "BCRD_from": "30 May 2025", "Amount": 44.0}],
    "Table1": [
        {"XTYPE": "Bonus", "BCRD_FROM": "16 Jun 2025", "VALUE": "issue 4:1"},
        {"XTYPE": "Bonus", "BCRD_FROM": "08 Sep 2016", "VALUE": "issue 1:1"},
    ],
    "Table2": [
        {"Ex_date": "16 Jun 2025", "purpose": "Bonus issue 4:1"},
        {"Ex_date": "16 Jun 2025", "purpose": "Stock  Split From Rs.2/- to Rs.1/-"},
        {"Ex_date": "30 May 2025", "purpose": "Final Dividend", "Details": "44.00"},
    ],
}


@pytest.mark.parametrize(
    ("text", "f"),
    [
        ("Bonus issue 4:1", 5.0),
        ("issue 1:1", 2.0),
        ("Stock  Split From Rs.2/- to Rs.1/-", 2.0),
        ("Stock Split From Rs.10/- to Re.1/-", 10.0),
        ("Final Dividend", None),
    ],
)
def test_share_factor(text, f) -> None:
    assert share_factor(text) == f


def test_parse_actions_dedupes_and_combines() -> None:
    factors, divs = parse_actions(ACTIONS)
    assert factors == {date(2025, 6, 16): pytest.approx(10.0), date(2016, 9, 8): pytest.approx(2.0)}
    assert divs == {date(2025, 5, 30): 44.0}


def test_adjust_puts_history_on_todays_basis() -> None:
    px = parse_price_csv(CSV)
    assert px.index[0] == date(2025, 6, 13) and px.loc[date(2025, 6, 13), "close"] == pytest.approx(
        9334.15
    )
    closes, divs = adjust(px["close"], {date(2025, 6, 16): 10.0}, {date(2025, 5, 30): 44.0})
    assert closes[date(2025, 6, 13)] == pytest.approx(933.415)
    assert closes[date(2025, 6, 16)] == pytest.approx(937.75)
    assert divs[date(2025, 5, 30)] == pytest.approx(4.4)
