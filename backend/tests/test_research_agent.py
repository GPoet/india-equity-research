from datetime import date, datetime

import pytest

from eqr.llm.claude_cli import LlmError, LlmResult
from eqr.research.agent import CompanyBrief, build_prompt, run_research
from eqr.sources.announcements import Announcement

TODAY = date(2026, 11, 25)
BRIEF = CompanyBrief(
    symbol="TCS",
    name="Tata Consultancy Services Limited",
    industry="Computers - Software",
    facts={
        "Latest quarter (Jul-Sep 2026)": "Revenue 73,188 cr (+11% YoY)",
        "Valuation": "Fairly valued",
    },
)
ANNS = [
    Announcement(
        "TCS",
        datetime(2026, 11, 19, 17, 41),
        "Acquisition",
        "TCS acquires X for $100m",
        "https://nsearchives.nseindia.in/a.pdf",
        "Computers - Software",
    ),
    Announcement(
        "TCS",
        datetime(2026, 10, 9, 18, 0),
        "Outcome of Board Meeting",
        "Q2 results approved",
        None,
        "Computers - Software",
    ),
]


def good_data() -> dict:
    return {
        "summary": "s",
        "business": "b",
        "latest_results": "r",
        "catalysts": [
            {
                "title": "Acquisition of X",
                "detail": "d",
                "kind": "company",
                "direction": "tailwind",
                "materiality": 3,
                "horizon": "medium",
                "date": "2026-11-19",
                "source_url": "https://nsearchives.nseindia.in/a.pdf",
                "source_name": "NSE",
            },
            {
                "title": "Rumour",
                "detail": "d",
                "kind": "company",
                "direction": "headwind",
                "materiality": 2,
                "horizon": "near",
                "date": "2026-11-01",
                "source_url": "",
                "source_name": "?",
            },
        ],
        "regulation": [],
        "risks": [],
        "events": [],
        "sector_view": {
            "sector": "IT services",
            "stance": "neutral",
            "reasoning": "r",
            "source_urls": [],
        },
        "bull_case": "b",
        "bear_case": "b",
        "what_would_change_view": [],
        "data_gaps": [],
    }


class FakeProvider:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.calls: list[dict] = []

    def run(self, prompt, schema, **kw):
        self.calls.append({"prompt": prompt, "schema": schema, **kw})
        return LlmResult(self.data, 0.5, 90_000, 12, 9, 4)


def test_prompt_contains_facts_announcements_and_date() -> None:
    p = build_prompt(BRIEF, ANNS, TODAY)
    assert "TCS" in p and "Tata Consultancy" in p
    assert "2026-11-25" in p
    assert "TCS acquires X for $100m" in p
    assert "https://nsearchives.nseindia.in/a.pdf" in p
    assert "Revenue 73,188 cr" in p


def test_prompt_caps_announcements() -> None:
    many = [ANNS[0]] * 200
    p = build_prompt(BRIEF, many, TODAY)
    assert p.count("TCS acquires X") <= 40


def test_run_research_cleans_and_records_meta() -> None:
    fake = FakeProvider(good_data())
    run = run_research(fake, BRIEF, ANNS, TODAY, model="sonnet")
    assert len(run.report.catalysts) == 1  # the unsourced rumour is dropped
    assert run.dropped["unsourced"] == 1
    assert run.meta["num_turns"] == 12
    assert run.meta["model"] == "sonnet"
    assert set(fake.calls[0]["tools"]) == {"WebSearch", "WebFetch"}


def test_schema_violation_is_invalid_output() -> None:
    bad = good_data()
    bad["catalysts"][0]["materiality"] = 42
    with pytest.raises(LlmError) as err:
        run_research(FakeProvider(bad), BRIEF, ANNS, TODAY)
    assert err.value.kind == "invalid_output"


def test_prompt_includes_document_text() -> None:
    from eqr.sources.documents import DocExcerpt

    doc = DocExcerpt(
        "https://nsearchives.nseindia.com/r.pdf",
        "Outcome of Board Meeting",
        datetime(2026, 10, 8),
        "Consolidated revenue Rs 73,188 crore",
        22,
    )
    p = build_prompt(BRIEF, ANNS, TODAY, [doc])
    assert "Consolidated revenue Rs 73,188 crore" in p
    assert 'url="https://nsearchives.nseindia.com/r.pdf"' in p
