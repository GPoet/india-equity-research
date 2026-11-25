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


def test_urls_not_seen_by_tools_are_dropped() -> None:
    raw = report(
        catalysts=[item(), item(title="Made up", source_url="https://economictimes.com/fake-story")]
    )
    allowed = {"https://www.nseindia.com/x"}
    cleaned, dropped = clean_report(
        ResearchReport.model_validate(raw), today=date(2026, 11, 25), allowed_urls=allowed
    )
    assert [c.title for c in cleaned.catalysts] == ["Order win"]
    assert dropped["unverified_url"] == 1


def test_url_match_tolerates_www_slash_and_query() -> None:
    raw = report(catalysts=[item(source_url="https://nseindia.com/x/?utm=1")])
    cleaned, _ = clean_report(
        ResearchReport.model_validate(raw),
        today=date(2026, 11, 25),
        allowed_urls={"https://www.nseindia.com/x"},
    )
    assert len(cleaned.catalysts) == 1


def test_past_and_invalid_events_dropped() -> None:
    events = [
        {"date": "2026-10-01", "event": "old", "source_url": None},
        {"date": "2026-13-45", "event": "bad", "source_url": None},
        {"date": "2026-12-05", "event": "RBI policy", "source_url": None},
        {"date": None, "event": "Q3 results, date not announced", "source_url": None},
    ]
    cleaned, dropped = clean_report(
        ResearchReport.model_validate(report(events=events)), today=date(2026, 11, 25)
    )
    assert [e.event for e in cleaned.events] == ["RBI policy", "Q3 results, date not announced"]
    assert dropped["stale_event"] == 2


def test_sector_view_without_verified_source_is_flagged() -> None:
    cleaned, _ = clean_report(
        ResearchReport.model_validate(report()),
        today=date(2026, 11, 25),
        allowed_urls={"https://www.nseindia.com/x"},
    )
    assert cleaned.sector_view.source_urls == []
    assert any("Sector view" in g for g in cleaned.data_gaps)
