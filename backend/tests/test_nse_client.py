from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from eqr.cache import Cache
from eqr.nse_client import NseClient, NseError, NseNotFound, looks_like_xbrl


@dataclass
class FakeResp:
    status_code: int
    text: str = ""

    @property
    def content(self) -> bytes:
        return self.text.encode()


class FakeSession:
    """Replays queued responses; the home page always succeeds unless told otherwise."""

    def __init__(self, responses: list, home_status: int = 200) -> None:
        self.responses = responses
        self.home_status = home_status
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> FakeResp:
        self.calls.append(url)
        if url.rstrip("/") == "https://www.nseindia.com":
            return FakeResp(self.home_status, "<html>home</html>")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(
    tmp_path: Path, responses: list, home_status: int = 200
) -> tuple[NseClient, FakeSession, Cache]:
    session = FakeSession(responses, home_status)
    cache = Cache(tmp_path / "c.sqlite")
    client = NseClient(cache=cache, min_interval=0, session_factory=lambda: session, backoff=0)
    return client, session, cache


XBRL = (
    '<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"></xbrli:xbrl>'
)


def test_html_error_page_not_cached_as_xbrl(tmp_path: Path) -> None:
    client, _, cache = make(tmp_path, [FakeResp(200, "<html>Access Denied</html>")])
    with pytest.raises(NseError):
        client.get_text("https://x/f.xml", ttl=None, validate=looks_like_xbrl)
    assert cache.get("nse:https://x/f.xml") is None


def test_valid_xbrl_cached(tmp_path: Path) -> None:
    client, session, _ = make(tmp_path, [FakeResp(200, XBRL)])
    assert client.get_text("https://x/f.xml", ttl=None, validate=looks_like_xbrl) == XBRL
    assert client.get_text("https://x/f.xml", ttl=None, validate=looks_like_xbrl) == XBRL
    assert session.calls.count("https://x/f.xml") == 1


def test_non_json_not_cached(tmp_path: Path) -> None:
    client, _, cache = make(tmp_path, [FakeResp(200, "<html>blocked</html>")])
    with pytest.raises(NseError):
        client.get_json("some-api", ttl=3600)
    assert cache.get("nse:https://www.nseindia.com/api/some-api") is None


def test_empty_json_cached_briefly_not_for_full_ttl(tmp_path: Path) -> None:
    client, _, cache = make(tmp_path, [FakeResp(200, "[]")])
    assert client.get_json("list-api", ttl=6 * 3600) == []
    row = cache._conn.execute("SELECT ttl FROM kv").fetchone()
    assert row[0] < 3600


def test_failed_warmup_is_not_remembered(tmp_path: Path) -> None:
    session = FakeSession([FakeResp(200, "{}")], home_status=403)
    client = NseClient(min_interval=0, session_factory=lambda: session, backoff=0)
    with pytest.raises(NseError):
        client.get_json("a", ttl=None)
    session.home_status = 200
    assert client.get_json("a", ttl=None) == {}


def test_404_raises_not_found(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, [FakeResp(404, "nope")])
    with pytest.raises(NseNotFound):
        client.get_bytes("https://x/file.zip")


def test_transport_error_wrapped(tmp_path: Path) -> None:
    client, _, _ = make(
        tmp_path,
        [ConnectionError("reset"), ConnectionError("reset"), ConnectionError("reset")],
    )
    with pytest.raises(NseError):
        client.get_json("a", ttl=None)


def test_retries_5xx_then_succeeds(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, [FakeResp(503, "busy"), FakeResp(200, '{"ok": 1}')])
    assert client.get_json("a", ttl=None) == {"ok": 1}


def test_403_rewarms_once_then_succeeds(tmp_path: Path) -> None:
    client, session, _ = make(tmp_path, [FakeResp(403, "denied"), FakeResp(200, '{"ok": 1}')])
    assert client.get_json("a", ttl=None) == {"ok": 1}
    assert session.calls.count("https://www.nseindia.com/") == 2


def test_background_requests_yield_to_waiting_foreground() -> None:
    import threading
    import time as _t

    from eqr.nse_client import NseClient

    class Resp:
        status_code = 200
        text = "ok"

    class Session:
        def get(self, url, **kw):
            return Resp()

    c = NseClient(min_interval=0, session_factory=Session)
    done = threading.Event()

    def bg():
        with c.background():
            c._fetch("https://x/bg")
        done.set()

    with c._fg_cond:
        c._fg_waiting = 1  # a page request is waiting
    t = threading.Thread(target=bg)
    t.start()
    _t.sleep(0.2)
    assert not done.is_set()  # the scan held back
    with c._fg_cond:
        c._fg_waiting = 0
        c._fg_cond.notify_all()
    t.join(2)
    assert done.is_set()
