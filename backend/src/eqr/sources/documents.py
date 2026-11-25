"""Text of the company's own filings (results, call transcripts, acquisitions, orders),
downloaded from NSE and handed to the research agent as primary sources. Claude's own web
fetch times out on NSE's archive, so we fetch it here."""

from __future__ import annotations

import io
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pypdf import PdfReader

from eqr.cache import Cache
from eqr.nse_client import NseClient, NseError
from eqr.sources.announcements import Announcement

log = logging.getLogger(__name__)

# Most useful first. Call transcripts and results carry the substance.
PRIORITY = (
    "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Outcome of Board Meeting",
    "Financial Result Updates",
    "Acquisition",
    "Bagging/Receiving of orders/contracts",
    "Credit Rating",
    "Press Release",
    "Change in Management",
    "Disclosure under SEBI Takeover Regulations",
)
CHAR_LIMIT = {
    "Analysts/Institutional Investor Meet/Con. Call Updates": 30000,  # keep the analyst Q&A
    "Outcome of Board Meeting": 8000,
}
DEFAULT_CHAR_LIMIT = 3000
MIN_USEFUL_CHARS = 200
MAX_PAGES = 40


@dataclass(frozen=True)
class DocExcerpt:
    url: str
    category: str
    when: datetime
    text: str
    pages: int


MIN_PAGES_FOR_STRIP = 4
MIN_REPEATS = 3
PER_CATEGORY = 2
_CALL = "Analysts/Institutional Investor Meet/Con. Call Updates"


def strip_repeated_lines(pages: Sequence[str]) -> str:
    """Drop lines that repeat on most pages (letterheads, footers, page furniture).
    Only for longer documents: in a 2-3 page results filing, row labels such as
    "Total income" legitimately repeat across the standalone and consolidated tables."""
    page_lines = [[ln.strip() for ln in p.splitlines() if ln.strip()] for p in pages]
    if len(page_lines) >= MIN_PAGES_FOR_STRIP:
        counts = Counter(ln for lines in page_lines for ln in set(lines))
        cutoff = max(MIN_REPEATS, len(page_lines) // 2)
        page_lines = [[ln for ln in lines if counts[ln] < cutoff] for lines in page_lines]
    return "\n".join(ln for lines in page_lines for ln in lines)


def extract_pdf_text(data: bytes, max_pages: int = MAX_PAGES) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "") for p in reader.pages[:max_pages]]
    text = strip_repeated_lines(pages)
    # pypdf can emit lone surrogates, which break sqlite and UTF-8 stdin.
    return text.encode("utf-8", "replace").decode("utf-8"), len(reader.pages)


def _is_intimation(a: Announcement) -> bool:
    """Analyst-meet filings are mostly schedules; only transcripts and recordings carry content."""
    text = a.text.lower()
    return (
        a.category == _CALL
        and "transcript" not in text
        and ("intimation" in text or "schedule" in text)
    )


def select_documents(anns: Sequence[Announcement], max_docs: int = 6) -> list[Announcement]:
    """Best filings to read: by category priority, newest first, at most two per category,
    so one busy category (analyst-meet notices) cannot crowd out results and acquisitions."""
    rank = {cat: i for i, cat in enumerate(PRIORITY)}
    candidates = [
        a
        for a in anns
        if a.url and a.url.lower().endswith(".pdf") and a.category in rank and not _is_intimation(a)
    ]
    candidates.sort(key=lambda a: (rank[a.category], -a.when.timestamp()))
    picked: list[Announcement] = []
    seen: set[str] = set()
    per_category: Counter[str] = Counter()
    for a in candidates:
        if a.url in seen or per_category[a.category] >= PER_CATEGORY:
            continue
        seen.add(a.url)  # type: ignore[arg-type]
        per_category[a.category] += 1
        picked.append(a)
        if len(picked) == max_docs:
            break
    return sorted(picked, key=lambda a: a.when, reverse=True)


def fetch_documents(
    client: NseClient, cache: Cache, anns: Sequence[Announcement], max_docs: int = 6
) -> list[DocExcerpt]:
    out: list[DocExcerpt] = []
    for a in select_documents(anns, max_docs):
        assert a.url is not None
        key = f"doctext:{a.url}"
        cached = cache.get(key)
        if cached is not None:
            pages_str, _, text = cached.partition("\n")
            pages = int(pages_str or 0)
        else:
            try:
                text, pages = extract_pdf_text(client.get_bytes(a.url))
            except NseError as exc:
                log.warning("Could not download %s: %s", a.url, exc)
                continue
            except Exception as exc:  # pypdf raises many types; one bad PDF must not stop the run
                log.warning("Could not read %s: %s: %s", a.url, type(exc).__name__, exc)
                continue
            cache.set(key, f"{pages}\n{text}", ttl=None)  # filed documents do not change
        if len(text) < MIN_USEFUL_CHARS:
            continue  # scanned image or cover letter only
        limit = CHAR_LIMIT.get(a.category, DEFAULT_CHAR_LIMIT)
        out.append(DocExcerpt(a.url, a.category, a.when, text[:limit], pages))
    return out
