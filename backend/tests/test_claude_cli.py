import json
import subprocess
from pathlib import Path

import pytest

from eqr.llm.claude_cli import ClaudeCliProvider, LlmError

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def fake(stdout: str, returncode: int = 0, raise_timeout: bool = False):
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        if raise_timeout:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return runner, calls


def ok_payload(**extra) -> str:
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "structured_output": {"x": 7},
        "result": '{"x": 7}',
        "total_cost_usd": 0.02,
        "duration_ms": 1200,
        "num_turns": 3,
        "usage": {"server_tool_use": {"web_search_requests": 4, "web_fetch_requests": 2}},
    }
    base.update(extra)
    return json.dumps(base)


def provider(runner, tmp_path: Path) -> ClaudeCliProvider:
    return ClaudeCliProvider(workdir=tmp_path, runner=runner, binary="claude")


def test_success_returns_structured_output(tmp_path: Path) -> None:
    runner, calls = fake(ok_payload())
    res = provider(runner, tmp_path).run(
        "prompt text", SCHEMA, tools=("WebSearch",), model="sonnet"
    )
    assert res.data == {"x": 7}
    assert res.web_searches == 4
    args, kwargs = calls[0]
    assert kwargs["input"] == "prompt text"  # prompt goes via stdin, not argv
    assert "--json-schema" in args and "--setting-sources" in args and "--strict-mcp-config" in args
    assert args[args.index("--tools") + 1] == "WebSearch"
    assert kwargs["cwd"] == tmp_path


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "auth_expired"), (403, "auth_entitlement"), (429, "rate_limit"), (529, "upstream")],
)
def test_api_errors_classified(tmp_path: Path, status: int, kind: str) -> None:
    payload = ok_payload(
        is_error=True,
        api_error_status=status,
        structured_output=None,
        result="API Error: something raw",
    )
    runner, _ = fake(payload)
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == kind
    assert "something raw" not in str(err.value)  # raw upstream text never surfaces


def test_missing_structured_output_fails_closed(tmp_path: Path) -> None:
    runner, _ = fake(ok_payload(structured_output=None, result="Sure! Here is some prose."))
    with pytest.raises(LlmError) as err:
        provider(runner, tmp_path).run("p", SCHEMA)
    assert err.value.kind == "invalid_output"


def test_non_json_stdout_fails_closed(tmp_path: Path) -> None:
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
