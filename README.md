# India Equity Research (personal use)

Paste a link, company name or ticker; get financials, valuation, news, sentiment and sector view for an NSE-listed company. Plan: [PLAN.md](PLAN.md).

## Status

Phase 0-1 (data layer) in progress. Dashboard, valuation engine and research agent not built yet.

## Backend

```bash
cd backend
uv sync
uv run pytest -q                          # offline tests against saved NSE fixtures
uv run python scripts/coverage_spike.py   # live check: data coverage for 10 stocks (hits NSE, ~1 req/s)
```

Modules (`backend/src/eqr/`):

| Module | Does |
|---|---|
| `resolver.py` | Link / name / ticker / ISIN to NSE symbol; returns a pick-list instead of guessing |
| `xbrl.py` | Parses NSE results XBRL (Ind-AS and banking taxonomies) into quarter, year-to-date and balance-sheet metrics |
| `nse_client.py` | Throttled NSE session with browser impersonation and caching |
| `cache.py` | SQLite cache with per-entry TTL |
| `sources/filings.py` | Lists and fetches quarterly results (legacy feed to 2024, integrated filing from 2025) |
| `sources/bhavcopy.py` | Official end-of-day prices |
| `sources/prices.py` | Delayed intraday quote and adjusted history via yfinance |
| `sources/universe.py` | Daily refresh of the NSE equity list |

Local data and cache live in `backend/data/` (git-ignored).
