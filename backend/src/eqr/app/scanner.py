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
from datetime import date, datetime
from pathlib import Path
from typing import Any

from eqr.app.serialize import clean
from eqr.forecast.model import ForecastModel
from eqr.pipeline import Context
from eqr.scan import order_universe, rank, scan_symbol, should_run
from eqr.sources.bhavcopy import BhavcopySource
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
        universe: Callable[[], dict[str, dict[str, str]]],
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
        universe = self._universe()
        order = order_universe(
            [s for s in universe if s in bars],
            self._nifty50(),
            {s: b.turnover for s, b in bars.items()},
        )
        current = _read(self._dir / "current.json")
        rows: dict[str, dict[str, Any]] = (
            {r["symbol"]: r for r in current["rows"]}
            if current and current.get("price_day") == day.isoformat()
            else {}
        )
        errors: dict[str, str] = {}  # failures are retried on a resumed run
        started = time.time()
        nifty, market, model = fetch_nifty(), self._ctx.market(), ForecastModel.load()
        for i, sym in enumerate(order, 1):
            if self._stop.is_set():
                return
            with self._lock:
                self._progress = {
                    "price_day": day,
                    "done": i - 1,
                    "total": len(order),
                    "current": sym,
                    "started_at": started,
                }
            if sym in rows:
                continue
            try:
                rows[sym] = scan_symbol(
                    self._ctx, sym, universe[sym]["name"], bars[sym], nifty, market, model
                )
            except Exception as exc:  # noqa: BLE001 - one company must not stop the scan
                errors[sym] = f"{type(exc).__name__}: {str(exc)[:160]}"
                log.warning("Scan %s failed: %s", sym, exc)
            if i % SAVE_EVERY == 0:
                _write(
                    self._dir / "current.json",
                    self._result(day, rows, errors, len(order), complete=False),
                )
        result = self._result(day, rows, errors, len(order), complete=True)
        _write(self._dir / "current.json", result)
        _write(self._dir / "history" / f"{day.isoformat()}.json", result)
        _write(self._dir / "latest.json", result)
        with self._lock:
            self._progress = {
                "price_day": day,
                "done": len(order),
                "total": len(order),
                "finished_at": time.time(),
            }

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
            "universe": "Nifty 500",
            "scanned": len(rows),
            "total": total,
            "errors": errors,
            "picks": picks,
            "ranked": ranked,
            "unranked": [r for r in rows.values() if not r.get("forecast")],
            "rows": list(rows.values()),
        }
