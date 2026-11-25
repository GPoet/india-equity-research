"""What the research agent must return, and the sourcing rules applied afterwards.

Rule from the plan: every factual item carries a source URL; unsourced items are dropped,
not trusted. News cannot be dated in the future. Regulations may take effect in the future.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["tailwind", "headwind", "mixed"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Catalyst(_Strict):
    title: str
    detail: str = Field(
        description="What happened and why it matters for this company, 1-3 sentences"
    )
    kind: Literal["company", "sector", "regulation", "macro", "competitor"]
    direction: Direction
    materiality: int = Field(ge=1, le=5, description="1 = trivia, 5 = changes the investment case")
    horizon: Literal["near", "medium", "long"] = Field(
        description="near < 6 months, medium 6-24, long 24+"
    )
    date: str | None = Field(description="Date it happened or was reported, YYYY-MM-DD")
    source_url: str
    source_name: str


class Regulation(_Strict):
    title: str
    regulator: str = Field(
        description="SEBI, RBI, a ministry, GST Council, DGFT, CERC, IRDAI, a foreign regulator..."
    )
    status: Literal["proposed", "draft", "notified", "effective", "court_case"]
    announced_date: str | None = Field(description="YYYY-MM-DD")
    effective_date: str | None = Field(description="YYYY-MM-DD, may be in the future")
    direction: Direction
    scope: Literal["company", "sector", "economy"]
    detail: str
    source_url: str
    source_name: str


class Risk(_Strict):
    title: str
    detail: str
    severity: int = Field(ge=1, le=5)
    source_url: str | None = Field(
        description="Source if the risk rests on a reported fact; null if it is analysis"
    )


class Event(_Strict):
    date: str | None = Field(description="YYYY-MM-DD, or null if only the month is known")
    event: str
    source_url: str | None


class SectorView(_Strict):
    sector: str
    stance: Literal["bullish", "neutral", "bearish"]
    reasoning: str
    source_urls: list[str]


class ResearchReport(_Strict):
    summary: str = Field(description="3-5 sentence overview of what matters now")
    business: str = Field(description="What the company does, main segments and revenue mix")
    latest_results: str = Field(
        description="Latest quarter: growth, margins, management guidance from the call"
    )
    catalysts: list[Catalyst]
    regulation: list[Regulation]
    risks: list[Risk]
    events: list[Event] = Field(
        description="Upcoming dated events: results, AGM, record dates, policy meetings"
    )
    sector_view: SectorView
    bull_case: str
    bear_case: str
    what_would_change_view: list[str]
    data_gaps: list[str] = Field(description="Things you looked for and could not verify")


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def cli_schema() -> dict[str, Any]:
    """JSON Schema for `claude --json-schema`, with references inlined."""
    return _inline_refs(ResearchReport.model_json_schema())


def _is_url(value: str | None) -> bool:
    return bool(value) and value.startswith(("https://", "http://")) and "." in value  # type: ignore[union-attr]


def _url_keys(url: str) -> tuple[str, str]:
    """Comparable forms of a URL: (host+path+query, host+path), ignoring scheme, www,
    trailing slashes and fragments."""
    u = url.strip().split("#")[0]
    u = u.split("://", 1)[-1]
    if u.lower().startswith("www."):
        u = u[4:]
    host, _, rest = u.partition("/")
    path, _, query = rest.partition("?")
    base = f"{host.lower()}/{path.rstrip('/')}"
    return (f"{base}?{query}" if query else base), base


def url_verifier(allowed: set[str] | frozenset[str] | None):
    """Returns a predicate: was this URL actually seen (tool results, fetched pages, our NSE
    documents)? With allowed=None, any well-formed URL passes."""
    if allowed is None:
        return _is_url
    keys = {k for u in allowed for k in _url_keys(u)}

    def seen(url: str | None) -> bool:
        if not _is_url(url):
            return False
        full, base = _url_keys(url)  # type: ignore[arg-type]
        return full in keys or base in keys

    return seen


def _parse(day: str | None) -> date | None:
    try:
        return date.fromisoformat(day) if day else None
    except ValueError:
        return None


def clean_report(
    report: ResearchReport, today: date, allowed_urls: set[str] | frozenset[str] | None = None
) -> tuple[ResearchReport, dict[str, int]]:
    """Apply the sourcing rules. Returns the cleaned report and counts of what was dropped.

    allowed_urls: URLs the model's tools actually returned or fetched, plus the NSE documents
    we supplied. When given, items citing any other URL are dropped as unverified: the model
    may have invented them.
    """
    dropped = {
        "unsourced": 0,
        "unverified_url": 0,
        "future_dated": 0,
        "duplicate": 0,
        "stale_event": 0,
    }
    seen_url = url_verifier(allowed_urls)
    seen_items: set[tuple[str, str]] = set()

    def keep(url: str | None, title: str, happened: str | None) -> bool:
        if not _is_url(url):
            dropped["unsourced"] += 1
            return False
        if not seen_url(url):
            dropped["unverified_url"] += 1
            return False
        when = _parse(happened)
        if when and when > today:
            dropped["future_dated"] += 1
            return False
        key = (url or "", title.strip().lower())
        if key in seen_items:
            dropped["duplicate"] += 1
            return False
        seen_items.add(key)
        return True

    catalysts = [c for c in report.catalysts if keep(c.source_url, c.title, c.date)]
    regulation = [r for r in report.regulation if keep(r.source_url, r.title, r.announced_date)]
    risks = []
    for r in report.risks:
        if r.source_url is None or seen_url(r.source_url):
            risks.append(r)
        else:
            dropped["unverified_url"] += 1
    events = []
    for e in report.events:
        when = _parse(e.date)
        if (e.date and when is None) or (when and when < today):
            dropped["stale_event"] += 1  # unparseable or already past: not an upcoming event
            continue
        events.append(
            e.model_copy(update={"source_url": e.source_url if seen_url(e.source_url) else None})
        )
    sector_urls = [u for u in report.sector_view.source_urls if seen_url(u)]
    gaps = list(report.data_gaps)
    if not sector_urls:
        gaps.append("Sector view has no verified source; treat it as the model's opinion")
    cleaned = report.model_copy(
        update={
            "catalysts": catalysts,
            "regulation": regulation,
            "risks": risks,
            "events": events,
            "sector_view": report.sector_view.model_copy(update={"source_urls": sector_urls}),
            "data_gaps": gaps,
        }
    )
    return cleaned, dropped
