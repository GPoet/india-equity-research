"""Research agent: Claude with web search reads the news, regulation and filings around a
company and returns a sourced, structured report. Numbers for valuation never come from
here; this layer explains, finds catalysts and flags risks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from eqr.llm.claude_cli import LlmError, LlmProvider
from eqr.research.schema import ResearchReport, clean_report, cli_schema
from eqr.sources.announcements import Announcement
from eqr.sources.documents import DocExcerpt

MAX_ANNOUNCEMENTS = 40
TEXT_LIMIT = 300
TOOLS = ("WebSearch", "WebFetch")
NEWS_WINDOW_DAYS = 120

SYSTEM = """You are an equity research analyst covering companies listed on India's NSE and BSE.
This is a personal research tool for one investor; valuation numbers are computed separately,
so do not give buy/sell/hold calls or price targets.

Rules:
- Use web search and fetch. Prefer primary sources: the company's NSE/BSE filings and investor
  presentations, regulators (sebi.gov.in, rbi.org.in, pib.gov.in, egazette.gov.in, ministry
  sites, GST Council, DGFT, IRDAI, CERC, TRAI), then established Indian business press
  (Economic Times, Mint, Business Standard, Moneycontrol, BusinessLine, Reuters, Bloomberg).
- Every catalyst and regulation needs the URL of a page you actually saw. If you cannot
  source something, leave it out or list it under data_gaps. Never invent numbers, dates or URLs.
- Dates as YYYY-MM-DD. Money in rupees crore (cr) unless the source uses another currency.
- Social media chatter, stock-tip sites and unverified forums are not sources.
- Be specific about direction: why each item is a tailwind or headwind for THIS company.
"""


@dataclass(frozen=True)
class CompanyBrief:
    symbol: str
    name: str
    industry: str | None
    facts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchRun:
    report: ResearchReport
    dropped: dict[str, int]
    meta: dict[str, Any]


def _announcement_lines(items: Sequence[Announcement]) -> list[str]:
    lines = []
    for a in items[:MAX_ANNOUNCEMENTS]:
        text = " ".join(a.text.split())[:TEXT_LIMIT]
        link = f" <{a.url}>" if a.url else ""
        lines.append(f"- {a.when:%Y-%m-%d} [{a.category}] {text}{link}")
    return lines


def _document_block(documents: Sequence[DocExcerpt]) -> str:
    if not documents:
        return "- (none could be read)"
    parts = []
    for d in documents:
        parts.append(
            f'<document url="{d.url}" type="{d.category}" date="{d.when:%Y-%m-%d}" pages="{d.pages}">\n'
            f"{d.text}\n</document>"
        )
    return "\n".join(parts)


def build_prompt(
    brief: CompanyBrief,
    announcements: Sequence[Announcement],
    today: date,
    documents: Sequence[DocExcerpt] = (),
) -> str:
    facts = "\n".join(f"- {k}: {v}" for k, v in brief.facts.items()) or "- (none)"
    anns = "\n".join(_announcement_lines(announcements)) or "- (none in the window)"
    docs = _document_block(documents)
    return f"""Today is {today.isoformat()}.

Company: {brief.name} (NSE: {brief.symbol})
NSE industry: {brief.industry or "unknown"}

Facts already computed from its filings (do not recompute; use for context):
{facts}

Its own NSE announcements in the last {NEWS_WINDOW_DAYS} days (primary source, newest first):
{anns}

Text of its key recent filings, downloaded from NSE for you (primary source; NSE's archive
times out for web fetch, so use this text and cite the document url). Text may be truncated:
{docs}

The filings give the company's own account. You must still search the web: news coverage
and what others say about the company, regulation and policy, peers' latest results, and the
macro backdrop (RBI policy, rates, demand). Do several searches; do not rely on the filings alone.
Where a filing and a press report disagree, prefer the filing and say so.

Research and report:
1. Latest quarterly results and what management said on the earnings call (guidance, demand,
   margins, order book or deal wins).
2. Material news in the last {NEWS_WINDOW_DAYS} days: orders, acquisitions, management changes,
   litigation, rating actions, promoter stake changes or pledges, capacity additions.
3. Regulation and policy, Indian and foreign, recent or upcoming, that helps or hurts this company
   or its sector: SEBI/RBI rules, budget and tax changes, GST, PLI schemes, tariffs and trade
   actions, sector regulators. Give the effective date where one exists.
4. Sector conditions and how peers are doing; a stance on the sector (bullish/neutral/bearish).
5. Upcoming dated events (results date, AGM, record dates, policy meetings, regulatory deadlines).
6. Key risks, a bull case and a bear case, and what would change the view.

Return only the structured report."""


def run_research(
    provider: LlmProvider,
    brief: CompanyBrief,
    announcements: Sequence[Announcement],
    today: date,
    model: str = "sonnet",
    effort: str | None = "medium",
    timeout: int = 900,
    documents: Sequence[DocExcerpt] = (),
) -> ResearchRun:
    prompt = build_prompt(brief, announcements, today, documents)
    result = provider.run(
        prompt,
        cli_schema(),
        system=SYSTEM,
        tools=TOOLS,
        model=model,
        effort=effort,
        timeout=timeout,
    )
    try:
        report = ResearchReport.model_validate(result.data)
    except ValidationError as exc:
        raise LlmError(
            "invalid_output", f"Research output failed validation: {exc.error_count()} errors"
        ) from exc
    cleaned, dropped = clean_report(report, today)
    meta = {
        "as_of": today.isoformat(),
        "model": model,
        "effort": effort,
        "cost_usd_equivalent": result.cost_usd,
        "duration_ms": result.duration_ms,
        "num_turns": result.num_turns,
        "documents_given": len(documents),
        "prompt_chars": len(prompt),
        "announcements_given": min(len(announcements), MAX_ANNOUNCEMENTS),
    }
    return ResearchRun(report=cleaned, dropped=dropped, meta=meta)
