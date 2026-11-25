from datetime import datetime

from eqr.sources.announcements import Announcement
from eqr.sources.documents import select_documents, strip_repeated_lines

HEADER = "9th Floor Nirmal Building Nariman Point Mumbai 400 021"


def ann(
    cat: str, day: int, url: str | None = "https://nsearchives.nseindia.com/x.pdf"
) -> Announcement:
    return Announcement("TCS", datetime(2026, 11, day), cat, "t", url, None)


def test_strip_repeated_lines_removes_letterhead() -> None:
    pages = [
        f"{HEADER}\nRevenue grew 5%\nPage 1",
        f"{HEADER}\nMargins held\nPage 2",
        f"{HEADER}\nOutlook steady",
    ]
    text = strip_repeated_lines(pages)
    assert HEADER not in text
    assert "Revenue grew 5%" in text and "Outlook steady" in text


def test_strip_keeps_single_page() -> None:
    assert "only page" in strip_repeated_lines([f"{HEADER}\nonly page"])


def test_select_prioritises_results_and_transcripts() -> None:
    anns = [
        ann("Updates", 20, "https://a/u.pdf"),
        ann("Outcome of Board Meeting", 10, "https://a/r.pdf"),
        ann("Analysts/Institutional Investor Meet/Con. Call Updates", 12, "https://a/c.pdf"),
        ann("Acquisition", 15, "https://a/q.pdf"),
        ann("Press Release", 18, None),
    ]
    picked = select_documents(anns, max_docs=3)
    cats = [a.category for a in picked]
    assert "Updates" not in cats
    assert len(picked) == 3
    assert all(a.url for a in picked)


def test_select_skips_duplicate_urls() -> None:
    anns = [
        ann("Acquisition", 15, "https://a/q.pdf"),
        ann("Outcome of Board Meeting", 14, "https://a/q.pdf"),
    ]
    assert len(select_documents(anns, max_docs=5)) == 1
