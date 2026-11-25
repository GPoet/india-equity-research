"""Claude through the local Claude Code CLI (`claude -p`), on the user's own subscription.

Personal use only: the CLI authenticates with the user's login on this machine; no token
is copied into the app. Swap in an API-key provider later by implementing LlmProvider.

Isolation: runs in an empty directory outside $HOME (so no CLAUDE.md is discovered), with
no user settings, hooks, plugins or MCP servers, and with API-key variables removed from
the environment so a stray key cannot switch billing away from the subscription.

Failure contract (memory: reference_claude_cli_headless_failures): the CLI can report an
API failure as a normal-looking reply, so success needs positive proof: a `result` event,
is_error false, structured output present. Raw upstream error text is never returned.

Output is stream-json so we can see which tools ran and which URLs they returned; the
research layer uses that to reject sources the model never actually saw.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TIMEOUT = 900  # seconds; research with web search takes minutes
_URL = re.compile(r"https?://[^\s\"'<>\\\]\)]+")
_STRIP_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)
_INTERNAL_TOOLS = {"StructuredOutput"}


class LlmError(RuntimeError):
    """kind: auth_expired | auth_entitlement | rate_limit | upstream | timeout |
    invalid_output | no_research | cli_missing | cli_failed"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class LlmResult:
    data: dict[str, Any]
    cost_usd: float | None  # API-equivalent cost the CLI reports; not billed on a subscription
    duration_ms: int | None
    num_turns: int | None
    tool_calls: dict[str, int] = field(default_factory=dict)
    seen_urls: frozenset[str] = frozenset()  # URLs returned by or requested through tools


class LlmProvider(Protocol):
    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system: str | None = None,
        tools: Sequence[str] = (),
        model: str = "sonnet",
        effort: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> LlmResult: ...


_MESSAGES = {
    "auth_expired": "Claude login expired: run `claude` once in a terminal and log in again",
    "auth_entitlement": (
        "Claude refused this account (403): the login is not on a plan that allows Claude Code. "
        "Logging in again with the same account will not help; check which account/org is active"
    ),
    "rate_limit": "Claude usage limit reached for now; try again later",
    "upstream": "Claude service error; try again in a few minutes",
}


def _classify(status: int | None) -> str:
    return {401: "auth_expired", 403: "auth_entitlement", 429: "rate_limit"}.get(
        status or 0, "upstream"
    )


def clean_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _STRIP_ENV}


def default_workdir() -> Path:
    return Path(tempfile.gettempdir()) / "eqr-claude-workdir"


def run_in_process_group(
    args: list[str], *, input: str, timeout: int, cwd: Path, env: dict[str, str]
):
    """subprocess.run, but a timeout kills the whole process group (tool subprocesses too)."""
    with subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    ) as proc:
        try:
            out, err = proc.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise
        return subprocess.CompletedProcess(args, proc.returncode, stdout=out, stderr=err)


def _norm(url: str) -> str:
    return url.rstrip(".,;:").split("#")[0]


@dataclass
class _Stream:
    result: dict[str, Any] | None = None
    tools: Counter = field(default_factory=Counter)
    urls: set[str] = field(default_factory=set)
    synthetic_error: bool = False

    def feed(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "result":
            self.result = event
        elif kind == "assistant":
            msg = event.get("message") or {}
            if msg.get("model") == "<synthetic>" or event.get("error"):
                self.synthetic_error = True
            for block in msg.get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") not in _INTERNAL_TOOLS:
                    self.tools[block.get("name")] += 1
                    url = (block.get("input") or {}).get("url")
                    if isinstance(url, str):
                        self.urls.add(_norm(url))
        elif kind == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    text = json.dumps(block.get("content"))
                    self.urls.update(_norm(u) for u in _URL.findall(text.replace('\\"', '"')))


class ClaudeCliProvider:
    def __init__(
        self,
        workdir: Path | None = None,
        binary: str = "claude",
        runner: Callable[..., subprocess.CompletedProcess[str]] = run_in_process_group,
    ) -> None:
        self._workdir = workdir or default_workdir()
        self._binary = binary
        self._runner = runner

    def _args(
        self,
        schema: dict[str, Any],
        system: str | None,
        tools: Sequence[str],
        model: str,
        effort: str | None,
    ) -> list[str]:
        args = [
            self._binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(schema),
            "--model",
            model,
            "--tools",
            ",".join(tools),
            "--setting-sources",
            "",  # no user hooks/plugins (OMC, claude-mem) in research runs
            "--strict-mcp-config",  # and no MCP servers
            "--no-session-persistence",
        ]
        if tools:
            args += ["--allowedTools", *tools]  # pre-approve: there is no one to click "allow"
        if system:
            args += ["--append-system-prompt", system]
        if effort:
            args += ["--effort", effort]
        return args

    def run(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system: str | None = None,
        tools: Sequence[str] = (),
        model: str = "sonnet",
        effort: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> LlmResult:
        self._workdir.mkdir(parents=True, exist_ok=True)
        try:
            proc = self._runner(
                self._args(schema, system, tools, model, effort),
                input=prompt,
                timeout=timeout,
                cwd=self._workdir,
                env=clean_env(os.environ),
            )
        except FileNotFoundError as exc:
            raise LlmError("cli_missing", "Claude Code CLI not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise LlmError("timeout", f"Claude did not finish within {timeout}s") from exc

        stream = _Stream()
        for line in (proc.stdout or "").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                stream.feed(event)

        payload = stream.result
        if payload is None:
            kind = "cli_failed" if proc.returncode else "invalid_output"
            raise LlmError(kind, f"Claude CLI produced no result (exit {proc.returncode})")
        status = payload.get("api_error_status")
        if payload.get("is_error") or status or stream.synthetic_error:
            kind = _classify(status)
            raise LlmError(kind, _MESSAGES[kind])
        data = payload.get("structured_output")
        if not isinstance(data, dict):
            raise LlmError(
                "invalid_output", "Claude replied without the requested structured output"
            )
        return LlmResult(
            data=data,
            cost_usd=payload.get("total_cost_usd"),
            duration_ms=payload.get("duration_ms"),
            num_turns=payload.get("num_turns"),
            tool_calls=dict(stream.tools),
            seen_urls=frozenset(stream.urls),
        )
