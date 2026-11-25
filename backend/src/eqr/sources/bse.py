"""BSE: daily price file, list of listed companies, and results filings. Used for companies
listed only on BSE (NSE covers the rest). BSE's results XBRL uses the same SEBI taxonomies
as NSE's (in-bse-fin before 2025, in-capmkt integrated filings after), so the same parser
reads both."""

from __future__ import annotations

import csv
import io
import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

from eqr.cache import Cache
from eqr.nse_client import NseClient, NseNotFound
from eqr.sources.bhavcopy import DailyBar
from eqr.sources.filings import FilingRef, FilingsSource, merge_refs

log = logging.getLogger(__name__)

BSE_BASE = "https://www.bseindia.com"
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/"
BHAV_URL = BSE_BASE + "/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{day:%Y%m%d}_F_0000.CSV"
LIST_TTL = 7 * 24 * 3600  # no market-wide refresh signal wired for BSE yet: weekly
FIRST_PERIOD = date(2017, 4, 1)  # same history depth as NSE's XBRL
QUARTER_KINDS = {"MQ", "JQ", "SQ", "DQ"}  # quarters; DC/SN/JH are year-to-date figures
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}
_Q = re.compile(r"^(Standalone|Consolidated)-([A-Z][a-z]{2})-(\d{2});([A-Z]{2})", re.I)


def bse_client(cache: Cache | None = None) -> NseClient:
    return NseClient(cache=cache, base=BSE_BASE, api=BSE_API, cache_prefix="bse")


def parse_bse_quarter(text: str) -> tuple[date, bool] | None:
    """'Consolidated-Sep-26;SQ2026-2027;131.00;c' -> (2026-09-30, consolidated=True)."""
    m = _Q.match(text or "")
    if not m or m.group(4).upper() not in QUARTER_KINDS or m.group(2) not in _MONTHS:
        return None
    month, year = _MONTHS[m.group(2)], 2000 + int(m.group(3))
    first_next = date(year + month // 12, month % 12 + 1, 1)
    return first_next - timedelta(days=1), m.group(1).lower() == "consolidated"


def _filed(row: dict[str, Any]) -> str:
    raw = row.get("Revised_Date_Time") or row.get("Filing_Date_Time") or ""
    try:
        return datetime.fromisoformat(raw.split(".")[0]).strftime("%d-%b-%Y %H:%M:%S")
    except ValueError:
        return ""


def bse_refs(table: list[dict[str, Any]], code: str) -> list[FilingRef]:
    out = []
    for row in table:
        q = parse_bse_quarter(row.get("Quarter") or "")
        if q is None or q[0] < FIRST_PERIOD:
            continue
        end, consolidated = q
        link = row.get("conso_xbrl_link") if consolidated else row.get("stand_xbrl_link")
        if not link:
            continue
        url = link if link.startswith("http") else BSE_BASE + link
        out.append(FilingRef(code, end, consolidated, url, _filed(row), "bse"))
    return out


class BseFilingsSource(FilingsSource):
    """Same interface as the NSE source; symbols are BSE scrip codes."""

    @staticmethod
    def _archive(code: str) -> str:
        return f"Result_Arch_ng/w?scrip_cd={code}"

    def invalidate(self, symbol: str) -> None:
        self._client.forget_json(self._archive(symbol))

    def list_raw(self, symbol: str) -> list[FilingRef]:
        payload = self._client.get_json(self._archive(symbol), ttl=LIST_TTL)
        table = payload.get("Table") if isinstance(payload, dict) else None
        if not isinstance(table, list):
            raise ValueError(f"Unexpected BSE results payload for {symbol}")
        return bse_refs(table, symbol)

    def list(self, symbol: str) -> list[FilingRef]:
        latest: dict[tuple[date, bool], FilingRef] = {}
        for r in sorted(
            self.list_raw(symbol),
            key=lambda r: r.filed_at and datetime.strptime(r.filed_at, "%d-%b-%Y %H:%M:%S"),
        ):
            latest[(r.period_end, r.consolidated)] = r  # a later filing (revision) replaces
        return merge_refs([], latest.values())


def parse_bse_bhavcopy(text: str) -> dict[str, DailyBar]:
    """BSE's UDiFF file, keyed by scrip code. SctySrs holds BSE's trading group (A, B, X...)."""
    bars: dict[str, DailyBar] = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("FinInstrmTp") != "STK":
            continue
        try:
            bars[row["FinInstrmId"].strip()] = DailyBar(
                symbol=row["FinInstrmId"].strip(),
                isin=row["ISIN"].strip(),
                series=row["SctySrs"].strip(),
                trade_date=date.fromisoformat(row["TradDt"]),
                open=float(row["OpnPric"]),
                high=float(row["HghPric"]),
                low=float(row["LwPric"]),
                close=float(row["ClsPric"]),
                prev_close=float(row["PrvsClsgPric"] or 0),
                volume=int(float(row["TtlTradgVol"] or 0)),
                turnover=float(row["TtlTrfVal"] or 0),
            )
        except (KeyError, ValueError) as exc:
            log.warning("Skipping bad BSE bhavcopy row %s: %s", row.get("FinInstrmId"), exc)
    return bars


def parse_scrips(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Active equity scrips: code -> {ticker, name, isin, url}."""
    out = {}
    for r in rows:
        if (r.get("Segment") or "").strip() != "Equity" or (
            r.get("Status") or ""
        ).strip() != "Active":
            continue
        code = str(r.get("SCRIP_CD") or "").strip()
        if code:
            out[code] = {
                "ticker": (r.get("scrip_id") or code).strip(),
                "name": (r.get("Scrip_Name") or r.get("Issuer_Name") or code).strip(),
                "isin": (r.get("ISIN_NUMBER") or "").strip(),
                "url": (r.get("NSURL") or "").strip(),
            }
    return out


class BseSource:
    def __init__(self, client: NseClient, cache: Cache) -> None:
        self._client, self._cache = client, cache

    def scrips(self) -> dict[str, dict[str, str]]:
        rows = self._client.get_json(
            "ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active",
            ttl=24 * 3600,
        )
        return parse_scrips(rows if isinstance(rows, list) else [])

    def bars(self, day: date) -> dict[str, DailyBar] | None:
        key = f"bsebhav:{day.isoformat()}"
        text = self._cache.get(key)
        if text is None:
            text = None
            for attempt in range(2):  # BSE sometimes answers 404 for a file that exists
                try:
                    text = self._client.get_bytes(BHAV_URL.format(day=day)).decode("utf-8-sig")
                    break
                except NseNotFound:
                    if attempt == 0:
                        time.sleep(2)
            if text is None:
                return None
            if not text.startswith("TradDt"):
                return None
            self._cache.set(key, text, ttl=None)
        return parse_bse_bhavcopy(text)
