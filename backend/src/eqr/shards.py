"""Splitting the daily scan across parallel jobs (GitHub Actions runners, each on its own IP,
so the polite per-address request rate multiplies) and merging their results.

Each job scans the companies whose key hashes to its slice, then exports only what it added:
new cache rows, its company files and its scan progress. The merge step folds every slice into
the shared data and marks the scan complete when every slice finished."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zlib
from pathlib import Path
from typing import Any

from eqr.scan import rank


def in_shard(key: str, shard: tuple[int, int] | None) -> bool:
    if shard is None:
        return True
    index, count = shard
    return zlib.crc32(key.encode("utf-8")) % count == index


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def export_delta(data_dir: Path, out: Path, since: float) -> None:
    """Copy what this job added since `since` into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    delta = out / "delta.sqlite"
    delta.unlink(missing_ok=True)
    with sqlite3.connect(delta) as conn:
        conn.execute(f"ATTACH DATABASE '{data_dir / 'cache.sqlite'}' AS src")
        conn.execute("CREATE TABLE kv AS SELECT * FROM src.kv WHERE stored_at >= ?", (since,))
        conn.commit()
        conn.execute("DETACH DATABASE src")
    companies = data_dir / "scan" / "companies"
    if companies.exists():
        for f in companies.glob("*.json"):
            if f.stat().st_mtime >= since:
                (out / "companies").mkdir(exist_ok=True)
                shutil.copy2(f, out / "companies" / f.name)
    for name in ("current.json", "industries.json"):
        src = data_dir / "scan" / name
        if src.exists():
            shutil.copy2(src, out / name)


def merge(data_dir: Path, deltas: list[Path]) -> dict[str, Any]:
    """Fold slices into data_dir. Returns the combined scan result."""
    cache = data_dir / "cache.sqlite"
    with sqlite3.connect(cache) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, stored_at REAL NOT NULL, ttl REAL)"
        )
        for d in deltas:
            if (d / "delta.sqlite").exists():
                conn.execute(f"ATTACH DATABASE '{d / 'delta.sqlite'}' AS part")
                conn.execute("INSERT OR REPLACE INTO kv SELECT * FROM part.kv")
                conn.commit()
                conn.execute("DETACH DATABASE part")
    scan_dir = data_dir / "scan"
    (scan_dir / "companies").mkdir(parents=True, exist_ok=True)
    industries: dict[str, str] = {}
    if (scan_dir / "industries.json").exists():
        industries = json.loads((scan_dir / "industries.json").read_text())
    parts = []
    for d in deltas:
        if (d / "companies").exists():
            for f in (d / "companies").glob("*.json"):
                shutil.copy2(f, scan_dir / "companies" / f.name)
        if (d / "industries.json").exists():
            industries.update(json.loads((d / "industries.json").read_text()))
        if (d / "current.json").exists():
            parts.append(json.loads((d / "current.json").read_text()))
    _write(scan_dir / "industries.json", industries)
    if not parts:
        return {"complete": False, "rows": [], "total": 0, "nothing_new": True}
    day = max(p["price_day"] for p in parts)
    same_day = [p for p in parts if p["price_day"] == day]
    rows: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for p in same_day:
        for r in p.get("rows", []):
            rows[r.get("key", r["symbol"])] = r
        errors.update(p.get("errors", {}))
    complete = len(same_day) == len(deltas) and all(p.get("complete") for p in same_day)
    picks, ranked = rank(list(rows.values()))
    result = {
        **same_day[0],
        "price_day": day,
        "complete": complete,
        "scanned": len(rows),
        "total": sum(p.get("total", 0) for p in same_day),
        "errors": errors,
        "picks": picks,
        "ranked": ranked,
        "unranked": [r for r in rows.values() if not r.get("forecast")],
        "rows": list(rows.values()),
    }
    _write(scan_dir / "current.json", result)
    if complete:
        _write(scan_dir / "latest.json", result)
        _write(scan_dir / "history" / f"{day}.json", result)
    return result
