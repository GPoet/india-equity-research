from datetime import date

import pytest

from eqr.llm.xai import XaiError, XaiResult
from eqr.sentiment.agent import build_prompt, run_sentiment
from eqr.sentiment.schema import SentimentReport, clean_sentiment, xai_schema

TODAY = date(2026, 11, 26)
REAL = "https://x.com/i/status/111"
FAKE = "https://x.com/i/status/999"


def report(**kw):
    base = {
        "overall": "bullish",
        "score": 1,
        "summary": "s",
        "volume": "normal",
        "volume_note": "v",
        "themes": [
            {"theme": "Order wins", "stance": "bullish", "detail": "d", "post_urls": [REAL, FAKE]}
        ],
        "notable_posts": [
            {
                "url": REAL,
                "author": "analyst1",
                "author_type": "analyst",
                "stance": "bullish",
                "summary": "s",
            },
            {
                "url": FAKE,
                "author": "x",
                "author_type": "retail",
                "stance": "bearish",
                "summary": "s",
            },
        ],
        "pump_risk": {"level": "low", "signals": []},
        "data_gaps": [],
    }
    base.update(kw)
    return base


def test_schema_is_inline_without_numeric_limits() -> None:
    s = str(xai_schema())
    assert "$ref" not in s and "minimum" not in s and "maximum" not in s


def test_unverified_posts_removed() -> None:
    cleaned, dropped = clean_sentiment(SentimentReport.model_validate(report()), {REAL})
    assert [p.url for p in cleaned.notable_posts] == [REAL]
    assert cleaned.themes[0].post_urls == [REAL]
    assert dropped["unverified_posts"] == 1


def test_score_out_of_range_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SentimentReport.model_validate(report(score=7))


def test_prompt_mentions_company_window_and_pump_rule() -> None:
    p = build_prompt("Tata Steel Limited", "TATASTEEL", "Steel", TODAY, days=30)
    assert "Tata Steel" in p and "TATASTEEL" in p and "2026-10-27" in p
    assert "pump" in p.lower()


class FakeXai:
    def __init__(self, data, urls):
        self.data, self.urls, self.calls = data, urls, []

    def x_search_json(self, prompt, schema, from_date, to_date, system=None, note=""):
        self.calls.append((from_date, to_date, note))
        return XaiResult(self.data, frozenset(self.urls), 40, 2, 0.21)


def test_run_sentiment_records_meta_and_window() -> None:
    fake = FakeXai(report(), {REAL})
    run = run_sentiment(fake, "Tata Steel Limited", "TATASTEEL", "Steel", TODAY)
    assert run.meta["posts_fetched"] == 40 and run.meta["cost_usd"] == pytest.approx(0.21)
    assert fake.calls[0][0] == date(2026, 10, 27) and fake.calls[0][1] == date(2026, 11, 27)
    assert len(run.report.notable_posts) == 1


def test_invalid_grok_output_is_error() -> None:
    with pytest.raises(XaiError) as err:
        run_sentiment(FakeXai({"overall": "great"}, set()), "X", "X", None, TODAY)
    assert err.value.kind == "invalid_output"
