"""HTTP API for the dashboard. Personal use: binds to localhost only (see run_api.py)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from eqr.app.serialize import clean
from eqr.llm.claude_cli import LlmError

log = logging.getLogger(__name__)
MODELS = ("sonnet", "opus")


class Services(Protocol):
    def resolve(self, q: str) -> dict[str, Any]: ...
    def known(self, symbol: str) -> bool: ...
    def company(self, symbol: str) -> dict[str, Any]: ...
    def prices(self, symbol: str, period: str) -> dict[str, Any]: ...
    def sector(self, symbol: str) -> dict[str, Any]: ...
    def sectors(self) -> dict[str, Any]: ...
    def run_research(self, symbol: str, model: str) -> dict[str, Any]: ...
    def cached_research(self, symbol: str, model: str) -> dict[str, Any] | None: ...


class ResearchJobs:
    """One research run at a time (it uses the user's Claude plan); results kept in memory
    and on disk through the services' cache."""

    def __init__(self, services: Services) -> None:
        self._services = services
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")
        self._jobs: dict[tuple[str, str], Future] = {}
        self._lock = threading.Lock()

    def start(self, symbol: str, model: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get((symbol, model))
            if job is None or job.done():
                self._jobs[(symbol, model)] = self._pool.submit(
                    self._services.run_research, symbol, model
                )
        return self.status(symbol, model)

    def status(self, symbol: str, model: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get((symbol, model))
        if job is None:
            cached = self._services.cached_research(symbol, model)
            return (
                {"status": "done", "data": cached, "cached": True} if cached else {"status": "none"}
            )
        if not job.done():
            return {"status": "running"}
        exc = job.exception()
        if exc is None:
            return {"status": "done", "data": job.result()}
        if isinstance(exc, LlmError):
            return {"status": "failed", "error": str(exc), "kind": exc.kind}
        log.exception("Research failed for %s", symbol, exc_info=exc)
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "kind": "internal"}

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def create_app(services: Services) -> FastAPI:
    jobs = ResearchJobs(services)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="India Equity Research", version="0.1", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
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

    @app.get("/api/sectors")
    def sectors() -> dict[str, Any]:
        return clean(services.sectors())

    @app.get("/api/company/{symbol}/research")
    def research_status(symbol: str, model: str = "sonnet") -> dict[str, Any]:
        return clean(jobs.status(require(symbol), model_ok(model)))

    @app.post("/api/company/{symbol}/research")
    def research_start(symbol: str, model: str = "sonnet") -> dict[str, Any]:
        return clean(jobs.start(require(symbol), model_ok(model)))

    return app
