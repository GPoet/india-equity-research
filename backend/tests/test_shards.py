import json
import sqlite3
import time
from pathlib import Path

from eqr.cache import Cache
from eqr.shards import export_delta, in_shard, merge


def test_every_key_lands_in_exactly_one_shard() -> None:
    keys = [f"SYM{i}" for i in range(500)] + [f"BSE:{i}" for i in range(500)]
    for k in keys:
        assert sum(in_shard(k, (i, 8)) for i in range(8)) == 1
    counts = [sum(in_shard(k, (i, 8)) for k in keys) for i in range(8)]
    assert min(counts) > 80  # roughly balanced
    assert all(in_shard(k, None) for k in keys)


def scan(path: Path, day: str, rows: list[str], total: int, complete: bool) -> None:
    (path / "scan").mkdir(parents=True, exist_ok=True)
    (path / "scan" / "current.json").write_text(
        json.dumps(
            {
                "price_day": day,
                "complete": complete,
                "total": total,
                "errors": {},
                "rows": [
                    {
                        "key": k,
                        "symbol": k,
                        "turnover": 5e9,
                        "red_flags": [],
                        "forecast": {"1m": {"p_beat_nifty": 0.5}},
                    }
                    for k in rows
                ],
            }
        )
    )


def test_delta_then_merge(tmp_path: Path) -> None:
    base = tmp_path / "base"
    (base / "scan").mkdir(parents=True)
    Cache(base / "cache.sqlite").set("old", "x", ttl=None)
    t0 = time.time()
    # two shards worked on copies of the base
    outs = []
    for i, keys in enumerate((["A"], ["B", "C"])):
        work = tmp_path / f"work{i}"
        (work / "scan" / "companies").mkdir(parents=True)
        c = Cache(work / "cache.sqlite")
        c.set("old", "x", ttl=None)
        sqlite3.connect(work / "cache.sqlite").execute(
            "UPDATE kv SET stored_at = ?", (t0 - 100,)
        ).connection.commit()
        c.set(f"new{i}", "y" * 10, ttl=None)
        for k in keys:
            (work / "scan" / "companies" / f"{k}.json").write_text("{}")
        scan(work, "2026-11-25", keys, total=len(keys), complete=True)
        out = tmp_path / f"delta{i}"
        export_delta(work, out, since=t0)
        outs.append(out)
    with sqlite3.connect(outs[0] / "delta.sqlite") as conn:
        assert [k for (k,) in conn.execute("SELECT key FROM kv")] == ["new0"]  # only what is new
    result = merge(base, outs)
    assert result["complete"] and result["total"] == 3
    assert sorted(r["key"] for r in result["rows"]) == ["A", "B", "C"]
    assert (base / "scan" / "latest.json").exists()
    assert Cache(base / "cache.sqlite").get("new1") == "y" * 10
    assert (base / "scan" / "companies" / "C.json").exists()


def test_merge_incomplete_keeps_latest_untouched(tmp_path: Path) -> None:
    base = tmp_path / "base"
    (base / "scan").mkdir(parents=True)
    (base / "scan" / "latest.json").write_text(json.dumps({"price_day": "2026-11-24"}))
    d = tmp_path / "d0"
    scan(d, "2026-11-25", ["A"], total=4, complete=False)
    result = merge(base, [d])
    assert not result["complete"]
    assert json.loads((base / "scan" / "latest.json").read_text())["price_day"] == "2026-11-24"


def test_a_failed_slice_keeps_the_scan_incomplete(tmp_path: Path) -> None:
    base = tmp_path / "base"
    (base / "scan").mkdir(parents=True)
    d = tmp_path / "d0"
    scan(d, "2026-11-25", ["A"], total=1, complete=True)
    result = merge(base, [d], missing=1)  # the other slice's job failed and uploaded nothing
    assert not result["complete"]
    assert not (base / "scan" / "latest.json").exists()
