"""HTTP API for the dashboard. Personal use: binds to 127.0.0.1 only (scripts/run_api.py).

Browser safety: a page on any website can send a "simple" POST to localhost without a
CORS preflight, and could use that to spend the user's Claude plan. So the research POST
needs a custom header (forcing a preflight, which the CORS allowlist then refuses), is
refused when the browser says the request is cross-site, and every request must carry a
localhost Host header (blocks DNS rebinding).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from eqr.app.serialize import clean
from eqr.llm.claude_cli import LlmError
from eqr.llm.xai import XaiError
from eqr.nse_client import NseError
from eqr.sources.prices import PriceError

log = logging.getLogger(__name__)
MODELS = ("sonnet", "opus")
ALLOWED_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
ALLOWED_HOSTS = ("localhost", "127.0.0.1")
CSRF_HEADER = "X-Equity-Desk"


class Services(Protocol):
    def resolve(self, q: str) -> dict[str, Any]: ...
    def known(self, symbol: str) -> bool: ...
    def company(self, symbol: str) -> dict[str, Any]: ...
    def prices(self, symbol: str, period: str) -> dict[str, Any]: ...
    def sector(self, symbol: str) -> dict[str, Any]: ...
    def sectors(self) -> dict[str, Any]: ...
    def run_research(self, symbol: str, model: str) -> dict[str, Any]: ...
    def cached_research(self, symbol: str, model: str) -> dict[str, Any] | None: ...
    def journal(self) -> dict[str, Any]: ...
    def backtest(self) -> dict[str, Any] | None: ...
    def forecast(self, symbol: str) -> dict[str, Any]: ...
    def overview(self) -> dict[str, Any]: ...
    def sentiment_enabled(self) -> bool: ...
    def run_sentiment(self, symbol: str, kind: str) -> dict[str, Any]: ...
    def cached_sentiment(self, symbol: str, kind: str) -> dict[str, Any] | None: ...


class Jobs:
    """Background runs (research on the Claude plan, sentiment on the xAI budget), one at a
    time per kind, with results cached by the services."""

    def __init__(
        self,
        run: Callable[[str, str], dict[str, Any]],
        cached: Callable[[str, str], dict[str, Any] | None],
        name: str,
        errors: tuple[type[Exception], ...],
    ) -> None:
        self._run_fn, self._cached_fn, self._name, self._errors = run, cached, name, errors
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._jobs: dict[tuple[str, str], Future] = {}
        self._running: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def _run(self, key: tuple[str, str]) -> dict[str, Any]:
        with self._lock:
            self._running.add(key)
        try:
            return self._run_fn(*key)
        finally:
            with self._lock:
                self._running.discard(key)

    def start(self, symbol: str, model: str, force: bool) -> dict[str, Any]:
        key = (symbol, model)
        if not force and (cached := self._cached_fn(symbol, model)):
            with self._lock:
                job = self._jobs.get(key)
            if job is None or job.done():
                return {"status": "done", "data": cached, "cached": True}
        with self._lock:
            job = self._jobs.get(key)
            if job is None or job.done():
                self._jobs[key] = self._pool.submit(self._run, key)
        return self.status(symbol, model)

    def status(self, symbol: str, model: str) -> dict[str, Any]:
        key = (symbol, model)
        with self._lock:
            job = self._jobs.get(key)
            running = key in self._running
        if job is None:
            cached = self._cached_fn(symbol, model)
            return (
                {"status": "done", "data": cached, "cached": True} if cached else {"status": "none"}
            )
        if not job.done():
            return {"status": "running" if running else "queued"}
        try:
            exc = job.exception()
        except CancelledError:
            return {
                "status": "failed",
                "error": f"{self._name.capitalize()} was cancelled (server shutting down)",
                "kind": "cancelled",
            }
        if exc is None:
            return {"status": "done", "data": job.result()}
        if isinstance(exc, self._errors):
            return {"status": "failed", "error": str(exc), "kind": getattr(exc, "kind", "error")}
        log.error("%s failed for %s", self._name, symbol, exc_info=exc)
        return {"status": "failed", "error": _plain(exc), "kind": "internal"}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _plain(exc: BaseException) -> str:
    if isinstance(exc, NseError):
        return "NSE did not respond properly; try again in a minute"
    if isinstance(exc, PriceError):
        return "Yahoo had no price data for this company"
    return "Something went wrong on the research server; see its log"


def _check_same_site(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing request header; use the dashboard")
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, "Cross-site request refused")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site request refused")


def create_app(services: Services) -> FastAPI:
    jobs = Jobs(services.run_research, services.cached_research, "research", (LlmError,))
    sentiment_jobs = Jobs(
        services.run_sentiment, services.cached_sentiment, "sentiment", (XaiError,)
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()
        sentiment_jobs.shutdown()

    app = FastAPI(title="India Equity Research", version="0.2", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_methods=["GET", "POST"],
        allow_headers=[CSRF_HEADER],
    )

    @app.exception_handler(NseError)
    async def nse_down(_: Request, exc: NseError) -> JSONResponse:
        log.warning("NSE error: %s", exc)
        return JSONResponse(
            {"detail": "NSE did not respond properly; try again in a minute"}, status_code=503
        )

    @app.exception_handler(PriceError)
    async def no_prices(_: Request, exc: PriceError) -> JSONResponse:
        log.warning("Price error: %s", exc)
        return JSONResponse({"detail": "Yahoo had no price data for this company"}, status_code=503)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("Unhandled error", exc_info=exc)
        return JSONResponse(
            {"detail": "Something went wrong on the research server; see its log"}, status_code=500
        )

    def require(symbol: str) -> str:
        sym = symbol.upper()
        if not services.known(sym):
            raise HTTPException(404, f"Unknown NSE symbol {symbol}")
        return sym

    def model_ok(model: str) -> str:
        if model not in MODELS:
            raise HTTPException(422, f"model must be one of {MODELS}")
        return model

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/api/resolve")
    def resolve(q: str = Query(..., max_length=500)) -> dict[str, Any]:
        if not q.strip():
            raise HTTPException(422, "Enter a ticker, company name or link")
        return clean(services.resolve(q))

    @app.get("/api/company/{symbol}")
    def company(symbol: str) -> dict[str, Any]:
        return clean(services.company(require(symbol)))

    @app.get("/api/company/{symbol}/prices")
    def prices(
        symbol: str, period: str = Query("1y", pattern="^(6mo|1y|2y|5y|10y|max)$")
    ) -> dict[str, Any]:
        return clean(services.prices(require(symbol), period))

    @app.get("/api/company/{symbol}/sector")
    def sector(symbol: str) -> dict[str, Any]:
        return clean(services.sector(require(symbol)))

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        return clean(services.overview())

    @app.get("/api/sectors")
    def sectors() -> dict[str, Any]:
        return clean(services.sectors())

    @app.get("/api/journal")
    def journal() -> dict[str, Any]:
        return clean(services.journal())

    @app.get("/api/backtest")
    def backtest() -> dict[str, Any]:
        result = services.backtest()
        if result is None:
            raise HTTPException(
                404, "No backtest has been run yet: uv run python scripts/backtest.py"
            )
        return clean(result)

    @app.get("/api/company/{symbol}/forecast")
    def company_forecast(symbol: str) -> dict[str, Any]:
        return clean(services.forecast(require(symbol)))

    @app.get("/api/company/{symbol}/sentiment")
    def sentiment_status(symbol: str) -> dict[str, Any]:
        sym = require(symbol)
        if not services.sentiment_enabled():
            return {
                "status": "disabled",
                "error": "Add XAI_API_KEY to backend/.env to turn on X sentiment",
            }
        return clean(sentiment_jobs.status(sym, "x"))

    @app.post("/api/company/{symbol}/sentiment")
    def sentiment_start(request: Request, symbol: str, force: bool = False) -> dict[str, Any]:
        _check_same_site(request)
        sym = require(symbol)
        if not services.sentiment_enabled():
            return {
                "status": "disabled",
                "error": "Add XAI_API_KEY to backend/.env to turn on X sentiment",
            }
        return clean(sentiment_jobs.start(sym, "x", force))

    @app.get("/api/company/{symbol}/research")
    def research_status(symbol: str, model: str = "sonnet") -> dict[str, Any]:
        return clean(jobs.status(require(symbol), model_ok(model)))

    @app.post("/api/company/{symbol}/research")
    def research_start(
        request: Request, symbol: str, model: str = "sonnet", force: bool = False
    ) -> dict[str, Any]:
        _check_same_site(request)
        return clean(jobs.start(require(symbol), model_ok(model), force))

    return app
