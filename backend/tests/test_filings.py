import json
from datetime import date
from pathlib import Path

from eqr.sources.filings import FilingRef, merge_refs, parse_integrated, parse_legacy

FIX = Path(__file__).parent / "fixtures" / "nse"


def load(name: str):
    return json.loads((FIX / name).read_text())


def test_parse_integrated() -> None:
    refs = parse_integrated(load("tcs_integrated_financials.json"))
    latest = refs[0]
    assert latest.period_end == date(2026, 9, 30)
    assert latest.consolidated is True
    assert latest.xbrl_url.endswith(".xml")
    assert latest.source == "integrated"
    assert {r.consolidated for r in refs} == {True, False}


def test_parse_legacy() -> None:
    refs = parse_legacy(load("tcs_legacy_results.json"))
    assert refs
    assert all(r.source == "legacy" for r in refs)
    assert all(r.xbrl_url for r in refs)
    ends = [r.period_end for r in refs]
    assert ends == sorted(ends, reverse=True)
    assert ends[0] == date(2024, 12, 31)


def test_merge_prefers_integrated_and_sorts_newest_first() -> None:
    legacy = FilingRef(
        "TCS", date(2024, 12, 31), True, "https://x/legacy.xml", "09-Jan-2025", "legacy"
    )
    dup_legacy = FilingRef(
        "TCS", date(2025, 3, 31), True, "https://x/old.xml", "10-Apr-2025", "legacy"
    )
    integrated = FilingRef(
        "TCS", date(2025, 3, 31), True, "https://x/new.xml", "10-Apr-2025", "integrated"
    )
    merged = merge_refs([legacy, dup_legacy], [integrated])
    assert [r.period_end for r in merged] == [date(2025, 3, 31), date(2024, 12, 31)]
    assert merged[0].source == "integrated"


def test_merge_keeps_consolidated_and_standalone_separate() -> None:
    a = FilingRef("TCS", date(2025, 3, 31), True, "https://x/c.xml", "", "integrated")
    b = FilingRef("TCS", date(2025, 3, 31), False, "https://x/s.xml", "", "integrated")
    assert len(merge_refs([], [a, b])) == 2


def test_merge_keeps_latest_revision_within_a_source() -> None:
    original = FilingRef(
        "X",
        date(2025, 6, 30),
        True,
        "https://x/orig.xml",
        "10-Aug-2025 10:00:00",
        "integrated",
    )
    revised = FilingRef(
        "X",
        date(2025, 6, 30),
        True,
        "https://x/rev.xml",
        "02-Sep-2025 18:30:00",
        "integrated",
    )
    for order in ([original, revised], [revised, original]):
        merged = merge_refs([], order)
        assert len(merged) == 1
        assert merged[0].xbrl_url == "https://x/rev.xml"


def test_malformed_rows_are_skipped_not_fatal() -> None:
    payload = load("tcs_integrated_financials.json")
    rows = payload["data"]
    broken = dict(rows[0], qe_Date="not a date")
    refs = parse_integrated({"data": [broken, *rows[1:]]})
    assert len(refs) == len([r for r in rows if r.get("xbrl")]) - 1


def test_fetch_rejects_period_mismatch() -> None:
    from eqr.sources.filings import FilingsSource

    xml = (FIX / "tcs_q2fy27_consolidated.xml").read_text()

    class Client:
        def get_text(self, url, ttl, validate=None):
            return xml

    wrong = FilingRef("TCS", date(2026, 6, 30), True, "https://x/f.xml", "", "integrated")
    right = FilingRef("TCS", date(2026, 9, 30), True, "https://x/f.xml", "", "integrated")
    source = FilingsSource(Client())
    assert source.fetch(right).quarter is not None
    import pytest

    with pytest.raises(ValueError):
        source.fetch(wrong)
