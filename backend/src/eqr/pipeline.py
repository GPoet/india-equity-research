"""End-to-end steps shared by the command-line scripts and the API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from eqr.cache import Cache
from eqr.fundamentals import Fundamentals, load_fundamentals
from eqr.llm.claude_cli import ClaudeCliProvider, LlmProvider
from eqr.market import MarketInputs, load_market_inputs
from eqr.nse_client import NseClient
from eqr.research.agent import NEWS_WINDOW_DAYS, run_research
from eqr.research.brief import build_brief
from eqr.research.store import ResearchStore
from eqr.resolver import Resolver
from eqr.sources.announcements import Announcement, fetch_announcements
from eqr.sources.documents import fetch_documents, select_documents
from eqr.sources.filings import FilingsSource
from eqr.sources.indices import IndexHistory
from eqr.sources.universe import load_resolver
from eqr.valuation.engine import ValuationReport, fetch_price_data, value_company

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@dataclass
class Context:
    """Long-lived objects: one NSE session, one cache, loaded lazily."""

    data_dir: Path = DATA
    _cache: Cache | None = None
    _client: NseClient | None = None
    _resolver: Resolver | None = None

    @property
    def cache(self) -> Cache:
        if self._cache is None:
            self._cache = Cache(self.data_dir / "cache.sqlite")
        return self._cache

    @property
    def client(self) -> NseClient:
        if self._client is None:
            self._client = NseClient(cache=self.cache)
        return self._client

    @property
    def resolver(self) -> Resolver:
        if self._resolver is None:
            self._resolver = load_resolver(self.data_dir)
        return self._resolver

    @property
    def filings(self) -> FilingsSource:
        return FilingsSource(self.client)

    @property
    def indices(self) -> IndexHistory:
        return IndexHistory(self.client, self.cache)

    @property
    def research_store(self) -> ResearchStore:
        return ResearchStore(self.data_dir / "research")

    def market(self) -> MarketInputs:
        return load_market_inputs()


def valuation(ctx: Context, symbol: str, today: date) -> tuple[Fundamentals, ValuationReport]:
    f = load_fundamentals(ctx.filings, symbol)
    prices = fetch_price_data(symbol, [y.fy_end for y in f.years], today)
    return f, value_company(f, ctx.market(), prices, today)


def announcements(ctx: Context, symbol: str, today: date) -> list[Announcement]:
    return fetch_announcements(ctx.client, symbol, today - timedelta(days=NEWS_WINDOW_DAYS), today)


def research(
    ctx: Context,
    symbol: str,
    name: str,
    today: date,
    model: str = "sonnet",
    provider: LlmProvider | None = None,
) -> dict[str, Any]:
    """Full research run. Raises LlmError on failure. Caches unless degraded."""
    f, report = valuation(ctx, symbol, today)
    anns = announcements(ctx, symbol, today)
    docs = fetch_documents(ctx.client, ctx.cache, anns)
    warnings = []
    if select_documents(anns) and not docs:
        warnings.append(
            "None of the company's NSE filings could be read; results rely on web sources"
        )
    brief = build_brief(name, anns[0].industry if anns else None, f, report)
    run = run_research(
        provider or ClaudeCliProvider(), brief, anns, today, model=model, documents=docs
    )
    data = {
        "symbol": symbol,
        "name": name,
        "brief": brief.facts,
        "report": run.report.model_dump(),
        "dropped": run.dropped,
        "meta": run.meta,
        "warnings": warnings,
    }
    if not warnings:
        ctx.research_store.save(symbol, model, data)
    return data
