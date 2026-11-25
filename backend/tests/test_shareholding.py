from datetime import date
from pathlib import Path

import pytest

from eqr.sources.shareholding import Shareholding, parse_shp, promoter_history

FIX = Path(__file__).parent / "fixtures" / "nse" / "adanient_shp.xml"


@pytest.fixture(scope="module")
def shp() -> Shareholding:
    return parse_shp(FIX.read_text())


def test_as_of(shp) -> None:
    assert shp.as_of == date(2026, 9, 30)


def test_promoter_and_pledge(shp) -> None:
    assert shp.promoter_pct == pytest.approx(0.7197)
    assert shp.pledged_of_promoter == pytest.approx(7_700_000 / 974_234_554)
    assert shp.encumbered_of_promoter == pytest.approx(0.0079, abs=1e-4)


def test_institutions(shp) -> None:
    assert shp.fpi_pct == pytest.approx(0.1066)
    assert shp.dii_pct == pytest.approx(0.1062)
    assert shp.mf_pct == pytest.approx(0.0662)
    assert shp.public_pct == pytest.approx(0.2803)
    assert shp.retail_pct == pytest.approx(0.0254 + 0.0023)


def test_bad_xml_raises() -> None:
    with pytest.raises(ValueError):
        parse_shp("<html>nope</html>")


def test_promoter_history_from_master() -> None:
    rows = [
        {"date": "30-SEP-2026", "pr_and_prgrp": "71.97", "xbrl": "a.xml"},
        {"date": "30-JUN-2026", "pr_and_prgrp": "72.50", "xbrl": "b.xml"},
        {"date": "30-SEP-2025", "pr_and_prgrp": "74.00", "xbrl": "c.xml"},
        {"date": "bad", "pr_and_prgrp": "x"},
    ]
    hist = promoter_history(rows)
    assert hist[0] == (date(2026, 9, 30), pytest.approx(0.7197))
    assert len(hist) == 3
