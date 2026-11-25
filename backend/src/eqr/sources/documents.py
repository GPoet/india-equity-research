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
from pypdf.errors import PdfReadError

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


def strip_repeated_lines(pages: Sequence[str]) -> str:
    """Drop lines that repeat on most pages (letterheads, footers, page furniture)."""
    page_lines = [[ln.strip() for ln in p.splitlines() if ln.strip()] for p in pages]
    if len(page_lines) > 1:
        counts = Counter(ln for lines in page_lines for ln in set(lines))
        cutoff = max(2, len(page_lines) // 2)
        page_lines = [[ln for ln in lines if counts[ln] < cutoff] for lines in page_lines]
    return "\n".join(ln for lines in page_lines for ln in lines)


def extract_pdf_text(data: bytes, max_pages: int = MAX_PAGES) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "") for p in reader.pages[:max_pages]]
    return strip_repeated_lines(pages), len(reader.pages)


def select_documents(anns: Sequence[Announcement], max_docs: int = 6) -> list[Announcement]:
    rank = {cat: i for i, cat in enumerate(PRIORITY)}
    candidates = [
        a for a in anns if a.url and a.url.lower().endswith(".pdf") and a.category in rank
    ]
    candidates.sort(key=lambda a: (rank[a.category], -a.when.timestamp()))
    picked, seen = [], set()
    for a in candidates:
        if a.url in seen:
            continue
        seen.add(a.url)
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
            except (NseError, PdfReadError, ValueError) as exc:
                log.warning("Could not read %s: %s", a.url, exc)
                continue
            cache.set(key, f"{pages}\n{text}", ttl=None)  # filed documents do not change
        if len(text) < MIN_USEFUL_CHARS:
            continue  # scanned image or cover letter only
        limit = CHAR_LIMIT.get(a.category, DEFAULT_CHAR_LIMIT)
        out.append(DocExcerpt(a.url, a.category, a.when, text[:limit], pages))
    return out
