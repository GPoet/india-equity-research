"""What Grok must return about X/Twitter sentiment, and the post-verification rule:
a post is kept only if its URL was among the sources Grok cited."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from eqr.research.schema import _inline_refs

Stance = Literal["bullish", "neutral", "bearish", "mixed"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Theme(_Strict):
    theme: str
    stance: Stance
    detail: str
    post_urls: list[str]


class Post(_Strict):
    url: str
    author: str
    author_type: Literal[
        "company", "journalist", "analyst", "investor", "retail", "influencer", "unknown"
    ]
    stance: Stance
    summary: str


class PumpRisk(_Strict):
    level: Literal["low", "medium", "high"]
    signals: list[str]


class SentimentReport(_Strict):
    overall: Stance
    score: int = Field(ge=-2, le=2, description="-2 very bearish ... 0 neutral ... 2 very bullish")
    summary: str
    volume: Literal["low", "normal", "high"]
    volume_note: str
    themes: list[Theme]
    notable_posts: list[Post]
    pump_risk: PumpRisk
    data_gaps: list[str]


def _strip(node: Any) -> Any:
    """xAI does not guarantee numeric bounds; enforce them here, not in the request schema."""
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("minimum", "maximum", "title")}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def xai_schema() -> dict[str, Any]:
    return _strip(_inline_refs(SentimentReport.model_json_schema()))


def _norm(url: str) -> str:
    """Same post, however written: twitter.com or x.com, www or not, tracking query dropped."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").removeprefix("www.").removeprefix("mobile.")
    if host == "twitter.com":
        host = "x.com"
    return f"{host}{p.path.rstrip('/')}"


def clean_sentiment(
    report: SentimentReport, cited: set[str] | frozenset[str]
) -> tuple[SentimentReport, dict[str, int]]:
    ok = {_norm(u) for u in cited}
    dropped = {"unverified_posts": 0}
    posts = []
    for p in report.notable_posts:
        if _norm(p.url) in ok:
            posts.append(p)
        else:
            dropped["unverified_posts"] += 1
    themes = [
        t.model_copy(update={"post_urls": [u for u in t.post_urls if _norm(u) in ok]})
        for t in report.themes
    ]
    gaps = list(report.data_gaps)
    if report.notable_posts and not posts:
        gaps.append("None of the quoted posts could be matched to Grok's cited sources")
    return report.model_copy(
        update={"notable_posts": posts, "themes": themes, "data_gaps": gaps}
    ), dropped
