from datetime import date

from eqr.fundamentals import Fundamentals
from eqr.market import load_market_inputs
from eqr.sources.shareholding import Ownership, Shareholding
from eqr.valuation.context import PriceData, build_context
from eqr.valuation.lenses_quality import bank_asset_quality, promoter_and_pledge


def f(is_bank: bool = False, aq: dict | None = None) -> Fundamentals:
    return Fundamentals(
        "X",
        True,
        is_bank,
        is_bank,
        (),
        (),
        {},
        None,
        "none",
        {},
        None,
        100.0,
        1.0,
        "",
        asset_quality=aq or {},
    )


P = PriceData(100.0, "now", 1.0, "t", None, {}, {})


def sh(promoter=0.6, pledged=0.0, fpi=0.2, dii=0.1, day=date(2026, 9, 30)) -> Shareholding:
    return Shareholding(
        day, promoter, pledged, pledged, 1 - promoter, fpi, dii, 0.05, 0.03, 0.1, None
    )


def test_bank_asset_quality_strong() -> None:
    ctx = build_context(
        f(True, {"gnpa_pct": 0.0111, "nnpa_pct": 0.0037, "cet1_pct": 0.1887}),
        load_market_inputs(),
        P,
    )
    r = bank_asset_quality(ctx)
    assert r.applicable and r.verdict == "strong"
    assert "1.11%" in r.summary


def test_bank_asset_quality_weak() -> None:
    ctx = build_context(
        f(True, {"gnpa_pct": 0.07, "nnpa_pct": 0.025, "cet1_pct": 0.10}), load_market_inputs(), P
    )
    assert bank_asset_quality(ctx).verdict == "weak"


def test_bank_asset_quality_not_for_non_banks() -> None:
    assert not bank_asset_quality(build_context(f(False), load_market_inputs(), P)).applicable


def test_heavy_pledge_flagged() -> None:
    own = Ownership(sh(pledged=0.40), None, [(date(2026, 9, 30), 0.6)])
    r = promoter_and_pledge(build_context(f(), load_market_inputs(), P, ownership=own))
    assert r.verdict == "heavy pledge"


def test_promoter_selling_flagged() -> None:
    hist = [(date(2026, 9, 30), 0.55), (date(2026, 6, 30), 0.58), (date(2025, 9, 30), 0.62)]
    own = Ownership(sh(promoter=0.55), sh(promoter=0.62, day=date(2025, 9, 30)), hist)
    r = promoter_and_pledge(build_context(f(), load_market_inputs(), P, ownership=own))
    assert r.verdict == "promoter selling"
    assert "-7.0" in r.summary


def test_no_promoter_company() -> None:
    own = Ownership(sh(promoter=0.0), None, [(date(2026, 9, 30), 0.0)])
    r = promoter_and_pledge(build_context(f(), load_market_inputs(), P, ownership=own))
    assert r.verdict == "no promoter"


def test_clean_promoter() -> None:
    own = Ownership(
        sh(promoter=0.72, pledged=0.0079),
        None,
        [(date(2026, 9, 30), 0.72), (date(2025, 9, 30), 0.72)],
    )
    r = promoter_and_pledge(build_context(f(), load_market_inputs(), P, ownership=own))
    assert r.verdict == "clean"


def test_ownership_unavailable() -> None:
    assert not promoter_and_pledge(build_context(f(), load_market_inputs(), P)).applicable


def test_blend_flags_include_new_checks() -> None:
    from eqr.valuation.blend import RED_FLAG_VERDICTS

    assert "weak" in RED_FLAG_VERDICTS["bank_asset_quality"]
    assert {"heavy pledge", "promoter selling"} <= RED_FLAG_VERDICTS["promoter"]


def test_promoter_from_master_when_xbrl_lacks_it() -> None:
    latest = Shareholding(date(2026, 9, 30), None, None, None, 1.0, 0.5, 0.35, 0.2, 0.1, 0.1, None)
    own = Ownership(latest, None, [(date(2026, 9, 30), 0.0)])
    r = promoter_and_pledge(build_context(f(), load_market_inputs(), P, ownership=own))
    assert r.verdict == "no promoter"


def test_missing_pledge_data_is_not_clean() -> None:
    own = Ownership(
        sh(promoter=0.72, pledged=None),
        None,
        [(date(2026, 9, 30), 0.72), (date(2025, 9, 30), 0.72)],
    )
    r = promoter_and_pledge(build_context(f(), load_market_inputs(), P, ownership=own))
    assert r.verdict == "pledge data not in filing"
    assert "not in the filing" in r.summary


def test_bank_without_cet1_is_not_strong() -> None:
    ctx = build_context(f(True, {"gnpa_pct": 0.011, "nnpa_pct": 0.003}), load_market_inputs(), P)
    r = bank_asset_quality(ctx)
    assert r.verdict == "adequate" and "CET1 capital n/a" in r.summary
