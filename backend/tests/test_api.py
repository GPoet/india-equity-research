import math
import time

import pytest
from fastapi.testclient import TestClient

from eqr.app.api import create_app
from eqr.app.serialize import clean


class FakeServices:
    def __init__(self) -> None:
        self.research_calls = 0

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
        return None


@pytest.fixture()
def client():
    fake = FakeServices()
    app = create_app(fake)
    with TestClient(app) as c:
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
    started = client.post("/api/company/TCS/research").json()
    assert started["status"] in ("running", "done")
    again = client.post("/api/company/TCS/research").json()  # no duplicate job while running
    for _ in range(50):
        state = client.get("/api/company/TCS/research").json()
        if state["status"] == "done":
            break
        time.sleep(0.02)
    assert state["status"] == "done"
    assert state["data"]["report"]["summary"] == "ok"
    assert client.fake.research_calls == 1
    assert again["status"] in ("running", "done")


def test_clean_handles_nested_nan_and_inf() -> None:
    out = clean({"a": [1.0, float("inf")], "b": {"c": float("nan")}, "d": (2, 3)})
    assert out == {"a": [1.0, None], "b": {"c": None}, "d": [2, 3]}
    assert not any(isinstance(v, float) and math.isnan(v) for v in out["a"] if v is not None)
