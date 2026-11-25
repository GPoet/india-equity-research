"""Claude through the local Claude Code CLI (`claude -p`), on the user's own subscription.

Personal use only: the CLI authenticates with the user's login on this machine; no token
is copied into the app. Swap in an API-key provider later by implementing LlmProvider.

Failure contract (see memory: reference_claude_cli_headless_failures): the CLI can report
an API failure as a normal-looking reply, so success requires positive proof: a `result`
event, is_error false, and structured output present. Raw upstream error text is never
returned as content.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TIMEOUT = 600  # seconds; research with web search takes minutes


class LlmError(RuntimeError):
    """kind: auth_expired | auth_entitlement | rate_limit | upstream | timeout |
    invalid_output | cli_missing | cli_failed"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class LlmResult:
    data: dict[str, Any]
    cost_usd: float | None  # API-equivalent cost the CLI reports; not billed on a subscription
    duration_ms: int | None
    num_turns: int | None
    web_searches: int
    web_fetches: int


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
    if status == 401:
        return "auth_expired"
    if status == 403:
        return "auth_entitlement"
    if status == 429:
        return "rate_limit"
    return "upstream"


class ClaudeCliProvider:
    def __init__(
        self,
        workdir: Path,
        binary: str = "claude",
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        # A clean, empty working directory: no CLAUDE.md, no project settings get picked up.
        self._workdir = workdir
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
            "json",
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
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._workdir,
            )
        except FileNotFoundError as exc:
            raise LlmError("cli_missing", "Claude Code CLI not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise LlmError("timeout", f"Claude did not finish within {timeout}s") from exc

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            kind = "cli_failed" if proc.returncode else "invalid_output"
            raise LlmError(kind, f"Claude CLI returned no JSON (exit {proc.returncode})") from exc

        if not isinstance(payload, dict) or payload.get("type") != "result":
            raise LlmError("invalid_output", "Claude CLI output had no result event")
        status = payload.get("api_error_status")
        if payload.get("is_error") or status:
            kind = _classify(status)
            raise LlmError(kind, _MESSAGES[kind])
        data = payload.get("structured_output")
        if not isinstance(data, dict):
            raise LlmError(
                "invalid_output", "Claude replied without the requested structured output"
            )
        tool_use = (payload.get("usage") or {}).get("server_tool_use") or {}
        return LlmResult(
            data=data,
            cost_usd=payload.get("total_cost_usd"),
            duration_ms=payload.get("duration_ms"),
            num_turns=payload.get("num_turns"),
            web_searches=int(tool_use.get("web_search_requests") or 0),
            web_fetches=int(tool_use.get("web_fetch_requests") or 0),
        )
