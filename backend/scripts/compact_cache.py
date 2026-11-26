"""Rewrite the cache with large values compressed, then reclaim the space (run with the API stopped)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from eqr.cache import _MARK, _pack

PATH = Path(__file__).resolve().parent.parent / "data" / "cache.sqlite"


def main() -> int:
    before = PATH.stat().st_size
    conn = sqlite3.connect(PATH)
    keys = [k for (k,) in conn.execute("SELECT key FROM kv WHERE length(value) >= 4096")]
    for i, key in enumerate(keys, 1):
        (value,) = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if not value.startswith(_MARK):
            conn.execute("UPDATE kv SET value = ? WHERE key = ?", (_pack(value), key))
        if i % 1000 == 0:
            conn.commit()
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    print(f"{len(keys)} large entries; {before / 1e6:.0f} MB -> {PATH.stat().st_size / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
