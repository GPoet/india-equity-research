"""Small SQLite key-value cache with per-entry TTL.

ttl=None means the value never expires (used for filed documents, which do
not change once published; revisions arrive under a new URL).
"""

from __future__ import annotations

import base64
import sqlite3
import threading
import time
import zlib
from pathlib import Path

COMPRESS_OVER = 4096  # filings are mostly repetitive XML: ~10x smaller compressed
_MARK = "\x00z1:"  # cannot start real text; rows stored before compression read as-is


def _pack(value: str) -> str:
    if len(value) < COMPRESS_OVER:
        return value
    return _MARK + base64.b64encode(zlib.compress(value.encode("utf-8"), 6)).decode("ascii")


def _unpack(value: str) -> str:
    if value.startswith(_MARK):
        return zlib.decompress(base64.b64decode(value[len(_MARK) :])).decode("utf-8")
    return value


class Cache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS kv ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL, ttl REAL)"
            )
            self._conn.commit()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, stored_at, ttl FROM kv WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, stored_at, ttl = row
        if ttl is not None and time.time() - stored_at > ttl:
            with self._lock:  # drop expired rows so the table does not grow forever
                self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                self._conn.commit()
            return None
        return _unpack(value)

    def set(self, key: str, value: str, ttl: float | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, stored_at, ttl) VALUES (?, ?, ?, ?)",
                (key, _pack(value), time.time(), ttl),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
