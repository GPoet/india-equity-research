"""Polite NSE client.

nseindia.com sits behind bot protection: plain HTTP clients get 403, so this
uses curl_cffi's Chrome impersonation and a warmed-up session cookie.
Requests are throttled (default 1 per second) and cached. Responses are
validated before caching, because NSE often answers a rejected session with
HTTP 200 and an HTML page or an empty body. The live quote API stays blocked
even with this, so prices come from yfinance and bhavcopy.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from curl_cffi import requests

from eqr.cache import Cache

BASE = "https://www.nseindia.com"
API = f"{BASE}/api/"
EMPTY_TTL = 600.0  # an empty list may be real (new listing) or a soft block: recheck soon
MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}


_thread = threading.local()


class NseError(RuntimeError):
    """NSE returned an error, a blocked response, or an invalid body."""


class NseNotFound(NseError):
    """HTTP 404: the resource does not exist (e.g. no bhavcopy on a holiday)."""


_XBRL_ROOT = re.compile(r"<(?:[A-Za-z][\w.-]*:)?xbrl[\s>]")


def looks_like_xbrl(text: str) -> bool:
    """True when the body opens with an XBRL root element (not an HTML error page)."""
    return bool(_XBRL_ROOT.search(text.lstrip()[:4000]))


class NseClient:
    def __init__(
        self,
        cache: Cache | None = None,
        min_interval: float = 1.0,
        timeout: float = 30.0,
        session_factory: Callable[[], Any] | None = None,
        backoff: float = 2.0,
    ) -> None:
        self._cache = cache
        self._min_interval = min_interval
        self._timeout = timeout
        self._backoff = backoff
        self._session_factory = session_factory or (lambda: requests.Session(impersonate="chrome"))
        self._session: Any = None
        self._last_call = 0.0
        self._lock = threading.Lock()
        # Requests from the website go first: background work (the daily scan) waits while
        # any foreground request is queued, so pages stay quick during a long scan.
        self._fg_waiting = 0
        self._fg_cond = threading.Condition()

    @contextmanager
    def background(self) -> Iterator[None]:
        """Mark this thread's requests as low priority for the duration."""
        prev = getattr(_thread, "background", False)
        _thread.background = True
        try:
            yield
        finally:
            _thread.background = prev

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, session: Any, url: str, **kwargs: Any) -> Any:
        self._throttle()
        try:
            return session.get(url, timeout=self._timeout, **kwargs)
        except Exception as exc:  # curl_cffi raises its own transport errors
            raise NseError(f"Network error for {url}: {type(exc).__name__}: {exc}") from exc

    def _warm(self) -> None:
        self._session = None
        session = self._session_factory()
        resp = self._get(session, BASE + "/")
        if resp.status_code != 200:
            raise NseError(f"NSE home page returned HTTP {resp.status_code}")
        self._session = session  # only keep a session that warmed up successfully

    def _fetch(self, url: str) -> Any:
        if getattr(_thread, "background", False):
            with self._fg_cond:
                self._fg_cond.wait_for(lambda: self._fg_waiting == 0)
            return self._fetch_locked(url)
        with self._fg_cond:
            self._fg_waiting += 1
        try:
            return self._fetch_locked(url)
        finally:
            with self._fg_cond:
                self._fg_waiting -= 1
                self._fg_cond.notify_all()

    def _fetch_locked(self, url: str) -> Any:
        """GET with re-warm on 401/403 and backoff on 429/5xx/network errors."""
        with self._lock:
            rewarmed = False
            last_error: NseError | None = None
            for attempt in range(MAX_ATTEMPTS):
                if self._session is None:
                    self._warm()
                try:
                    resp = self._get(self._session, url, headers={"Referer": BASE + "/"})
                except NseError as exc:
                    last_error = exc
                    time.sleep(self._backoff * (attempt + 1))
                    continue
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 404:
                    raise NseNotFound(f"HTTP 404 for {url}")
                if resp.status_code in (401, 403) and not rewarmed:
                    rewarmed = True
                    self._warm()  # cookie expired; get a fresh session once
                    continue
                last_error = NseError(f"HTTP {resp.status_code} for {url}: {resp.text[:200]}")
                if resp.status_code not in RETRY_STATUS:
                    raise last_error
                time.sleep(self._backoff * (attempt + 1))
            raise last_error or NseError(f"Gave up on {url}")

    def get_text(
        self, url: str, ttl: float | None, validate: Callable[[str], bool] | None = None
    ) -> str:
        key = f"nse:{url}"
        if self._cache and (hit := self._cache.get(key)) is not None:
            return hit
        text = self._fetch(url).text
        if validate and not validate(text):
            raise NseError(f"Unexpected response body for {url}: {text[:200]!r}")
        if self._cache:
            self._cache.set(key, text, ttl)
        return text

    def forget_json(self, path: str) -> None:
        """Drop a cached API response so the next get_json fetches it fresh."""
        if self._cache:
            self._cache.delete(f"nse:{API + path}")

    def get_json(self, path: str, ttl: float | None) -> Any:
        url = API + path
        key = f"nse:{url}"
        if self._cache and (hit := self._cache.get(key)) is not None:
            return json.loads(hit)
        text = self._fetch(url).text
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NseError(f"Non-JSON response for {path}: {text[:200]!r}") from exc
        if self._cache:
            empty = payload in ([], {}) or (isinstance(payload, dict) and payload.get("data") == [])
            self._cache.set(key, text, EMPTY_TTL if empty else ttl)
        return payload

    def get_bytes(self, url: str) -> bytes:
        return self._fetch(url).content
