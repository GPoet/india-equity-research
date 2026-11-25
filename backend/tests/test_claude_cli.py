import json
import subprocess
from pathlib import Path

import pytest

from eqr.llm.claude_cli import ClaudeCliProvider, LlmError, clean_env

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def events(*extra: dict, result: dict | None = None) -> str:
    base_result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "structured_output": {"x": 7},
        "result": "",
        "total_cost_usd": 0.02,
        "duration_ms": 1200,
        "num_turns": 3,
    }
    if result is not None:
        base_result.update(result)
    lines = [{"type": "system", "subtype": "init"}, *extra, base_result]
    return "\n".join(json.dumps(e) for e in lines)


def tool_use(name: str, inp: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "model": "claude-sonnet-5-5",
            "content": [{"type": "tool_use", "id": "t1", "name": name, "input": inp}],
        },
    }


def tool_result(text: str) -> dict:
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": text}]},
    }


SEARCH = tool_use("WebSearch", {"query": "rbi repo"})
SEARCH_RESULT = tool_result(
    'Links: [{"title":"a","url":"https://www.moneylife.in/article/x/1.html"},{"title":"b","url":"https://rbi.org.in/p?id=2"}]'
)
FETCH = tool_use(
    "WebFetch",
    {"url": "https://www.sebi.gov.in/legal/circulars/nov-2026/x.html", "prompt": "summarise"},
)


def fake(stdout: str, returncode: int = 0, raise_timeout: bool = False):
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        if raise_timeout:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return runner, calls


def provider(runner, tmp_path: Path) -> ClaudeCliProvider:
    return ClaudeCliProvider(workdir=tmp_path, runner=runner, binary="claude")


def test_success_collects_tools_and_seen_urls(tmp_path: Path) -> None:
    runner, calls = fake(events(SEARCH, SEARCH_RESULT, FETCH))
    res = provider(runner, tmp_path).run("prompt text", SCHEMA, tools=("WebSearch", "WebFetch"))
    assert res.data == {"x": 7}
    assert res.tool_calls == {"WebSearch": 1, "WebFetch": 1}
    assert "https://www.moneylife.in/article/x/1.html" in res.seen_urls
    assert "https://rbi.org.in/p?id=2" in res.seen_urls
    assert "https://www.sebi.gov.in/legal/circulars/nov-2026/x.html" in res.seen_urls
    args, kwargs = calls[0]
    assert kwargs["input"] == "prompt text"
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert "--setting-sources" in args and "--strict-mcp-config" in args


def test_structured_output_tool_not_counted(tmp_path: Path) -> None:
    runner, _ = fake(events(SEARCH, tool_use("StructuredOutput", {"x": 7})))
    res = provider(runner, tmp_path).run("p", SCHEMA)
    assert res.tool_calls == {"WebSearch": 1}


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "auth_expired"), (403, "auth_entitlement"), (429, "rate_limit"), (529, "upstream")],
)
def test_api_errors_classified(tmp_path: Path, status: int, kind: str) -> None:
    out = events(
        result={
            "is_error": True,
            "api_error_status": status,
            "structured_output": None,
            "result": "API Error: something raw",
        }
    )
    runner, _ = fake(out)
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == kind
    assert "something raw" not in str(err.value)


def test_synthetic_error_turn_detected(tmp_path: Path) -> None:
    synthetic = {
        "type": "assistant",
        "error": "authentication_failed",
        "message": {
            "model": "<synthetic>",
            "content": [{"type": "text", "text": "Failed to authenticate. 401"}],
        },
    }
    runner, _ = fake(
        events(
            synthetic, result={"is_error": True, "api_error_status": 401, "structured_output": None}
        )
    )
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == "auth_expired"


def test_missing_result_event_fails_closed(tmp_path: Path) -> None:
    runner, _ = fake(json.dumps({"type": "system", "subtype": "init"}))
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == "invalid_output"


def test_missing_structured_output_fails_closed(tmp_path: Path) -> None:
    runner, _ = fake(events(result={"structured_output": None, "result": "Sure! prose"}))
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == "invalid_output"


def test_garbage_stdout_fails_closed(tmp_path: Path) -> None:
    runner, _ = fake("Failed to authenticate. API Error: 401", returncode=1)
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind in ("invalid_output", "cli_failed")


def test_timeout(tmp_path: Path) -> None:
    runner, _ = fake("", raise_timeout=True)
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA, timeout=1)
    assert err.value.kind == "timeout"


def test_missing_binary(tmp_path: Path) -> None:
    def runner(args, **kwargs):
        raise FileNotFoundError("claude")

    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == "cli_missing"


def test_env_drops_api_keys() -> None:
    env = clean_env(
        {"PATH": "/bin", "ANTHROPIC_API_KEY": "sk-x", "ANTHROPIC_AUTH_TOKEN": "t", "HOME": "/h"}
    )
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "/bin"


def test_default_workdir_outside_home() -> None:
    from eqr.llm.claude_cli import default_workdir

    assert not str(default_workdir()).startswith(str(Path.home()))
