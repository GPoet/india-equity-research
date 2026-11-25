import math
import time

import pytest
from fastapi.testclient import TestClient

from eqr.app.api import create_app
from eqr.app.serialize import clean


class FakeServices:
    def __init__(self) -> None:
        self.research_calls = 0
        self.cached = None
        self.fail_company = False
        self.xai_on = False

    def resolve(self, q):
        if q.lower() in ("tcs", "tata consultancy"):
            return {
                "match": {"symbol": "TCS", "name": "Tata Consultancy Services Limited"},
                "candidates": [],
            }
        return {
            "match": None,
            "candidates": [{"symbol": "BAJFINANCE", "name": "Bajaj Finance", "score": 75}],
        }

    def known(self, symbol):
        return symbol == "TCS"

    def company(self, symbol):
        if self.fail_company:
            from eqr.nse_client import NseError

            raise NseError("HTTP 503 for https://www.nseindia.com/api/x")
        return {
            "symbol": symbol,
            "valuation": {"result": {"mid": float("nan"), "signal": "Fairly valued"}},
        }

    def prices(self, symbol, period):
        return {"symbol": symbol, "points": [{"date": "2026-11-20", "close": 2376.2}]}

    def sector(self, symbol):
        return {"sector": {"key": "it"}, "related": []}

    def sectors(self):
        return {"as_of": "2026-11-23", "sectors": [{"key": "it", "rank": 8}]}

    def run_research(self, symbol, model):
        self.research_calls += 1
        time.sleep(0.05)
        return {"symbol": symbol, "report": {"summary": "ok"}}

    def cached_research(self, symbol, model):
        return self.cached

    def journal(self):
        return {"as_of": "2026-11-25", "entries": [], "summary": [], "engine_version": "x"}

    def backtest(self):
        return None

    def overview(self):
        return {"as_of": "2026-11-25", "movers": {}}

    def forecast(self, symbol):
        return {"status": "not_fitted", "error": "run scripts/forecast_fit.py"}

    def sentiment_enabled(self):
        return self.xai_on

    def run_sentiment(self, symbol, kind):
        return {"symbol": symbol, "report": {"overall": "neutral"}}

    def cached_sentiment(self, symbol, kind):
        return None


@pytest.fixture()
def client():
    fake = FakeServices()
    app = create_app(fake)
    with TestClient(app, base_url="http://localhost") as c:
        c.fake = fake
        yield c


def test_health(client) -> None:
    assert client.get("/api/health").json()["ok"] is True


def test_resolve(client) -> None:
    assert client.get("/api/resolve", params={"q": "tcs"}).json()["match"]["symbol"] == "TCS"
    assert client.get("/api/resolve", params={"q": "bajaj"}).json()["match"] is None


def test_resolve_requires_query(client) -> None:
    assert client.get("/api/resolve", params={"q": " "}).status_code == 422


def test_company_nan_becomes_null(client) -> None:
    r = client.get("/api/company/TCS")
    assert r.status_code == 200
    assert r.json()["valuation"]["result"]["mid"] is None


def test_unknown_symbol_404(client) -> None:
    assert client.get("/api/company/NOPE").status_code == 404
    assert client.get("/api/company/NOPE/sector").status_code == 404


def test_research_job_lifecycle(client) -> None:
    assert client.get("/api/company/TCS/research").json()["status"] == "none"
    started = client.post("/api/company/TCS/research", headers={"X-Equity-Desk": "1"}).json()
    assert started["status"] in ("queued", "running", "done")
    again = client.post(
        "/api/company/TCS/research", headers={"X-Equity-Desk": "1"}
    ).json()  # no duplicate job while running
    for _ in range(50):
        state = client.get("/api/company/TCS/research").json()
        if state["status"] == "done":
            break
        time.sleep(0.02)
    assert state["status"] == "done"
    assert state["data"]["report"]["summary"] == "ok"
    assert client.fake.research_calls == 1
    assert again["status"] in ("queued", "running", "done")


def test_clean_handles_nested_nan_and_inf() -> None:
    out = clean({"a": [1.0, float("inf")], "b": {"c": float("nan")}, "d": (2, 3)})
    assert out == {"a": [1.0, None], "b": {"c": None}, "d": [2, 3]}
    assert not any(isinstance(v, float) and math.isnan(v) for v in out["a"] if v is not None)


H = {"X-Equity-Desk": "1"}


def test_post_without_custom_header_rejected(client) -> None:
    r = client.post("/api/company/TCS/research")
    assert r.status_code == 403
    assert client.fake.research_calls == 0


def test_cross_site_post_rejected(client) -> None:
    r = client.post("/api/company/TCS/research", headers={**H, "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/company/TCS/research", headers={**H, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_foreign_host_header_rejected(client) -> None:
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_fresh_cache_served_unless_forced(client) -> None:
    client.fake.cached = {"symbol": "TCS", "report": {"summary": "cached"}}
    r = client.post("/api/company/TCS/research", headers=H).json()
    assert r["status"] == "done" and r.get("cached") is True
    assert client.fake.research_calls == 0


def test_upstream_failure_is_503_with_reason(client) -> None:
    client.fake.fail_company = True
    r = client.get("/api/company/TCS")
    assert r.status_code == 503
    assert "NSE" in r.json()["detail"]


def test_memo_caches_failure_briefly() -> None:
    from eqr.app.services import _Memo

    memo, calls = _Memo(), []

    def boom():
        calls.append(1)
        raise RuntimeError("down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            memo.get("k", 60, boom)
    assert len(calls) == 1


def test_journal_endpoint(client) -> None:
    assert client.get("/api/journal").json()["entries"] == []


def test_backtest_missing_is_404_with_instructions(client) -> None:
    r = client.get("/api/backtest")
    assert r.status_code == 404
    assert "scripts/backtest.py" in r.json()["detail"]


def test_sentiment_disabled_without_key(client) -> None:
    r = client.get("/api/company/TCS/sentiment").json()
    assert r["status"] == "disabled" and "XAI_API_KEY" in r["error"]
    r = client.post("/api/company/TCS/sentiment", headers=H).json()
    assert r["status"] == "disabled"


def test_sentiment_runs_when_enabled(client) -> None:
    client.fake.xai_on = True
    assert client.post("/api/company/TCS/sentiment").status_code == 403  # same CSRF guard
    started = client.post("/api/company/TCS/sentiment", headers=H).json()
    assert started["status"] in ("queued", "running", "done")


def test_forecast_endpoint(client) -> None:
    r = client.get("/api/company/TCS/forecast")
    assert r.status_code == 200 and r.json()["status"] == "not_fitted"


def test_overview_endpoint(client) -> None:
    assert client.get("/api/overview").json()["as_of"] == "2026-11-25"
