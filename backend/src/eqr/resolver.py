"""Turn a ticker, company name, ISIN or stock-site URL into an NSE security.

Never guesses: when the input is ambiguous the result carries ranked
candidates and no match, so the UI can ask the user to pick.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from rapidfuzz import fuzz

# Common short names that point at exactly one listed company. Keys are upper-case.
ALIASES: dict[str, str] = {
    "HUL": "HINDUNILVR",
    "RIL": "RELIANCE",
    "SBI": "SBIN",
    "L&T": "LT",
    "LARSEN": "LT",
    "AIRTEL": "BHARTIARTL",
    "KOTAK": "KOTAKBANK",
    "AXIS": "AXISBANK",
    # Former names after renames
    "ZOMATO": "ETERNAL",
}

# Group names shared by several listed companies: always ask, never pick.
# Symbols not in the current NSE list are dropped at lookup time.
GROUPS: dict[str, tuple[str, ...]] = {
    "HDFC": ("HDFCBANK", "HDFCLIFE", "HDFCAMC"),
    "ICICI": ("ICICIBANK", "ICICIGI", "ICICILIFE", "ICICIAMC"),
    "LIC": ("LICI", "LICHSGFIN"),
    "SBI CARD": ("SBICARD",),
}

MIN_PREFIX_CHARS = 6

CONFIDENT_SCORE = 88.0
CONFIDENT_GAP = 6.0
CANDIDATE_FLOOR = 60.0
MAX_CANDIDATES = 5

_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
_SUFFIX_RE = re.compile(r"\.(NS|BO|NSE|BSE)$")
_PREFIX_RE = re.compile(r"^(NSE|BSE)[:\s]+")
_LEGAL_WORDS = re.compile(r"\b(limited|ltd|pvt|private|the|co|corp|corporation)\b")


@dataclass(frozen=True)
class Security:
    symbol: str
    name: str
    series: str
    isin: str


@dataclass(frozen=True)
class Candidate:
    security: Security
    score: float


@dataclass(frozen=True)
class Resolution:
    query: str
    match: Security | None
    candidates: tuple[Candidate, ...]
    method: str  # symbol | alias | isin | prefix | name | none


@dataclass(frozen=True)
class _Hints:
    symbols: tuple[str, ...]
    names: tuple[str, ...]


def normalize_name(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = _LEGAL_WORDS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(text: str) -> str:
    return normalize_name(text).replace(" ", "")


def _clean_ticker(token: str) -> str:
    token = token.strip().upper().lstrip("$")
    token = _PREFIX_RE.sub("", token)
    return _SUFFIX_RE.sub("", token)


def _slug_to_name(slug: str) -> str:
    return unquote(slug).replace("-", " ").replace("_", " ")


def _segments(path: str) -> list[str]:
    return [unquote(s) for s in path.split("/") if s]


def _after(segments: list[str], marker: str, offset: int = 1) -> str | None:
    if marker in segments:
        idx = segments.index(marker) + offset
        if idx < len(segments):
            return segments[idx]
    return None


def url_hints(url: str) -> _Hints:
    """Extract ticker and name hints from known stock-site URL shapes."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    segs = _segments(parsed.path)
    query = parse_qs(parsed.query)
    symbols: list[str] = []
    names: list[str] = []

    for key in ("symbol", "sym", "ticker"):
        symbols.extend(query.get(key, []))

    if "screener.in" in host:
        if seg := _after(segs, "company"):
            symbols.append(seg)
    elif "tickertape.in" in host:
        if seg := _after(segs, "stocks"):
            symbols.append(seg.rsplit("-", 1)[-1])
            names.append(_slug_to_name(seg.rsplit("-", 1)[0]))
    elif "yahoo." in host:
        if seg := _after(segs, "quote"):
            symbols.append(seg)
    elif "bseindia.com" in host:
        if seg := _after(segs, "stock-share-price", 2):
            symbols.append(seg)
        if seg := _after(segs, "stock-share-price"):
            names.append(_slug_to_name(seg))
    elif "moneycontrol.com" in host:
        # /india/stockpricequote/<sector>/<compactname>/<mc-code>; mc-code is not a ticker
        if seg := _after(segs, "stockpricequote", 2):
            names.append(seg)
    elif "groww.in" in host:
        if seg := _after(segs, "stocks"):
            names.append(_slug_to_name(seg))
    elif "trendlyne.com" in host:
        if seg := _after(segs, "equity", 2):
            symbols.append(seg)
        if seg := _after(segs, "equity", 3):
            names.append(_slug_to_name(seg))
    else:
        # Unknown site: path words are often ordinary words that happen to be
        # tickers ("trade-idea" -> IDEA), so only query-string symbols count as
        # tickers; hyphenated slugs are tried as company names.
        names.extend(_slug_to_name(seg) for seg in segs if "-" in seg)

    return _Hints(symbols=tuple(symbols), names=tuple(names))


