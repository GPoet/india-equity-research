"""Small SQLite key-value cache with per-entry TTL.

ttl=None means the value never expires (used for filed documents, which do
not change once published; revisions arrive under a new URL).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


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
        return value

    def set(self, key: str, value: str, ttl: float | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value, stored_at, ttl) VALUES (?, ?, ?, ?)",
                (key, value, time.time(), ttl),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
