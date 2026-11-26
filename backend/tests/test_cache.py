

def test_large_values_are_compressed_and_round_trip(tmp_path) -> None:
    import sqlite3

    from eqr.cache import Cache

    c = Cache(tmp_path / "c.sqlite")
    big = "<xbrl>" + "<fact>12345</fact>" * 5000 + "</xbrl>"
    c.set("big", big, ttl=None)
    c.set("small", "tiny", ttl=None)
    assert c.get("big") == big and c.get("small") == "tiny"
    raw = sqlite3.connect(tmp_path / "c.sqlite").execute("SELECT value FROM kv WHERE key='big'").fetchone()[0]
    assert len(raw) < len(big) / 5  # stored compressed


def test_old_uncompressed_rows_still_read(tmp_path) -> None:
    import sqlite3
    import time

    from eqr.cache import Cache

    c = Cache(tmp_path / "c.sqlite")
    conn = sqlite3.connect(tmp_path / "c.sqlite")
    conn.execute("INSERT INTO kv VALUES (?, ?, ?, ?)", ("old", "plain text value" * 1000, time.time(), None))
    conn.commit()
    assert c.get("old") == "plain text value" * 1000