class Resolver:
    def __init__(self, securities: list[Security]) -> None:
        self._securities = tuple(securities)
        self._by_symbol = {s.symbol.upper(): s for s in securities}
        self._by_isin = {s.isin.upper(): s for s in securities}
        self._names = tuple(normalize_name(s.name) for s in securities)
        self._compact_names = tuple(n.replace(" ", "") for n in self._names)

    @classmethod
    def from_csv(cls, path: Path) -> Resolver:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header_row = next(reader, None)
            if not header_row:
                raise ValueError(f"Equity list {path} is empty")
            col = {h.strip().upper(): i for i, h in enumerate(header_row)}
            needed = ("SYMBOL", "NAME OF COMPANY", "SERIES", "ISIN NUMBER")
            if missing := [n for n in needed if n not in col]:
                raise ValueError(f"Equity list {path} is missing columns {missing}")
            width = max(col[n] for n in needed) + 1
            securities = [
                Security(
                    symbol=row[col["SYMBOL"]].strip(),
                    name=row[col["NAME OF COMPANY"]].strip(),
                    series=row[col["SERIES"]].strip(),
                    isin=row[col["ISIN NUMBER"]].strip(),
                )
                for row in reader
                if len(row) >= width
            ]
        if not securities:
            raise ValueError(f"Equity list {path} has no rows")
        return cls(securities)

    def __len__(self) -> int:
        return len(self._securities)

    def by_symbol(self, symbol: str) -> Security | None:
        return self._by_symbol.get(symbol.upper())

    def resolve(self, text: str) -> Resolution:
        query = text.strip()
        if not query:
            raise ValueError("Enter a ticker, company name or link")

        if re.match(r"^https?://", query, re.I) or "." in query.split("/")[0] and "/" in query:
            url = query if re.match(r"^https?://", query, re.I) else f"https://{query}"
            return self._resolve_url(query, url_hints(url))

        exact = self._exact(query)
        if exact:
            return exact
        return self._resolve_name(query, query)

    def _exact(self, query: str) -> Resolution | None:
        token = _clean_ticker(query)
        if _ISIN_RE.match(token) and token in self._by_isin:
            return Resolution(query, self._by_isin[token], (), "isin")
        if token in self._by_symbol:
            return Resolution(query, self._by_symbol[token], (), "symbol")
        if token in ALIASES and ALIASES[token] in self._by_symbol:
            return Resolution(query, self._by_symbol[ALIASES[token]], (), "alias")
        if token in GROUPS:
            group = tuple(
                Candidate(self._by_symbol[s], 100.0) for s in GROUPS[token] if s in self._by_symbol
            )
            if len(group) == 1:
                return Resolution(query, group[0].security, group, "alias")
            if group:
                return Resolution(query, None, group, "none")
        # "Sun Pharma" -> SUNPHARMA: the query with spaces removed is a symbol.
        squashed = re.sub(r"[^A-Z0-9&]", "", token)
        if squashed != token and squashed in self._by_symbol:
            return Resolution(query, self._by_symbol[squashed], (), "symbol")
        return None

    def _resolve_url(self, query: str, hints: _Hints) -> Resolution:
        for sym in hints.symbols:
            token = _clean_ticker(sym)
            if token in self._by_symbol:
                return Resolution(query, self._by_symbol[token], (), "symbol")
        best: Resolution | None = None
        for name in hints.names:
            res = self._resolve_name(query, name)
            if res.match:
                return res
            best = best or res
        return best or Resolution(query, None, (), "none")

    def _resolve_name(self, query: str, name: str) -> Resolution:
        target = normalize_name(name)
        if not target:
            return Resolution(query, None, (), "none")
        prefixed = self._prefix_matches(target)
        if len(prefixed) == 1:
            sec = self._securities[prefixed[0]]
            return Resolution(query, sec, (Candidate(sec, 100.0),), "prefix")
        compact = target.replace(" ", "")
        scores = [self._score(target, compact, i) for i in range(len(self._securities))]
        clean = {self._securities[i].symbol for i, (_, ok) in enumerate(scores) if ok}
        scored = sorted(
            (Candidate(sec, scores[i][0]) for i, sec in enumerate(self._securities)),
            key=lambda c: c.score,
            reverse=True,
        )
        if len(prefixed) > 1:
            # Several names start with the query ("Bajaj Fin"): list those first, never pick.
            first = {self._securities[i].symbol for i in prefixed}
            scored = [c for c in scored if c.security.symbol in first] + [
                c for c in scored if c.security.symbol not in first
            ]
            return Resolution(query, None, tuple(scored[:MAX_CANDIDATES]), "none")
        candidates = tuple(c for c in scored[:MAX_CANDIDATES] if c.score >= CANDIDATE_FLOOR)
        if not candidates:
            return Resolution(query, None, (), "none")
        top = candidates[0]
        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        confident = top.score >= CONFIDENT_SCORE and top.score - runner_up >= CONFIDENT_GAP
        # A query with words the name does not contain ("Reliance Industries Jio
        # Platforms") may mean a subsidiary or an old name: ask instead of picking.
        if confident and top.security.symbol in clean:
            return Resolution(query, top.security, candidates, "name")
        return Resolution(query, None, candidates, "none")

    def _prefix_matches(self, target: str) -> list[int]:
        """Indexes of names that start with the query (last word may be partial)."""
        if len(target) < MIN_PREFIX_CHARS:
            return []
        return [i for i, name in enumerate(self._names) if name.startswith(target)]

    def _score(self, target: str, compact: str, i: int) -> tuple[float, bool]:
        """(similarity 0-100, whether every query word appears in the name)."""
        name = self._names[i]
        if target == name or compact == self._compact_names[i]:
            return 100.0, True
        full = fuzz.ratio(target, name)
        if not set(target.split()) <= set(name.split()):
            return full, False
        # Query words are a subset of the name: credit that, scaled by how much
        # of the name the query covers so "bajaj" stays ambiguous.
        token = fuzz.token_set_ratio(target, name)
        coverage = min(len(target) / max(len(name), 1), 1.0)
        return max(full, token * (0.6 + 0.4 * coverage)), True
