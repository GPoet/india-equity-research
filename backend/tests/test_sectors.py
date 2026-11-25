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
