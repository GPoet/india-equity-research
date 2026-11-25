"""Real implementation of the API's Services: wires the pipeline together with short
in-memory caches so the dashboard stays fast and NSE is not hammered."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from eqr.fundamentals import Fundamentals, owners_profit
from eqr.pipeline import Context, announcements, research, valuation
from eqr.sectors.catalog import sector_for_industry
from eqr.sectors.view import build_stats, sector_picture
from eqr.sources.prices import history

T = TypeVar("T")
VALUATION_TTL = 15 * 60
SECTOR_TTL = 6 * 3600
INDEX_DAYS = 400


class _Memo:
    """TTL cache with a lock per key, so concurrent requests never duplicate heavy work."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str, ttl: float, make: Callable[[], T]) -> T:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            hit = self._data.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            value = make()
            self._data[key] = (time.time(), value)
            return value


def _series(f: Fundamentals) -> dict[str, list[dict[str, Any]]]:
    top = "total_income" if f.is_bank else "revenue"
    years = [
        {
            "fy_end": y.fy_end,
            "source": y.income_source,
            "revenue": y.income.get(top),
            "ebitda": y.income.get("ebitda"),
            "profit": owners_profit(y.income),
            "eps": y.income.get("eps_basic"),
            "cfo": y.income.get("cfo"),
            "capex": y.income.get("capex_ppe"),
            "equity": y.balance.get("equity_owners"),
            "debt": y.balance.get("total_debt"),
            "nii": y.income.get("nii"),
        }
        for y in reversed(f.years)
    ]
    quarters = [
        {
            "period_end": q.period_end,
            "revenue": q.income.get(top),
            "profit": owners_profit(q.income),
            "ebitda": q.income.get("ebitda"),
            "nii": q.income.get("nii"),
        }
        for q in reversed(f.quarters[:12])
    ]
    return {"years": years, "quarters": quarters}


class LiveServices:
    def __init__(self, ctx: Context | None = None) -> None:
        self.ctx = ctx or Context()
        self._memo = _Memo()

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
        anns = announcements(self.ctx, symbol, date.today())
        return anns[0].industry if anns else None

    def company(self, symbol: str) -> dict[str, Any]:
        def make() -> dict[str, Any]:
            sec = self.ctx.resolver.by_symbol(symbol)
            f, report = valuation(self.ctx, symbol, date.today())
            industry = self._industry(symbol)
            return {
                "symbol": symbol,
                "name": sec.name if sec else symbol,
                "industry": industry,
                "sector_key": sector_for_industry(industry, sec.name if sec else ""),
                "valuation": report.to_dict(),
                "financials": _series(f),
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

    def run_research(self, symbol: str, model: str) -> dict[str, Any]:
        sec = self.ctx.resolver.by_symbol(symbol)
        return research(self.ctx, symbol, sec.name if sec else symbol, date.today(), model=model)

    def cached_research(self, symbol: str, model: str) -> dict[str, Any] | None:
        return self.ctx.research_store.load(symbol, model)
