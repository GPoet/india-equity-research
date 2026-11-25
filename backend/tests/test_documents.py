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
        f"{HEADER}\nCapex plan",
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


def test_short_filing_keeps_repeated_row_labels() -> None:
    # Standalone and consolidated tables repeat labels across 2-3 pages: keep them.
    pages = ["Total income 100\nProfit before tax 20", "Total income 300\nProfit before tax 60"]
    text = strip_repeated_lines(pages)
    assert text.count("Total income") == 2


def test_at_most_two_per_category_and_intimations_skipped() -> None:
    call = "Analysts/Institutional Investor Meet/Con. Call Updates"
    anns = [
        Announcement(
            "TCS",
            datetime(2026, 11, d),
            call,
            "Intimation of schedule of analyst meet",
            f"https://a/i{d}.pdf",
            None,
        )
        for d in range(1, 8)
    ]
    anns.append(
        Announcement(
            "TCS",
            datetime(2026, 10, 20),
            call,
            "Transcript of the earnings call",
            "https://a/t.pdf",
            None,
        )
    )
    anns.append(
        Announcement(
            "TCS",
            datetime(2026, 10, 9),
            "Outcome of Board Meeting",
            "Results",
            "https://a/r.pdf",
            None,
        )
    )
    picked = select_documents(anns, max_docs=6)
    urls = {a.url for a in picked}
    assert "https://a/t.pdf" in urls and "https://a/r.pdf" in urls
    assert sum(a.category == call for a in picked) <= 2
    assert not any("/i" in u for u in urls)
