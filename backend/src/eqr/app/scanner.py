"""Runs the daily market scan in the background: by itself when NSE publishes a new trading
day (checked every 30 minutes, and on startup to catch up), or when the Refresh button asks.
Progress is saved as it goes, so a restart resumes instead of starting over; the last complete
scan stays visible until a new one finishes."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext as _nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from eqr.app.serialize import clean
from eqr.forecast.model import ForecastModel
from eqr.pipeline import Context
from eqr.scan import order_universe, rank, scan_symbol, should_run, symbols_with_new_results
from eqr.sources.announcements import fetch_market_announcements
from eqr.sources.bhavcopy import BhavcopySource
from eqr.sources.bse import BseFilingsSource, BseSource, bse_client
from eqr.sources.bse_prices import bse_market_series
from eqr.valuation.engine import fetch_nifty

log = logging.getLogger(__name__)

CHECK_EVERY = 30 * 60
SAVE_EVERY = 10


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean(data)))
    os.replace(tmp, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


class Scanner:
    def __init__(
        self,
        ctx: Context,
        out_dir: Path,
        universe: Callable[[], tuple[dict[str, str], set[str]]],
        nifty50: Callable[[], set[str]],
    ) -> None:
        self._ctx, self._dir = ctx, out_dir
        self._universe, self._nifty50 = universe, nifty50
        self._lock = threading.Lock()
        self._running = False
        self._progress: dict[str, Any] = {}
        self._stop = threading.Event()

    # ---- reading -------------------------------------------------------------
    def latest(self) -> dict[str, Any] | None:
        return _read(self._dir / "latest.json")

    def status(self) -> dict[str, Any]:
        with self._lock:
            running, progress = self._running, dict(self._progress)
        latest = self.latest()
        out: dict[str, Any] = {"running": running, "progress": progress, "latest": latest}
        if latest is None and running:
            out["partial"] = _read(self._dir / "current.json")  # first ever run: show what is done
        return out

    # ---- running ---------------------------------------------------------------
    def start(self) -> bool:
        """Start a scan now (Refresh button). False if one is already running."""
        with self._lock:
            if self._running:
                return False
            self._running = True
        threading.Thread(target=self._run_guarded, name="scan", daemon=True).start()
        return True

    def start_schedule(self) -> None:
        threading.Thread(target=self._schedule, name="scan-schedule", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _schedule(self) -> None:
        while not self._stop.is_set():
            try:
                bars_day = self._latest_file_day()
                last = self.latest()
                last_day = date.fromisoformat(last["price_day"]) if last else None
                if should_run(last_day, bars_day):
                    self.start()
            except Exception:  # noqa: BLE001 - the schedule must survive a bad check
                log.exception("Scan schedule check failed")
            self._stop.wait(CHECK_EVERY)

    def _latest_file_day(self) -> date | None:
        with self._ctx.client.background():
            got = BhavcopySource(self._ctx.client, self._ctx.cache).latest(date.today())
        return next(iter(got.values())).trade_date if got else None

    def _run_guarded(self) -> None:
        try:
            with self._ctx.client.background():  # pages get NSE first while this runs
                self._run()
        except Exception:  # noqa: BLE001
            log.exception("Scan failed")
            with self._lock:
                self._progress["error"] = "The scan stopped on an error; see the API log"
        finally:
            with self._lock:
                self._running = False

    def _run(self) -> None:
        bars = BhavcopySource(self._ctx.client, self._ctx.cache).latest(date.today())
        if not bars:
            raise RuntimeError("No NSE end-of-day file found in the last 10 days")
        day = next(iter(bars.values())).trade_date
        self._refresh_filed(day)
        names, nse_isins = self._universe()
        nifty, market, model = fetch_nifty(), self._ctx.market(), ForecastModel.load()

        # Lane 1: every NSE company that traded (main board and SME). ETFs and index funds trade
        # in the same file but are not on NSE's equity lists.
        listed = [sym for sym in bars if sym in names] if names else list(bars)
        nse_jobs = [
            (
                sym,
                lambda sym=sym: scan_symbol(
                    self._ctx, sym, names.get(sym, sym), bars[sym], nifty, market, model
                ),
            )
            for sym in order_universe(
                listed, self._nifty50(), {s: b.turnover for s, b in bars.items()}
            )
        ]
        # Lane 2: companies listed only on BSE, from BSE's own feeds (a separate server, so this
        # lane runs alongside the NSE one without slowing it).
        bse_jobs = self._bse_jobs(
            day, nse_isins | {b.isin for b in bars.values()}, nifty, market, model
        )

        current = _read(self._dir / "current.json")
        rows: dict[str, dict[str, Any]] = (
            {r.get("key", r["symbol"]): r for r in current["rows"]}
            if current and current.get("price_day") == day.isoformat()
            else {}
        )
        errors: dict[str, str] = {}  # failures are retried on a resumed run
        total = len(nse_jobs) + len(bse_jobs)
        state = {"done": 0, "nse": "", "bse": ""}
        started = time.time()
        guard = threading.Lock()

        def lane(name: str, jobs: list[tuple[str, Callable[[], dict[str, Any]]]]) -> None:
            ctx_mgr = self._ctx.client.background() if name == "nse" else _nullcontext()
            with ctx_mgr:
                for key, job in jobs:
                    if self._stop.is_set():
                        return
                    with guard:
                        state[name] = key
                        self._set_progress(day, state, total, started)
                    if key not in rows:
                        try:
                            row = job()
                            with guard:
                                rows[key] = {**row, "key": key}
                        except Exception as exc:  # noqa: BLE001 - one company must not stop the scan
                            with guard:
                                errors[key] = f"{type(exc).__name__}: {str(exc)[:160]}"
                            log.warning("Scan %s failed: %s", key, exc)
                    with guard:
                        state["done"] += 1
                        if state["done"] % SAVE_EVERY == 0:
                            _write(
                                self._dir / "current.json",
                                self._result(day, dict(rows), dict(errors), total, complete=False),
                            )

        threads = [
            threading.Thread(target=lane, args=(n, j), name=f"scan-{n}", daemon=True)
            for n, j in (("nse", nse_jobs), ("bse", bse_jobs))
            if j
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if self._stop.is_set():
            return
        result = self._result(day, rows, errors, total, complete=True)
        _write(self._dir / "current.json", result)
        _write(self._dir / "history" / f"{day.isoformat()}.json", result)
        _write(self._dir / "latest.json", result)
        with self._lock:
            self._progress = {
                "price_day": day,
                "done": total,
                "total": total,
                "finished_at": time.time(),
            }

    def _set_progress(self, day: date, state: dict[str, Any], total: int, started: float) -> None:
        current = ", ".join(v for v in (state["nse"], state["bse"]) if v)
        with self._lock:
            self._progress = {
                "price_day": day,
                "done": state["done"],
                "total": total,
                "current": current,
                "started_at": started,
            }

    def _bse_jobs(
        self, day: date, nse_isins: set[str], nifty: Any, market: Any, model: Any
    ) -> list[tuple[str, Callable[[], dict[str, Any]]]]:
        """Companies listed only on BSE that traded on `day`, most traded first."""
        try:
            client = bse_client(self._ctx.cache)
            source = BseSource(client, self._ctx.cache)
            bars, scrips = source.bars(day), source.scrips()
        except Exception as exc:  # noqa: BLE001 - BSE down must not stop the NSE scan
            log.warning("BSE unavailable, scanning NSE only: %s", exc)
            return []
        if not bars:
            log.warning("No BSE price file for %s; scanning NSE only", day)
            return []
        filings = BseFilingsSource(client)
        only = sorted(
            (
                code
                for code, info in scrips.items()
                if code in bars and info["isin"] not in nse_isins
            ),
            key=lambda c: -bars[c].turnover,
        )

        def job(code: str) -> dict[str, Any]:
            info = scrips[code]
            return scan_symbol(
                self._ctx,
                code,
                info["name"],
                bars[code],
                nifty,
                market,
                model,
                filings=filings,
                series=bse_market_series(client, code, nifty),
                with_ownership=False,  # BSE shareholding is not wired in yet
                extra={"exchange": "BSE", "ticker": info["ticker"], "link": info["url"] or None},
            )

        return [(f"BSE:{code}", lambda code=code: job(code)) for code in only]

    def _refresh_filed(self, day: date) -> None:
        """Drop cached filing lists of companies that announced results since the last scan."""
        last = self.latest()
        if last is None:
            return  # first scan: everything is fetched fresh anyway
        d = date.fromisoformat(last["price_day"])
        refreshed: set[str] = set()
        while d < day:
            d += timedelta(days=1)
            try:
                refreshed |= symbols_with_new_results(
                    fetch_market_announcements(self._ctx.client, d)
                )
            except Exception as exc:  # noqa: BLE001 - a missed day only means slightly stale lists
                log.warning("Announcements for %s unavailable: %s", d, exc)
        for sym in refreshed:
            self._ctx.filings.invalidate(sym)
        log.info("Scan: refreshed filing lists of %d companies with new results", len(refreshed))

    @staticmethod
    def _result(
        day: date,
        rows: dict[str, dict[str, Any]],
        errors: dict[str, str],
        total: int,
        complete: bool,
    ) -> dict[str, Any]:
        picks, ranked = rank(list(rows.values()))
        return {
            "price_day": day.isoformat(),
            "run_at": datetime.now().isoformat(timespec="minutes"),
            "complete": complete,
            "universe": "Every listed company that traded: NSE main board and SME, plus BSE-only",
            "scanned": len(rows),
            "total": total,
            "errors": errors,
            "picks": picks,
            "ranked": ranked,
            "unranked": [r for r in rows.values() if not r.get("forecast")],
            "rows": list(rows.values()),
        }
