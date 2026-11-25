# India Equity Research (personal use)

Paste a link, company name or ticker; get financials, valuation, news, sentiment and sector view for an NSE-listed company. Plan: [PLAN.md](PLAN.md).

## Status

Phases 0-3 and 5 done: data layer, valuation engine, Claude research agent, sector view. Grok sentiment (needs an xAI key), dashboard and backtest not built yet. Formulas: [docs/FORMULAS.md](docs/FORMULAS.md).

## Backend

```bash
cd backend
uv sync
uv run pytest -q                          # offline tests against saved NSE fixtures
uv run python scripts/coverage_spike.py   # live check: data coverage for 10 stocks (hits NSE, ~1 req/s)
uv run python scripts/value.py TCS "HDFC Bank"  # full valuation report; JSON in data/reports/
uv run python scripts/research.py TCS          # Claude research (uses your Claude Code login), cached 12h
uv run python scripts/sectors.py TATASTEEL     # sector strength, related sectors
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
| `fundamentals.py` | Fiscal-year rows, TTM, share count checks, bonus/split detection |
| `market.py` | Rates and risk premium from `config/market_inputs.toml` |
| `valuation/` | Investor formulas, quality scores, blend into fair value and signal |
| `llm/claude_cli.py` | Claude via the local Claude Code CLI, isolated, fail-closed, records tools and URLs seen |
| `research/` | Research prompt, typed report schema, sourcing rules |
| `sources/announcements.py`, `sources/documents.py` | NSE announcements and extracted text of key filings |
| `sources/indices.py`, `sectors/` | NSE daily index files, sector strength, related sectors |

Local data and cache live in `backend/data/` (git-ignored).
