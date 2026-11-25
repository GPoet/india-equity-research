import pytest

from eqr.valuation.blend import blend
from eqr.valuation.models import LensResult


def v(key: str, value: float) -> LensResult:
    return LensResult(key, key, "x", "value", True, value=value)


def s(key: str, verdict: str, value: float = 0.0) -> LensResult:
    return LensResult(key, key, "x", "score", True, value=value, verdict=verdict)


CORE = [
    v("dcf", 100),
    v("owner_earnings", 110),
    v("epv", 80),
    v("graham_formula", 120),
    v("lynch", 105),
]


def test_mid_is_weighted_and_range_brackets_it() -> None:
    out = blend(CORE, price=100, financial=False, margin_of_safety=0.15)
    assert out.low <= out.mid <= out.high
    assert 95 < out.mid < 110


def test_signal_undervalued_when_price_below_range() -> None:
    assert blend(CORE, price=60, financial=False, margin_of_safety=0.15).signal == "Undervalued"


def test_signal_overvalued_when_price_above_range() -> None:
    assert blend(CORE, price=200, financial=False, margin_of_safety=0.15).signal == "Overvalued"


def test_signal_fair_inside_range() -> None:
    out = blend(CORE, price=100, financial=False, margin_of_safety=0.15)
    assert out.signal == "Fairly valued"


def test_margin_of_safety_buy_price() -> None:
    out = blend(CORE, price=100, financial=False, margin_of_safety=0.15)
    assert out.buy_below == pytest.approx(out.mid * 0.85)


def test_too_few_lenses_gives_no_signal() -> None:
    out = blend([v("graham_number", 100)], price=50, financial=False, margin_of_safety=0.15)
    assert out.signal == "Not enough data"
    assert out.mid is None


def test_red_flags_lower_confidence() -> None:
    clean = blend(CORE, price=100, financial=False, margin_of_safety=0.15)
    flagged = blend(
        CORE + [s("altman_z", "distress"), s("beneish_m", "possible manipulation")],
        price=100,
        financial=False,
        margin_of_safety=0.15,
    )
    assert len(flagged.red_flags) == 2
    order = ["low", "medium", "high"]
    assert order.index(flagged.confidence) < order.index(clean.confidence)


def test_financial_weights_ignore_dcf() -> None:
    lenses = [
        v("dcf", 1000),
        v("residual_income", 100),
        v("justified_pb", 90),
        v("graham_formula", 110),
    ]
    out = blend(lenses, price=100, financial=True, margin_of_safety=0.15)
    assert out.mid < 200


def test_agreeing_models_do_not_flip_signal_on_small_moves() -> None:
    same = [v(k, 100) for k in ("dcf", "owner_earnings", "epv", "graham_formula", "lynch")]
    assert blend(same, price=99, financial=False, margin_of_safety=0.15).signal == "Fairly valued"
    assert blend(same, price=101, financial=False, margin_of_safety=0.15).signal == "Fairly valued"
    assert blend(same, price=80, financial=False, margin_of_safety=0.15).signal == "Undervalued"
    assert blend(same, price=120, financial=False, margin_of_safety=0.15).signal == "Overvalued"


def test_negative_model_value_counts_and_flags() -> None:
    lenses = [
        v("dcf", -400),
        v("owner_earnings", 120),
        v("epv", 110),
        v("graham_formula", 100),
        v("lynch", 90),
    ]
    out = blend(lenses, price=300, financial=False, margin_of_safety=0.15)
    assert "dcf" in out.used  # kept, as zero
    assert any("negative" in f for f in out.red_flags)
    without = blend(lenses[1:], price=300, financial=False, margin_of_safety=0.15)
    assert out.mid < without.mid


def test_data_warnings_lower_confidence() -> None:
    clean = blend(CORE, price=100, financial=False, margin_of_safety=0.15)
    noisy = blend(CORE, price=100, financial=False, margin_of_safety=0.15, data_warnings=2)
    order = ["low", "medium", "high"]
    assert order.index(noisy.confidence) < order.index(clean.confidence)
