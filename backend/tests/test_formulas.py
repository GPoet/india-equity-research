import math

import pytest

from eqr.valuation import formulas as fx


def test_two_stage_pv_flat_growth_matches_gordon() -> None:
    # With g1 == terminal, a 10-year PV + terminal value equals the Gordon value.
    pv = fx.two_stage_pv(base=100, g1=0.05, g_terminal=0.05, rate=0.10)
    assert pv == pytest.approx(100 * 1.05 / (0.10 - 0.05), rel=1e-9)


def test_two_stage_pv_rejects_rate_below_terminal() -> None:
    with pytest.raises(ValueError):
        fx.two_stage_pv(base=100, g1=0.1, g_terminal=0.08, rate=0.07)


def test_growth_path_fades_linearly() -> None:
    path = fx.growth_path(g1=0.20, g_terminal=0.05, years=10, high_years=5)
    assert path[:5] == [0.20] * 5
    assert path[-1] == pytest.approx(0.05)
    assert all(a >= b for a, b in zip(path, path[1:]))


def test_solve_growth_inverts_valuation() -> None:
    target = fx.two_stage_pv(base=100, g1=0.12, g_terminal=0.05, rate=0.11)
    g = fx.solve_growth(lambda g1: fx.two_stage_pv(100, g1, 0.05, 0.11), target)
    assert g == pytest.approx(0.12, abs=1e-6)


def test_graham_number() -> None:
    assert fx.graham_number(eps=10, bvps=100) == pytest.approx(math.sqrt(22.5 * 10 * 100))
    assert fx.graham_number(eps=-1, bvps=100) is None


def test_graham_formula_revised() -> None:
    # V = EPS x (8.5 + 2g) x 4.4 / Y, g and Y in percent
    assert fx.graham_formula(eps=10, growth_pct=10, aaa_yield_pct=8.0) == pytest.approx(
        10 * (8.5 + 20) * 4.4 / 8.0
    )


def test_lynch() -> None:
    assert fx.lynch_fair_value(eps=10, growth_pct=18) == 180
    assert fx.lynch_fair_value(eps=10, growth_pct=40) == 250  # fair P/E capped at 25
    assert fx.lynch_ratio(pe=20, growth_pct=15, dividend_yield_pct=1) == pytest.approx(0.8)


def test_rule1_sticker_price() -> None:
    eps, g, pe_hist = 10.0, 0.10, 30.0
    future_pe = min(2 * 10, 30)  # 20
    expected = eps * 1.10**10 * future_pe / 1.15**10
    assert fx.rule1_sticker(eps, g, pe_hist) == pytest.approx(expected)


def test_justified_pb() -> None:
    assert fx.justified_pb(roe=0.18, cost_of_equity=0.13, growth=0.05) == pytest.approx(0.13 / 0.08)


def test_residual_income_equals_book_when_roe_equals_ke() -> None:
    v = fx.residual_income_value(
        book=1000, roe=0.12, cost_of_equity=0.12, retention=0.6, g_terminal=0.05
    )
    assert v == pytest.approx(1000)


def test_residual_income_above_book_when_roe_beats_ke() -> None:
    v = fx.residual_income_value(
        book=1000, roe=0.18, cost_of_equity=0.12, retention=0.6, g_terminal=0.05
    )
    assert v > 1000


def test_altman_z_em() -> None:
    z = fx.altman_z_em(wc_ta=0.2, re_ta=0.3, ebit_ta=0.1, eq_tl=1.5)
    assert z == pytest.approx(3.25 + 6.56 * 0.2 + 3.26 * 0.3 + 6.72 * 0.1 + 1.05 * 1.5)


def test_beneish_neutral_company_scores_low() -> None:
    # Every index at 1 and zero accruals: M = -4.84 + sum of coefficients (minus SGAI, LVGI)
    m = fx.beneish_m(dsri=1, gmi=1, aqi=1, sgi=1, depi=1, sgai=1, tata=0, lvgi=1)
    assert m == pytest.approx(-4.84 + 0.92 + 0.528 + 0.404 + 0.892 + 0.115 - 0.172 - 0.327)
    assert m < -1.78


def test_cagr() -> None:
    assert fx.cagr(100, 121, 2) == pytest.approx(0.10)
    assert fx.cagr(-5, 10, 3) is None
    assert fx.cagr(100, 0, 3) is None
