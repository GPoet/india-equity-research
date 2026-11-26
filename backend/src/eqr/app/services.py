"""Real implementation of the API's Services: wires the pipeline together with short
in-memory caches so the dashboard stays fast and NSE is not hammered."""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import date, timedelta
from typing import Any, TypeVar

import yfinance as yf

from eqr.app.scanner import Scanner
from eqr.company_view import series
from eqr.forecast.dataset import observation
from eqr.forecast.model import ForecastModel, forecast
from eqr.journal import HORIZONS, score_entry, summarise, thin
from eqr.listings import all_names, nifty50_symbols
from eqr.llm.xai import DEFAULT_MODEL, SpendLedger, XaiClient, XaiError
from eqr.nse_client import NseError
from eqr.overview import (
    WINDOWS,
    DayFiles,
    circuit_factors,
    headline,
    most_traded,
    movers,
    sector_moves,
    unusual_volume,
)
from eqr.pipeline import Context, announcements, research, valuation
from eqr.research.store import ResearchStore
from eqr.sectors.catalog import SECTORS, sector_for_industry
from eqr.sectors.view import build_stats, sector_picture
from eqr.sentiment.agent import run_sentiment
from eqr.settings import load_env
from eqr.sources.announcements import fetch_announcements
from eqr.sources.bhavcopy import BhavcopySource
from eqr.sources.bse import BseSource, bse_client
from eqr.sources.corporate_actions import fetch_share_factors
from eqr.sources.prices import history
from eqr.valuation import ENGINE_VERSION
from eqr.valuation.engine import _dated, fetch_market_series
from eqr.valuation.pricedata import beta_as_of

T = TypeVar("T")
log = logging.getLogger(__name__)
VALUATION_TTL = 15 * 60
SECTOR_TTL = 6 * 3600
INDEX_DAYS = 400
JOURNAL_PRICE_TTL = 6 * 3600
OVERVIEW_TTL = 15 * 60
UNIVERSE_TTL = 24 * 3600
OVERVIEW_DAYS = 22  # a month of trading days plus the day before
NEWS_MOVERS = 5
NIFTY500 = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
NIFTY50 = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
ALL_LISTS = (
    ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "SYMBOL", "NAME OF COMPANY"),
    (
        "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
        "SYMBOL",
        "NAME_OF_COMPANY",
    ),
)
NEWS_CATEGORIES = (
    "Financial Result Updates",
    "Outcome of Board Meeting",
    "Acquisition",
    "Bagging/Receiving of orders/contracts",
    "Credit Rating",
    "Change in Management",
    "Disclosure under SEBI Takeover Regulations",
    "Press Release",
    "General Updates",
)
SENTIMENT_HOURS = 6
DEFAULT_XAI_BUDGET = 10.0


FAILURE_TTL = 45  # a failed lookup is remembered briefly so waiters don't each retry it


