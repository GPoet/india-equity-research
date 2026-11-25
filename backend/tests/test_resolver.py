from pathlib import Path

import pytest

from eqr.resolver import Resolver, Security

FIXTURE = Path(__file__).parent / "fixtures" / "equity_sample.csv"


@pytest.fixture(scope="module")
def resolver() -> Resolver:
    return Resolver.from_csv(FIXTURE)


def resolved_symbol(resolver: Resolver, text: str) -> str | None:
    result = resolver.resolve(text)
    return result.match.symbol if result.match else None


def test_loads_securities(resolver: Resolver) -> None:
    tcs = resolver.by_symbol("TCS")
    assert tcs == Security(
        symbol="TCS",
        name="Tata Consultancy Services Limited",
        series="EQ",
        isin="INE467B01029",
    )


@pytest.mark.parametrize("text", ["TCS", "tcs", " TCS ", "TCS.NS", "NSE:TCS", "$TCS"])
def test_exact_ticker(resolver: Resolver, text: str) -> None:
    assert resolved_symbol(resolver, text) == "TCS"


def test_ticker_with_ampersand(resolver: Resolver) -> None:
    assert resolved_symbol(resolver, "M&M") == "M&M"


def test_isin(resolver: Resolver) -> None:
    assert resolved_symbol(resolver, "INE002A01018") == "RELIANCE"


@pytest.mark.parametrize(
    ("text", "symbol"),
    [
        ("Tata Consultancy Services", "TCS"),
        ("reliance industries", "RELIANCE"),
        ("Hindustan Unilever Ltd", "HINDUNILVR"),
        ("State Bank of India", "SBIN"),
        ("mahindra and mahindra", "M&M"),
        ("Infosys", "INFY"),
    ],
)
def test_company_name(resolver: Resolver, text: str, symbol: str) -> None:
    assert resolved_symbol(resolver, text) == symbol


@pytest.mark.parametrize(
    ("text", "symbol"),
    [
        ("HUL", "HINDUNILVR"),
        ("RIL", "RELIANCE"),
        ("SBI", "SBIN"),
        ("Zomato", "ETERNAL"),
        ("Sun Pharma", "SUNPHARMA"),
    ],
)
def test_common_aliases(resolver: Resolver, text: str, symbol: str) -> None:
    assert resolved_symbol(resolver, text) == symbol


@pytest.mark.parametrize(
    ("url", "symbol"),
    [
        ("https://www.screener.in/company/TCS/consolidated/", "TCS"),
        ("https://www.nseindia.com/get-quotes/equity?symbol=RELIANCE", "RELIANCE"),
        ("https://www.nseindia.com/get-quotes/equity?symbol=M%26M", "M&M"),
        ("https://www.tickertape.in/stocks/tata-consultancy-services-TCS", "TCS"),
        ("https://finance.yahoo.com/quote/INFY.NS/", "INFY"),
        (
            "https://www.bseindia.com/stock-share-price/tata-consultancy-services-ltd/tcs/532540/",
            "TCS",
        ),
        (
            "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI",
            "RELIANCE",
        ),
        ("https://groww.in/stocks/hindustan-unilever-ltd", "HINDUNILVR"),
        ("https://trendlyne.com/equity/1372/TCS/tata-consultancy-services-ltd/", "TCS"),
    ],
)
def test_urls(resolver: Resolver, url: str, symbol: str) -> None:
    assert resolved_symbol(resolver, url) == symbol


def test_ambiguous_returns_candidates_not_guess(resolver: Resolver) -> None:
    result = resolver.resolve("Bajaj")
    assert result.match is None
    symbols = {c.security.symbol for c in result.candidates}
    assert {"BAJFINANCE", "BAJAJFINSV"} <= symbols


def test_ambiguous_tata(resolver: Resolver) -> None:
    result = resolver.resolve("Tata")
    assert result.match is None
    assert len(result.candidates) >= 2


def test_nonsense_returns_nothing_confident(resolver: Resolver) -> None:
    result = resolver.resolve("qwertyuiop zzz")
    assert result.match is None


def test_empty_input_raises(resolver: Resolver) -> None:
    with pytest.raises(ValueError):
        resolver.resolve("   ")


@pytest.mark.parametrize(
    ("text", "symbol"),
    [
        ("Tata Consultancy", "TCS"),
        ("Sun Pharmaceutical", "SUNPHARMA"),
        ("state bank", "SBIN"),
        ("Hindustan Uni", "HINDUNILVR"),
    ],
)
def test_unique_name_prefix_matches(resolver: Resolver, text: str, symbol: str) -> None:
    assert resolved_symbol(resolver, text) == symbol


def test_shared_name_prefix_stays_ambiguous(resolver: Resolver) -> None:
    result = resolver.resolve("Bajaj Fin")
    assert result.match is None
    assert {c.security.symbol for c in result.candidates[:2]} == {
        "BAJFINANCE",
        "BAJAJFINSV",
    }


@pytest.mark.parametrize(
    "text",
    [
        "Hindustan Unilever Foods",
        "Reliance Industries Jio Platforms",
        "State Bank of India Mutual Fund",
        "Tata Consultancy Services Infotech",
    ],
)
def test_extra_words_do_not_match_parent(resolver: Resolver, text: str) -> None:
    assert resolver.resolve(text).match is None


def test_unknown_site_path_words_are_not_tickers(resolver: Resolver) -> None:
    assert resolver.resolve("https://economictimes.com/markets/stocks/trade-idea").match is None


def test_unknown_site_query_symbol_still_works(resolver: Resolver) -> None:
    assert resolved_symbol(resolver, "https://example.com/quote?symbol=TCS") == "TCS"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HDFC", {"HDFCBANK", "HDFCLIFE", "HDFCAMC"}),
        ("LIC", {"LICI", "LICHSGFIN"}),
        ("ICICI", {"ICICIBANK", "ICICIGI"}),
    ],
)
def test_group_names_are_ambiguous(resolver: Resolver, text: str, expected: set[str]) -> None:
    result = resolver.resolve(text)
    assert result.match is None
    assert expected <= {c.security.symbol for c in result.candidates}


def test_short_prefix_does_not_match(resolver: Resolver) -> None:
    assert resolver.resolve("Infos").match is None


def test_empty_csv_raises_value_error(tmp_path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(ValueError):
        Resolver.from_csv(empty)
