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


def _parse(day: str | None) -> date | None:
    try:
        return date.fromisoformat(day) if day else None
    except ValueError:
        return None


def clean_report(report: ResearchReport, today: date) -> tuple[ResearchReport, dict[str, int]]:
    """Apply the sourcing rules. Returns the cleaned report and counts of what was dropped."""
    dropped = {"unsourced": 0, "future_dated": 0, "duplicate": 0}
    seen: set[tuple[str, str]] = set()

    def keep(url: str | None, title: str, happened: str | None) -> bool:
        if not _is_url(url):
            dropped["unsourced"] += 1
            return False
        when = _parse(happened)
        if when and when > today:
            dropped["future_dated"] += 1
            return False
        key = (url or "", title.strip().lower())
        if key in seen:
            dropped["duplicate"] += 1
            return False
        seen.add(key)
        return True

    catalysts = [c for c in report.catalysts if keep(c.source_url, c.title, c.date)]
    regulation = [r for r in report.regulation if keep(r.source_url, r.title, r.announced_date)]
    risks = [r for r in report.risks if r.source_url is None or _is_url(r.source_url)]
    sector = report.sector_view.model_copy(
        update={"source_urls": [u for u in report.sector_view.source_urls if _is_url(u)]}
    )
    cleaned = report.model_copy(
        update={
            "catalysts": catalysts,
            "regulation": regulation,
            "risks": risks,
            "sector_view": sector,
        }
    )
    return cleaned, dropped
