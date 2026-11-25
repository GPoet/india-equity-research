"""Ask Grok what X (Twitter) is saying about a company, in a cost-capped, sourced way."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from eqr.llm.xai import XaiError, XaiResult
from eqr.sentiment.schema import SentimentReport, clean_sentiment, xai_schema

WINDOW_DAYS = 30

SYSTEM = """You analyse what people on X (Twitter) say about companies listed in India, for one
private investor. Use the X search tool. Report sentiment honestly; do not give buy/sell advice.
Weigh credible voices (the company, journalists, known analysts and fund managers) above anonymous
accounts. Treat coordinated promotion, many new or low-follower accounts pushing the same message,
price targets with no reasoning, or Telegram/WhatsApp tip links as pump risk, never as bullish
evidence; SEBI has acted against such schemes. Quote only posts you actually retrieved, by URL.
"""


class _Xai(Protocol):
    def x_search_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        from_date: date,
        to_date: date,
        system: str | None = None,
        note: str = "",
    ) -> XaiResult: ...


@dataclass(frozen=True)
class SentimentRun:
    report: SentimentReport
    dropped: dict[str, int]
    meta: dict[str, Any]


def build_prompt(
    name: str, symbol: str, industry: str | None, today: date, days: int = WINDOW_DAYS
) -> str:
    start = today - timedelta(days=days)
    return f"""Today is {today.isoformat()}. Company: {name}, NSE symbol {symbol}{f", industry {industry}" if industry else ""}.

Search X for posts about this company from {start.isoformat()} to today: its name, common short
names, the NSE symbol, and its management. Then report:
- overall sentiment and a score from -2 (very bearish) to 2 (very bullish);
- whether posting volume looks low, normal or high for this company, and why;
- the main themes people discuss, each with its stance and the URLs of example posts;
- up to 8 notable posts (URL, author handle, author type, stance, one-line summary);
- pump risk (low/medium/high) with the specific signals you saw;
- anything you could not determine.
"""


def run_sentiment(
    client: _Xai, name: str, symbol: str, industry: str | None, today: date, days: int = WINDOW_DAYS
) -> SentimentRun:
    start, end = today - timedelta(days=days), today + timedelta(days=1)  # to_date is exclusive
    result = client.x_search_json(
        build_prompt(name, symbol, industry, today, days),
        xai_schema(),
        start,
        end,
        system=SYSTEM,
        note=symbol,
    )
    try:
        report = SentimentReport.model_validate(result.data)
    except ValidationError as exc:
        raise XaiError(
            "invalid_output", f"Grok output failed validation ({exc.error_count()} errors)"
        ) from exc
    cleaned, dropped = clean_sentiment(report, result.cited_urls)
    meta = {
        "as_of": today.isoformat(),
        "window_days": days,
        "posts_fetched": result.posts_fetched,
        "searches": result.searches,
        "cost_usd": result.cost_usd,
        "sources_cited": len(result.cited_urls),
    }
    return SentimentRun(cleaned, dropped, meta)
