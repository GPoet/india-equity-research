import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from eqr.llm.xai import SpendLedger, XaiClient, XaiError
from eqr.settings import load_env

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def response_body(text: str, annotations=None, usage=None) -> dict:
    return {
        "id": "resp_1",
        "output": [
            {"type": "custom_tool_call", "call_id": "xs_1", "name": "x_keyword_search"},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": text, "annotations": annotations or []}
                ],
            },
        ],
        "usage": usage
        or {
            "input_tokens": 1000,
            "output_tokens": 500,
            "server_side_tool_usage_details": {
                "x_search_calls": 2,
                "x_posts_fetched": 40,
                "x_users_fetched": 0,
            },
        },
    }


def client(handler, tmp_path: Path, budget: float = 10.0) -> XaiClient:
    return XaiClient(
        api_key="k",
        ledger=SpendLedger(tmp_path / "spend.sqlite"),
        monthly_budget_usd=budget,
        transport=httpx.MockTransport(handler),
    )


def test_request_shape_and_parsing(tmp_path: Path) -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json=response_body(
                '{"x": 7}',
                annotations=[
                    {"type": "url_citation", "url": "https://x.com/i/status/1", "title": "1"}
                ],
            ),
        )

    res = client(handler, tmp_path).x_search_json(
        "p", SCHEMA, date(2026, 10, 26), date(2026, 11, 26)
    )
    assert res.data == {"x": 7}
    assert "https://x.com/i/status/1" in res.cited_urls
    assert res.posts_fetched == 40
    assert seen["url"].endswith("/v1/responses")
    assert seen["auth"] == "Bearer k"
    tool = seen["body"]["tools"][0]
    assert tool == {"type": "x_search", "from_date": "2026-10-26", "to_date": "2026-11-26"}
    assert seen["body"]["text"]["format"]["type"] == "json_schema"


def test_spend_recorded_and_budget_enforced(tmp_path: Path) -> None:
    handler = lambda req: httpx.Response(200, json=response_body('{"x": 1}'))  # noqa: E731
    c = client(handler, tmp_path, budget=0.70)
    first = c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert first.cost_usd == pytest.approx(40 * 0.005 + 1000 * 2e-6 + 500 * 6e-6)
    with pytest.raises(XaiError) as err:
        c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert err.value.kind == "budget"


@pytest.mark.parametrize(
    ("status", "kind"), [(401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "upstream")]
)
def test_http_errors(tmp_path: Path, status: int, kind: str) -> None:
    c = client(lambda req: httpx.Response(status, json={"error": "nope"}), tmp_path)
    with pytest.raises(XaiError) as err:
        c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert err.value.kind == kind


def test_non_json_output_fails_closed(tmp_path: Path) -> None:
    c = client(lambda req: httpx.Response(200, json=response_body("Sure, here's prose")), tmp_path)
    with pytest.raises(XaiError) as err:
        c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert err.value.kind == "invalid_output"


def test_missing_key() -> None:
    with pytest.raises(XaiError) as err:
        XaiClient(api_key="", ledger=None, monthly_budget_usd=10)
    assert err.value.kind == "no_key"


def test_load_env_reads_only_listed_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("XAI_API_KEY=abc\n# comment\nXAI_MONTHLY_BUDGET_USD = 25\nOTHER=zzz\n")
    out = load_env(env, ("XAI_API_KEY", "XAI_MONTHLY_BUDGET_USD"))
    assert out == {"XAI_API_KEY": "abc", "XAI_MONTHLY_BUDGET_USD": "25"}


def test_refuses_when_one_more_call_could_exceed_budget(tmp_path: Path) -> None:
    from eqr.llm.xai import CALL_RESERVE_USD

    c = client(
        lambda req: httpx.Response(200, json=response_body('{"x": 1}')),
        tmp_path,
        budget=CALL_RESERVE_USD - 0.01,
    )
    with pytest.raises(XaiError) as err:
        c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert err.value.kind == "budget"


def test_unknown_cost_is_charged_conservatively(tmp_path: Path) -> None:
    from eqr.llm.xai import CALL_RESERVE_USD

    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    c = client(timeout, tmp_path)
    with pytest.raises(XaiError):
        c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert c.month_spend() == pytest.approx(CALL_RESERVE_USD)  # may have been billed

    c2 = client(lambda req: httpx.Response(200, json={"output": []}), tmp_path / "b")
    with pytest.raises(XaiError):
        c2.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert c2.month_spend() == pytest.approx(CALL_RESERVE_USD)  # no usage reported


def test_non_json_body_is_upstream_error(tmp_path: Path) -> None:
    c = client(lambda req: httpx.Response(200, text="<html>"), tmp_path)
    with pytest.raises(XaiError) as err:
        c.x_search_json("p", SCHEMA, date(2026, 11, 1), date(2026, 11, 26))
    assert err.value.kind == "upstream"
