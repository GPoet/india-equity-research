"""Grok via xAI's Responses API with the server-side X search tool, for social sentiment.

Docs (read 25 Nov 2026): POST https://api.x.ai/v1/responses, tool {"type": "x_search"} with
from_date/to_date (YYYY-MM-DD, to_date exclusive), structured output via text.format
json_schema, citations as url_citation annotations, usage.server_side_tool_usage_details
.x_posts_fetched. X search is billed per post fetched ($5 per 1,000) on top of tokens.

Spending is capped: every call's cost is written to a local ledger and a call is refused
once the month's spend reaches the budget (XAI_MONTHLY_BUDGET_USD, default $10).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.7"
# grok-4.7 list prices (USD), prompts under 200k tokens; X posts billed per item fetched.
PRICE_INPUT = 2.00 / 1e6
PRICE_OUTPUT = 6.00 / 1e6
PRICE_POST = 5.00 / 1000
PRICE_PROFILE = 10.00 / 1000
MAX_TURNS = 4
# Charged when a call's real cost is unknown (timeout, error after the request was sent, no
# usage in the reply), and kept free under the budget before each call: spending fails closed.
CALL_RESERVE_USD = 0.50


class XaiError(RuntimeError):
    """kind: no_key | budget | auth | rate_limit | upstream | invalid_output | network"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class XaiResult:
    data: dict[str, Any]
    cited_urls: frozenset[str]
    posts_fetched: int
    searches: int
    cost_usd: float


class SpendLedger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS spend (at REAL, month TEXT, usd REAL, note TEXT)"
            )
            self._conn.commit()

    def month_total(self, month: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(usd), 0) FROM spend WHERE month = ?", (month,)
            ).fetchone()
        return float(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add(self, usd: float, note: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO spend VALUES (?, ?, ?, ?)",
                (time.time(), datetime.now().strftime("%Y-%m"), usd, note),
            )
            self._conn.commit()


def _cost(usage: dict[str, Any]) -> float:
    ticks = usage.get("cost_in_usd_ticks")
    if isinstance(ticks, (int, float)) and ticks > 0:
        return ticks / 1e10  # xAI: 10,000,000,000 ticks per dollar
    tools = usage.get("server_side_tool_usage_details") or {}
    if not usage.get("input_tokens") and not tools:
        return CALL_RESERVE_USD  # no usage reported: assume the worst, not zero
    return (
        (usage.get("input_tokens") or 0) * PRICE_INPUT
        + (usage.get("output_tokens") or 0) * PRICE_OUTPUT
        + (tools.get("x_posts_fetched") or 0) * PRICE_POST
        + (tools.get("x_users_fetched") or 0) * PRICE_PROFILE
    )


class XaiClient:
    def __init__(
        self,
        api_key: str,
        ledger: SpendLedger | None,
        monthly_budget_usd: float,
        model: str = DEFAULT_MODEL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 180.0,
    ) -> None:
        if not api_key:
            raise XaiError("no_key", "No xAI API key: add XAI_API_KEY to backend/.env")
        self._ledger = ledger
        self._budget = monthly_budget_usd
        self._model = model
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()
        if self._ledger:
            self._ledger.close()

    def _charge(self, usd: float, note: str) -> None:
        if self._ledger:
            self._ledger.add(usd, note)

    def month_spend(self) -> float:
        return self._ledger.month_total(datetime.now().strftime("%Y-%m")) if self._ledger else 0.0

    def x_search_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        from_date: date,
        to_date: date,
        system: str | None = None,
        note: str = "",
    ) -> XaiResult:
        spent = self.month_spend()
        if spent + CALL_RESERVE_USD > self._budget:
            raise XaiError(
                "budget",
                f"Monthly xAI budget of ${self._budget:.2f} reached (${spent:.2f} spent, "
                f"${CALL_RESERVE_USD:.2f} kept free per call)",
            )
        body = {
            "model": self._model,
            "input": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "type": "x_search",
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "report",
                    "schema": schema,
                    "strict": True,
                }
            },
            "max_turns": MAX_TURNS,
        }
        try:
            resp = self._http.post("/responses", json=body)
        except httpx.TimeoutException as exc:
            self._charge(CALL_RESERVE_USD, f"{note} (timed out; cost unknown)")
            raise XaiError("network", "xAI did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise XaiError("network", f"Could not reach xAI: {type(exc).__name__}") from exc
        if resp.status_code in (401, 403):
            raise XaiError(
                "auth", "xAI rejected the API key (check XAI_API_KEY and the account's credits)"
            )
        if resp.status_code == 429:
            raise XaiError("rate_limit", "xAI rate limit reached; try again shortly")
        if resp.status_code >= 400:
            if resp.status_code >= 500:
                self._charge(CALL_RESERVE_USD, f"{note} (HTTP {resp.status_code}; cost unknown)")
            raise XaiError("upstream", f"xAI error HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            self._charge(CALL_RESERVE_USD, f"{note} (unreadable reply; cost unknown)")
            raise XaiError("upstream", "xAI returned something that is not JSON") from exc
        usage = payload.get("usage") or {}
        cost = _cost(usage)
        self._charge(cost, note)  # billed even if the output turns out unusable
        message = next((o for o in payload.get("output") or [] if o.get("type") == "message"), None)
        texts = [c for c in (message or {}).get("content") or [] if c.get("type") == "output_text"]
        if not texts:
            raise XaiError("invalid_output", "Grok returned no text")
        try:
            data = json.loads(texts[0]["text"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise XaiError("invalid_output", "Grok did not return the requested JSON") from exc
        if not isinstance(data, dict):
            raise XaiError("invalid_output", "Grok returned JSON that is not an object")
        urls = {
            a.get("url")
            for c in texts
            for a in c.get("annotations") or []
            if a.get("type") == "url_citation"
        }
        for c in payload.get("citations") or []:  # top-level list, when present
            if isinstance(c, str):
                urls.add(c)
            elif isinstance(c, dict) and c.get("url"):
                urls.add(c["url"])
        tools = usage.get("server_side_tool_usage_details") or {}
        return XaiResult(
            data=data,
            cited_urls=frozenset(u for u in urls if u),
            posts_fetched=int(tools.get("x_posts_fetched") or 0),
            searches=int(tools.get("x_search_calls") or 0),
            cost_usd=cost,
        )