class _Memo:
    """TTL cache with a lock per key, so concurrent requests never duplicate heavy work.
    Failures are cached for FAILURE_TTL seconds and re-raised to queued waiters."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str, ttl: float, make: Callable[[], T]) -> T:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            hit = self._data.get(key)
            if hit:
                stamp, value = hit
                if isinstance(value, _Failure):
                    if time.time() - stamp < FAILURE_TTL:
                        raise value.exc
                elif time.time() - stamp < ttl:
                    return value
            try:
                value = make()
            except Exception as exc:
                self._data[key] = (time.time(), _Failure(exc))
                raise
            self._data[key] = (time.time(), value)
            return value


class _Failure:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc


class LiveServices:
    def __init__(self, ctx: Context | None = None) -> None:
        self.ctx = ctx or Context()
        self._memo = _Memo()
        self._scanner: Scanner | None = None
        self._sentiment_store = ResearchStore(
            self.ctx.data_dir / "sentiment", max_age_hours=SENTIMENT_HOURS
        )

    def resolve(self, q: str) -> dict[str, Any]:
        res = self.ctx.resolver.resolve(q)
        sec = lambda s: {"symbol": s.symbol, "name": s.name, "isin": s.isin}  # noqa: E731
        return {
            "query": res.query,
            "match": sec(res.match) if res.match else None,
            "method": res.method,
            "candidates": [{**sec(c.security), "score": round(c.score, 1)} for c in res.candidates],
        }

    def known(self, symbol: str) -> bool:
        return self.ctx.resolver.by_symbol(symbol) is not None

    def _industry(self, symbol: str) -> str | None:
        """NSE's industry label, taken from the company's announcements. Only a label: if the
        lookup fails or the company filed nothing recently, return None rather than fail."""
        try:
            anns = announcements(self.ctx, symbol, date.today())
        except Exception as exc:  # noqa: BLE001 - optional data must not break the page
            log.warning("Industry lookup for %s failed: %s", symbol, exc)
            return None
        return next((a.industry for a in anns if a.industry), None)

    def company(self, symbol: str) -> dict[str, Any]:
        def make() -> dict[str, Any]:
            sec = self.ctx.resolver.by_symbol(symbol)
            f, report = valuation(self.ctx, symbol, date.today())
            try:
                self.ctx.journal.record(report, date.today(), ENGINE_VERSION)
            except Exception as exc:  # noqa: BLE001 - the track record must never break the page
                log.warning("Journal write for %s failed: %s", symbol, exc)
            industry = self._industry(symbol)
            return {
                "symbol": symbol,
                "name": sec.name if sec else symbol,
                "industry": industry,
                "sector_key": sector_for_industry(industry, sec.name if sec else ""),
                "valuation": report.to_dict(),
                "financials": series(f),
                "generated_at": time.time(),
            }

        return self._memo.get(f"company:{symbol}", VALUATION_TTL, make)

    def prices(self, symbol: str, period: str) -> dict[str, Any]:
        def make() -> dict[str, Any]:
            h = history(symbol, period=period)
            return {
                "symbol": symbol,
                "period": period,
                "points": [{"date": ts.date(), "close": float(c)} for ts, c in h["Close"].items()],
            }

        return self._memo.get(f"prices:{symbol}:{period}", VALUATION_TTL, make)

    def _index_frames(self):
        return self._memo.get(
            "indices", SECTOR_TTL, lambda: self.ctx.indices.frame(date.today(), INDEX_DAYS)
        )

    def sectors(self) -> dict[str, Any]:
        closes, pe = self._index_frames()
        stats = sorted(
            (s for s in build_stats(closes, pe).values()), key=lambda s: (s.rank == 0, s.rank)
        )
        return {"as_of": closes.index[-1].date(), "sectors": stats}

    def sector(self, symbol: str) -> dict[str, Any]:
        closes, pe = self._index_frames()
        sec = self.ctx.resolver.by_symbol(symbol)
        industry = self._industry(symbol)
        key = sector_for_industry(industry, sec.name if sec else "")
        return {"industry": industry, "sector_key": key, "picture": sector_picture(key, closes, pe)}

    def _closes(self, symbol: str):
        return self._memo.get(
            f"closes:{symbol}",
            JOURNAL_PRICE_TTL,
            lambda: _dated(history(symbol, period="max")["Close"]),
        )

    def journal(self) -> dict[str, Any]:
        today = date.today()
        index = self._memo.get(
            "closes:^NSEI",
            JOURNAL_PRICE_TTL,
            lambda: _dated(yf.Ticker("^NSEI").history(period="max", auto_adjust=False)["Close"]),
        )
        scored = []
        for e in self.ctx.journal.entries():
            try:
                scores = score_entry(e, self._closes(e["symbol"]), index, today)
            except Exception as exc:  # noqa: BLE001 - one missing price history must not hide the rest
                log.warning("Scoring %s failed: %s", e["symbol"], exc)
                scores = {h: {"outcome": "no data", "excess": None} for h in HORIZONS}
            scored.append({**e, "scores": scores})
        return {
            "as_of": today,
            "entries": scored,
            "summary": summarise(thin(scored)),  # one call per company per 30 days
            "engine_version": ENGINE_VERSION,
        }

    def _nifty500(self) -> dict[str, dict[str, str]]:
        def make() -> dict[str, dict[str, str]]:
            text = self.ctx.client.get_bytes(NIFTY500).decode("utf-8-sig")
            return {
                r["Symbol"].strip(): {
                    "name": r["Company Name"].strip(),
                    "industry": r["Industry"].strip(),
                }
                for r in csv.DictReader(io.StringIO(text))
                if r.get("Symbol")
            }

        return self._memo.get("nifty500", UNIVERSE_TTL, make)

    def _all_names(self) -> tuple[dict[str, str], set[str]]:
        return self._memo.get("all-names", UNIVERSE_TTL, lambda: all_names(self.ctx.client))

    def _nifty50(self) -> set[str]:
        return self._memo.get("nifty50", UNIVERSE_TTL, lambda: nifty50_symbols(self.ctx.client))

    @property
    def scanner(self) -> Scanner:
        if self._scanner is None:
            self._scanner = Scanner(
                self.ctx, self.ctx.data_dir / "scan", self._all_names, self._nifty50
            )
        return self._scanner

    def start_background(self) -> None:
        self.scanner.start_schedule()

    def stop_background(self) -> None:
        if self._scanner is not None:
            self._scanner.stop()

    def scan(self) -> dict[str, Any]:
        return self.scanner.status()

    def start_scan(self) -> dict[str, Any]:
        started = self.scanner.start()
        return {"started": started, **self.scanner.status()}

    def overview(self) -> dict[str, Any]:
        def make() -> dict[str, Any]:
            names, nse_isins = self._all_names()
            bhav = BhavcopySource(self.ctx.client, self.ctx.cache)
            files: DayFiles = []
            d = date.today()
            while len(files) < OVERVIEW_DAYS and (date.today() - d).days < 60:
                if d.weekday() < 5 and (bars := bhav.for_day(d)):
                    files.append((d, bars))
                d -= timedelta(days=1)
            if len(files) < WINDOWS["month"] + 1:
                raise NseError("Not enough NSE daily files to build the market overview")
            files.reverse()
            factors = fetch_share_factors(self.ctx.client, files[0][0], files[-1][0])
            # Every NSE company (main board and SME; ETFs are not on NSE's company lists) ...
            universe = set(names) if names else {s for _, bars in files for s in bars}
            labels: dict[str, str] = dict(names)
            meta: dict[str, dict[str, Any]] = {}
            # ... plus companies listed only on BSE, keyed "BSE:<code>".
            files, bse_keys = self._with_bse_only(files, nse_isins, labels, meta)
            universe |= bse_keys
            factors.update(circuit_factors(files, bse_keys))
            files = [(dd, {k: b for k, b in bars.items() if k in universe}) for dd, bars in files]
            last_day, today = files[-1]
            mv = movers(files, factors, universe)
            closes, _ = self._index_frames()
            week_movers = [
                r
                for r in mv["week"]["best"][:NEWS_MOVERS] + mv["week"]["worst"][:NEWS_MOVERS]
                if not r["symbol"].startswith("BSE:")  # NSE announcements only
            ]
            return {
                "as_of": last_day,
                "universe": "All listed companies: NSE main board, NSE SME and BSE-only",
                "names": labels,
                "meta": meta,
                "sectors": sector_moves(closes, {s.label: s.index for s in SECTORS.values()}),
                "movers": mv,
                "trending": unusual_volume(files, factors),
                "most_traded": most_traded(today, day=last_day, factors=factors),
                "news": self._week_news(week_movers, files[-WINDOWS["week"]][0], last_day),
            }

        return self._memo.get("overview", OVERVIEW_TTL, make)

    def _with_bse_only(
        self,
        files: DayFiles,
        nse_isins: set[str],
        labels: dict[str, str],
        meta: dict[str, dict[str, Any]],
    ) -> tuple[DayFiles, set[str]]:
        """Add BSE's daily files for companies not listed on NSE. BSE down = NSE only."""
        try:
            source = BseSource(bse_client(self.ctx.cache), self.ctx.cache)
            scrips = source.scrips()
        except Exception as exc:  # noqa: BLE001 - the overview must still show NSE
            log.warning("BSE unavailable for the overview: %s", exc)
            return files, set()
        isins = nse_isins | {b.isin for _, bars in files for b in bars.values()}
        only = {c: info for c, info in scrips.items() if info["isin"] and info["isin"] not in isins}
        keys: set[str] = set()
        merged: DayFiles = []
        for d, bars in files:
            extra = {}
            for code, b in (source.bars(d) or {}).items():
                if code in only:
                    key = f"BSE:{code}"
                    extra[key] = replace(b, symbol=key)
                    keys.add(key)
            merged.append((d, {**bars, **extra}))
        for key in keys:
            info = only[key[4:]]
            labels[key] = info["name"]
            meta[key] = {"ticker": info["ticker"], "exchange": "BSE", "link": info["url"] or None}
        return merged, keys

    def _week_news(
        self, rows: list[dict[str, Any]], start: date, end: date
    ) -> list[dict[str, Any]]:
        """The most substantive filing each of the week's biggest movers made that week."""
        rank = {c: i for i, c in enumerate(NEWS_CATEGORIES)}
        out = []
        for r in sorted(rows, key=lambda x: abs(x["change"]), reverse=True):
            try:
                anns = fetch_announcements(self.ctx.client, r["symbol"], start, end)
            except Exception as exc:  # noqa: BLE001 - one company's filings must not drop the section
                log.warning("Announcements for %s failed: %s", r["symbol"], exc)
                continue
            picks = sorted(
                (a for a in anns if a.category in rank),
                key=lambda a: (rank[a.category], -a.when.timestamp()),
            )
            if picks:
                a = picks[0]
                out.append(
                    {
                        "symbol": r["symbol"],
                        "change": r["change"],
                        "category": a.category,
                        "text": headline(a.text)[:400],
                        "when": a.when,
                        "url": a.url,
                    }
                )
        return out

    def forecast(self, symbol: str) -> dict[str, Any]:
        model = ForecastModel.load()
        if model is None:
            return {
                "status": "not_fitted",
                "error": "Forecast model not fitted yet: run scripts/forecast_fit.py",
            }

        def make() -> dict[str, Any]:
            v = self.company(symbol)["valuation"]
            r = v["result"]
            series = fetch_market_series(symbol)
            pairs = []
            for ref in self.ctx.filings.list_raw(symbol):
                try:
                    pairs.append((ref, self.ctx.filings.fetch(ref)))
                except Exception as exc:  # noqa: BLE001 - one unreadable filing must not hide the forecast
                    log.warning("Forecast: %s %s unreadable: %s", symbol, ref.period_end, exc)
            today = date.today()
            row = {"upside": r["upside"], "confidence": r["confidence"], "used": list(r["used"])}
            x = observation(symbol, pairs, series, today, row)
            if x is None:
                return {"status": "no_data", "error": "Under a year of prices: no forecast"}
            beta, _ = beta_as_of(series.closes, series.index_closes, today)
            market_return = self.ctx.market().cost_of_equity(1.0) / 100
            return {
                "status": "ok",
                "price": v["price"],
                "price_as_of": v["price_as_of"],
                "horizons": [
                    asdict(h) for h in forecast(model, x, v["price"], beta, market_return, today)
                ],
                "inputs": {
                    k: x.get(k)
                    for k in ("mom_12_1", "rev_1m", "surprise", "value", "next_results_est")
                },
                "beta": beta,
                "market_return_assumed": market_return,
                "model": {
                    "fitted_on": model.fitted_on,
                    "tested_on": model.tested_on,
                    "test": model.test,
                    "has_edge": model.has_edge,
                },
            }

        return self._memo.get(f"forecast:{symbol}", VALUATION_TTL, make)

    def backtest(self) -> dict[str, Any] | None:
        path = self.ctx.data_dir / "backtest" / "latest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def _xai(self) -> XaiClient | None:
        env = load_env(keys=("XAI_API_KEY", "XAI_MONTHLY_BUDGET_USD", "XAI_MODEL"))
        key = env.get("XAI_API_KEY")
        if not key:
            return None
        try:
            budget = float(env.get("XAI_MONTHLY_BUDGET_USD", DEFAULT_XAI_BUDGET))
        except ValueError:
            budget = DEFAULT_XAI_BUDGET
        return XaiClient(
            key,
            SpendLedger(self.ctx.data_dir / "xai_spend.sqlite"),
            budget,
            model=env.get("XAI_MODEL", DEFAULT_MODEL),
        )

    def sentiment_enabled(self) -> bool:
        return bool(load_env(keys=("XAI_API_KEY",)).get("XAI_API_KEY"))

    def run_sentiment(self, symbol: str, kind: str = "x") -> dict[str, Any]:
        client = self._xai()
        if client is None:
            raise XaiError("no_key", "No xAI API key: add XAI_API_KEY to backend/.env")
        sec = self.ctx.resolver.by_symbol(symbol)
        try:
            run = run_sentiment(
                client, sec.name if sec else symbol, symbol, self._industry(symbol), date.today()
            )
        finally:
            client.close()
        data = {
            "symbol": symbol,
            "report": run.report.model_dump(),
            "dropped": run.dropped,
            "meta": {**run.meta, "month_spend_usd": client.month_spend()},
        }
        self._sentiment_store.save(symbol, kind, data)
        return data

    def cached_sentiment(self, symbol: str, kind: str = "x") -> dict[str, Any] | None:
        return self._sentiment_store.load(symbol, kind)

    def run_research(self, symbol: str, model: str) -> dict[str, Any]:
        sec = self.ctx.resolver.by_symbol(symbol)
        return research(self.ctx, symbol, sec.name if sec else symbol, date.today(), model=model)

    def cached_research(self, symbol: str, model: str) -> dict[str, Any] | None:
        return self.ctx.research_store.load(symbol, model)
