from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eqr.sectors.analysis import excess_correlations, sector_scores
from eqr.sectors.catalog import LINKS, SECTORS, sector_for_industry
from eqr.sources.indices import index_close_url, parse_index_closes

FIX = Path(__file__).parent / "fixtures" / "nse" / "ind_close_all_23112026.csv"


def test_url() -> None:
    assert index_close_url(date(2026, 11, 23)).endswith(
        "/content/indices/ind_close_all_23112026.csv"
    )


def test_parse_index_file() -> None:
    rows = {r.name: r for r in parse_index_closes(FIX.read_text())}
    n50 = rows["Nifty 50"]
    assert n50.day == date(2026, 11, 23)
    assert n50.close == 25349.65
    assert n50.pe == 20.65
    assert rows["Nifty India Defence Equal Weight"].close == 8348.59  # open shown as "-"


def test_catalog_indices_exist_in_nse_file() -> None:
    names = {r.name for r in parse_index_closes(FIX.read_text())}
    missing = [s.index for s in SECTORS.values() if s.index not in names]
    assert missing == []
    for key, links in LINKS.items():
        assert key in SECTORS
        assert all(other in SECTORS for other, _ in links)


@pytest.mark.parametrize(
    ("industry", "name", "sector"),
    [
        ("Computers - Software", "Tata Consultancy Services Limited", "it"),
        ("Banks", "HDFC Bank Limited", "private_bank"),
        ("Banks", "State Bank of India", "psu_bank"),
        ("Pharmaceuticals", "Sun Pharmaceutical Industries Limited", "pharma"),
        ("Iron & Steel", "Tata Steel Limited", "metal"),
        ("Cement & Cement Products", "UltraTech Cement Limited", "cement"),
        ("Power Generation/Distribution", "NTPC Limited", "power"),
        ("Edible Oil", "Adani Wilmar Limited", "fmcg"),
        ("Refineries", "Reliance Industries Limited", "oil_gas"),
    ],
)
def test_industry_mapping(industry: str, name: str, sector: str) -> None:
    assert sector_for_industry(industry, name) == sector


def test_unknown_industry_is_none() -> None:
    assert sector_for_industry("Something Odd", "X Ltd") is None


def _frame() -> pd.DataFrame:
    days = pd.bdate_range(end=pd.Timestamp("2026-11-23"), periods=300)
    t = np.arange(len(days))
    rng = np.random.default_rng(1)
    market = 100 * np.exp(0.0003 * t + rng.normal(0, 0.008, len(t)).cumsum() * 0.1)
    noise = rng.normal(0, 0.004, len(t)).cumsum()
    return pd.DataFrame(
        {
            "Nifty 50": market,
            "Strong": market * np.exp(0.0015 * t),
            "Weak": market * np.exp(-0.0015 * t),
            "Twin": market * np.exp(0.0015 * t + noise * 0.05),
        },
        index=days,
    )


def test_scores_rank_strong_above_weak() -> None:
    scores = sector_scores(_frame(), benchmark="Nifty 50")
    assert scores.loc["Strong", "stance"] == "bullish"
    assert scores.loc["Weak", "stance"] == "bearish"
    assert scores.loc["Strong", "rs_6m"] > 0 > scores.loc["Weak", "rs_6m"]


def test_excess_correlation_finds_twin() -> None:
    corr = excess_correlations(_frame(), benchmark="Nifty 50")
    assert corr.loc["Strong", "Twin"] > corr.loc["Strong", "Weak"]


def test_scores_need_enough_history() -> None:
    short = _frame().iloc[-30:]
    scores = sector_scores(short, benchmark="Nifty 50")
    assert scores["rs_6m"].isna().all()
    assert (scores["stance"] == "insufficient history").all()


def test_sector_picture_links_and_comovement() -> None:
    from eqr.sectors.view import sector_picture

    frame = _frame().rename(
        columns={
            "Strong": "Nifty IT",
            "Twin": "Nifty India Internet",
            "Weak": "Nifty Telecommunications",
        }
    )
    pe = frame * 0 + 20.0
    pic = sector_picture("it", frame, pe)
    assert pic.sector is not None and pic.sector.stance == "bullish"
    keys = {r.stat.key for r in pic.related}
    assert {"internet", "telecom"} <= keys  # both are economic links of IT
    internet = next(r for r in pic.related if r.stat.key == "internet")
    assert internet.correlation is not None and internet.correlation > 0.3
    assert pic.strongest[0].key in {"it", "internet"}


def test_unknown_sector_notes() -> None:
    from eqr.sectors.view import sector_picture

    frame = _frame().rename(columns={"Strong": "Nifty IT"})
    pic = sector_picture(None, frame, frame * 0 + 20.0)
    assert pic.sector is None


def test_short_history_index_gets_partial_stance() -> None:
    frame = _frame()
    frame.loc[frame.index[:-111], "Strong"] = np.nan  # index launched ~5 months ago
    scores = sector_scores(frame, benchmark="Nifty 50")
    row = scores.loc["Strong"]
    assert np.isnan(row["rs_6m"])
    assert row["stance"] == "bullish (short history)"
    assert row["history_days"] == 111
