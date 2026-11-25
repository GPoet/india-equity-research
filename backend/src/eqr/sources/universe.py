"""NSE listed-equity master (EQUITY_L.csv), refreshed daily for the resolver."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from curl_cffi import requests

from eqr.resolver import Resolver

log = logging.getLogger(__name__)

EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
MAX_AGE_SECONDS = 24 * 3600
RETRY_AFTER_FAILURE = 3600  # after a failed refresh, keep using the old copy for an hour


def _download() -> str:
    try:
        resp = requests.get(EQUITY_LIST_URL, impersonate="chrome", timeout=30)
    except Exception as exc:  # curl_cffi transport errors
        raise RuntimeError(f"Could not download NSE equity list: {exc}") from exc
    if resp.status_code != 200 or not resp.text.startswith("SYMBOL,"):
        raise RuntimeError(f"Could not download NSE equity list: HTTP {resp.status_code}")
    return resp.text


def refresh_equity_list(path: Path, max_age: float = MAX_AGE_SECONDS) -> Path:
    """Download EQUITY_L.csv if missing or stale. On failure keep the old copy (logged)."""
    if path.exists() and time.time() - path.stat().st_mtime < max_age:
        return path
    try:
        text = _download()
    except RuntimeError as exc:
        if not path.exists():
            raise
        log.warning("Using stale equity list %s: %s", path, exc)
        # Push the mtime forward so we retry in an hour, not on every call.
        retry_at = time.time() - max_age + RETRY_AFTER_FAILURE
        os.utime(path, (retry_at, retry_at))
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def load_resolver(data_dir: Path) -> Resolver:
    return Resolver.from_csv(refresh_equity_list(data_dir / "EQUITY_L.csv"))
