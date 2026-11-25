from datetime import date

from eqr.research.schema import ResearchReport, clean_report, cli_schema


def item(**kw):
    base = {
        "title": "Order win",
        "detail": "Won a large deal",
        "kind": "company",
        "direction": "tailwind",
        "materiality": 3,
        "horizon": "near",
        "date": "2026-11-01",
        "source_url": "https://www.nseindia.com/x",
        "source_name": "NSE",
    }
    base.update(kw)
    return base


def report(**kw):
    base = {
        "summary": "s",
        "business": "b",
        "latest_results": "r",
        "catalysts": [item()],
        "regulation": [],
        "risks": [],
        "events": [],
        "sector_view": {
            "sector": "IT",
            "stance": "neutral",
            "reasoning": "x",
            "source_urls": ["https://example.com/a"],
        },
        "bull_case": "up",
        "bear_case": "down",
        "what_would_change_view": ["x"],
        "data_gaps": [],
    }
    base.update(kw)
    return base


def test_schema_has_no_refs_for_cli() -> None:
    assert "$ref" not in str(cli_schema())
    assert cli_schema()["type"] == "object"


def test_valid_report_parses() -> None:
    r = ResearchReport.model_validate(report())
    assert r.catalysts[0].direction == "tailwind"


def test_unsourced_items_dropped_and_counted() -> None:
    raw = report(
        catalysts=[
            item(),
            item(source_url=""),
            item(source_url="not a url"),
            item(source_url="ftp://x"),
        ]
    )
    cleaned, dropped = clean_report(ResearchReport.model_validate(raw), today=date(2026, 11, 25))
    assert len(cleaned.catalysts) == 1
    assert dropped["unsourced"] == 3


def test_future_dated_news_dropped() -> None:
    raw = report(catalysts=[item(date="2027-03-01")])
    cleaned, dropped = clean_report(ResearchReport.model_validate(raw), today=date(2026, 11, 25))
    assert cleaned.catalysts == []
    assert dropped["future_dated"] == 1


def test_duplicates_dropped() -> None:
    raw = report(catalysts=[item(), item()])
    cleaned, dropped = clean_report(ResearchReport.model_validate(raw), today=date(2026, 11, 25))
    assert len(cleaned.catalysts) == 1
    assert dropped["duplicate"] == 1


def test_regulation_may_have_future_effective_date() -> None:
    reg = {
        "title": "New rule",
        "regulator": "SEBI",
        "status": "notified",
        "effective_date": "2027-04-01",
        "announced_date": "2026-11-10",
        "direction": "headwind",
        "scope": "sector",
        "detail": "d",
        "source_url": "https://www.sebi.gov.in/x",
        "source_name": "SEBI",
    }
    cleaned, _ = clean_report(
        ResearchReport.model_validate(report(regulation=[reg])), today=date(2026, 11, 25)
    )
    assert len(cleaned.regulation) == 1


def test_bad_materiality_rejected() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResearchReport.model_validate(report(catalysts=[item(materiality=9)]))
