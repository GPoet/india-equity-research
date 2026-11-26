"""NSE's lists of listed companies (main board and SME) and the Nifty 50."""

from __future__ import annotations

import csv
import io
import logging

from eqr.nse_client import NseClient, NseError

log = logging.getLogger(__name__)

NIFTY50 = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
ALL_LISTS = (
    ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", "SYMBOL", "NAME OF COMPANY"),
    (
        "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
        "SYMBOL",
        "NAME_OF_COMPANY",
    ),
)


def all_names(client: NseClient) -> tuple[dict[str, str], set[str]]:
    """(symbol -> company name, ISINs) for every NSE-listed company. The ISINs tell which BSE
    companies are also on NSE."""
    out: dict[str, str] = {}
    isins: set[str] = set()
    for url, sym_col, name_col in ALL_LISTS:
        try:
            text = client.get_bytes(url).decode("utf-8-sig")
        except NseError as exc:
            log.warning("Equity list %s unavailable: %s", url, exc)
            continue
        for r in csv.DictReader(io.StringIO(text)):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if r.get(sym_col):
                out[r[sym_col]] = r.get(name_col) or r[sym_col]
            isin = r.get("ISIN NUMBER") or r.get("ISIN_NUMBER")
            if isin:
                isins.add(isin)
    return out, isins


def nifty50_symbols(client: NseClient) -> set[str]:
    text = client.get_bytes(NIFTY50).decode("utf-8-sig")
    return {r["Symbol"].strip() for r in csv.DictReader(io.StringIO(text)) if r.get("Symbol")}
