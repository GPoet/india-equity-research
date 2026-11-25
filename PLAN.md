# India Equity Research Dashboard: Development Plan

Status: plan only, no code yet. Date: 25 Nov 2026. Scope: personal use, NSE/BSE listed companies only.

## 1. What it does

Input: a link (Screener, Moneycontrol, NSE, BSE, Tickertape URL), a company name, or a ticker.
Output: one structured page with financials, valuation, fair value range, an under/overvalued signal with a confidence level, news and regulatory tailwinds/headwinds, social and news sentiment, sector outlook, correlated sectors, and 12-month bear/base/bull scenarios. Every number carries a source and an "as of" timestamp.

## 2. Research findings that shape the design

| Topic | Finding | Effect on plan |
|---|---|---|
| Claude via subscription OAuth | Anthropic's terms (Feb 2026) say consumer plan OAuth tokens are for Claude Code and Anthropic's own apps, and third parties may not offer Claude.ai login in their apps. Anthropic staff later said personal Agent SDK use was not changing but recommended API keys for building. Since May 2026, Agent SDK and headless `claude -p` usage draws from a separate credit pool on the subscription. | For personal use, drive research through Claude Code headless (`claude -p`) or the Agent SDK on your own machine, logged in with your own plan. Do not embed the OAuth token in a web app. Keep an `LLMProvider` interface so switching to an API key is one config change. |
| Claude API cost (if you switch) | Sonnet 5.5 is $2 / $10 per M tokens, Opus 5.5 is $4 / $20. A report of roughly 150k input + 10k output tokens + 10 web searches comes to about $0.50 on Sonnet 5.5 and about $0.90 on Opus 5.5 (web search at $10 per 1k, verify). | Default Sonnet 5.5 for extraction and news triage, Opus 5.5 for the final synthesis. |
| Grok / X sentiment | xAI API has server-side `x_search` and `web_search` tools, billed on top of tokens. Listed at $5 per 1k calls; RuntimeWire reports a move to per-item billing ($5 per 1k posts, $10 per 1k profiles) from Sept 2026, unconfirmed. | Use Grok only for X sentiment. Cap posts per query. Check docs.x.ai/developers/pricing before building. |
| Market data | Zerodha Kite Connect: free Personal tier has no market data; paid Connect is Rs 500/month per key and includes live and historical data. Upstox and Dhan have data APIs too (pricing from one aggregator, unverified). yfinance `.NS` is free but delayed and patchy on Indian fundamentals. | Kite Connect for prices (you are a Zerodha user if this fits), yfinance as free fallback. |
| Fundamentals | No clean official free API. Options: NSE/BSE corporate filings (XBRL results, shareholding), Screener.in export (logged-in, personal), open-source scrapers like `dalal`, paid APIs (Tapetide, EODHD). | Primary: NSE/BSE XBRL filings (authoritative, point-in-time). Secondary: Screener export for 10-year history. All scrapers behind an adapter so one breaking does not break the app. |
| SEBI rules | Specific buy/sell calls to others without SEBI RA/IA registration are being enforced against actively (Telegram/WhatsApp tip orders in 2026). RA rules also require disclosure of AI tool use. | Personal use is fine. If it is ever shared, paid, or published, it needs an RA tie-up or registration first. Keep the app login-gated and single user. |
| NSE data licensing | Redistributing or displaying exchange data on a website needs an NSE Data & Analytics licence; Zerodha forbids showing Kite API data on external platforms. | Fine for local, personal use. Do not host it publicly. |

## 3. Architecture

```
Next.js dashboard (localhost)
        |
FastAPI service (Python: finance libs live here)
  |-- resolver        link / name / ticker -> NSE symbol + BSE code + ISIN
  |-- data adapters   kite | yfinance | nse_filings | bse | screener | macro
  |-- cache           SQLite (DuckDB for backtests), TTL per data type
  |-- valuation       deterministic Python, no LLM
  |-- sector engine   index returns, rotation, correlation matrix
  |-- research agent  Claude (news, regulation, filings, synthesis)
  |-- sentiment       Grok x_search + news-tone scoring
  |-- report builder  merges into one typed JSON report
  |-- journal         every report saved with timestamp for forward testing
```

Rule: the LLM never computes a number that appears in the valuation. Python computes; Claude explains, finds catalysts, and flags risks. This keeps outputs reproducible and backtestable.

### Input resolution
- Load NSE `EQUITY_L.csv` and BSE scrip master daily; fuzzy match names (rapidfuzz), alias table for common names ("HUL", "RIL", "SBI").
- URL parsers per site extract the symbol.
- Ambiguous match: show top 3 to pick from, never guess.

### Data adapters and refresh
| Data | Source | Refresh |
|---|---|---|
| Price, volume, history | Kite Connect, fallback yfinance | live / daily |
| Quarterly and annual results | NSE/BSE XBRL filings, Screener export | on new filing |
| Shareholding, promoter pledge | NSE shareholding pattern | quarterly |
| Announcements, bulk/block deals, auditor changes | NSE/BSE corporate announcements | hourly |
| Surveillance (ASM/GSM), F&O ban list | NSE | daily |
| Macro | RBI (repo, 10Y G-Sec yield), MOSPI (CPI, IIP), INR, crude | daily / monthly |
| FPI flows by sector | NSDL fortnightly sector data | fortnightly |
| News | Google News RSS, ET / Business Standard / Moneycontrol RSS, Claude web search | per request + hourly |
| Regulation | SEBI circulars, RBI notifications, PIB, e-Gazette, DGFT, ministry PLI pages | daily |
| Social | Grok `x_search`; optional ValuePickr forum, Reddit r/IndianStreetBets | per request |

India-specific handling: consolidated vs standalone statements (default consolidated, show both), April-March fiscal year, bonus/split adjustment, SME board flag, PSU dividend policy.

## 4. Valuation engine

Model chosen by sector, then blended into a range:

| Company type | Primary model | Cross-check |
|---|---|---|
| General (FMCG, IT, pharma, auto, industrials) | FCFF DCF, 3-stage | EV/EBITDA and P/E vs own 10-year band and peers |
| Banks, NBFCs | Justified P/B from ROE, cost of equity, growth; residual income | P/B and P/ABV vs peers, asset-quality adjustment (GNPA/NNPA) |
| Insurers | P/EV | VNB margin trend |
| Cyclicals (metals, cement, oil) | Normalised mid-cycle earnings x multiple | EV/tonne or EV/capacity |
| Holding companies, conglomerates | Sum of the parts with holdco discount | listed subsidiary market values |
| Loss-making growth | EV/Sales with path-to-profit | reverse DCF only |

Inputs: risk-free rate = live 10Y G-Sec yield (fetched, never hardcoded), equity risk premium from Damodaran's India country data (refreshed yearly), beta vs Nifty 50 (2y weekly, Blume-adjusted), tax at effective rate.

Always run a reverse DCF: "the current price implies X% growth for 10 years". This is often the most useful line on the page.

Outputs:
- Fair value range (low / mid / high) with each method's weight shown.
- Signal: Undervalued if price < low end minus margin of safety (default 15%), Overvalued if price > high end, else Fairly valued.
- Confidence (high/medium/low) from model agreement, data completeness, and earnings stability.
- Football-field chart of all methods.

Quality and red-flag overlay (shown next to valuation, can downgrade confidence): promoter pledge %, related-party transactions, auditor resignation, contingent liabilities, cash conversion (CFO/EBITDA), receivable days trend, equity dilution, ASM/GSM listing, Piotroski F-score, Beneish M-score.

## 5. Research agent (Claude)

Runs after the data layer, given the computed metrics as context. Tasks:
1. Summarise last 4 quarters' results and management commentary (earnings call transcripts / investor presentations from filings).
2. News scan (last 90 days): classify each item as tailwind / headwind / neutral with materiality 1-5, dated and linked.
3. Regulatory scan: upcoming or recent policy changes for the company and its sector (SEBI, RBI, GST council, PLI, tariffs, import duties, ministry drafts, Budget announcements), each with effective date and expected direction.
4. Event calendar: results date, RBI MPC, Budget (1 Feb), index rebalances, lock-in expiries.
5. Final synthesis: thesis, key risks, what would change the view.

Uses structured outputs (fixed JSON schema) so the page renders reliably. Every claim needs a source URL; unsourced claims are dropped.

## 6. Sentiment

- X (Grok): query by cashtag, company name, and key people. Score bullish / bearish / neutral, volume vs 30-day baseline, top posts with links. Weight by account quality.
- Pump detection: sudden volume spikes from low-follower or new accounts on small caps get flagged as a risk, not counted as bullish. (SEBI flagged lakhs of misleading posts in 2026.)
- News tone: scored separately from X so you can see when they diverge.
- Sentiment is shown as context only. It does not change fair value.

## 7. Sector view and correlated sectors

- Track all NSE sectoral and thematic indices (Bank, IT, Pharma, Auto, FMCG, Metal, Realty, Energy, PSU Bank, Capital Goods, Defence, etc.).
- Bullish score per sector: relative strength vs Nifty (3 and 6 month), earnings revision breadth, FPI/DII flow trend, regulatory tailwind count from the agent.
- Correlated sectors, two layers:
  1. Statistical: rolling 1-year correlation of weekly returns, plus lead-lag (does sector A move before B).
  2. Economic linkage map: supply chain and macro links (power capex -> cables, transformers, capital goods; housing -> cement, paints, building materials; crude down -> paints, OMCs, aviation; rate cuts -> banks, NBFCs, realty, autos; EV -> copper, batteries). Claude proposes links, the statistics confirm or reject them.
- Output: the company's sector rating plus 3-5 related sectors that are bullish, each with the reason and the correlation number.

## 8. Expected future value

- 12-month bear / base / bull values from the valuation engine with different growth, margin, and multiple assumptions, each with a stated probability.
- Shown as a range with assumptions, never one target price.
- Logged to the journal so accuracy can be measured.

## 9. Backtesting (the hard part)

Two different problems:

1. Deterministic engine (valuation, quality, sector scores): backtest historically.
   - Needs point-in-time data: financials as filed on that date, not restated later. Store filing dates.
   - Include delisted companies to avoid survivorship bias.
   - Test: buy "Undervalued + high confidence" names, compare 6/12-month returns vs Nifty 500, hit rate, drawdown, by sector and market-cap bucket.

2. LLM layers (news, regulation, sentiment synthesis): cannot be honestly backtested on past dates. The model already knows what happened up to its training cutoff, so a 2024 "prediction" is contaminated. Only valid test is forward: every report goes into the journal now, and a scheduled job scores it at 1, 3, 6, and 12 months.

The journal (report JSON + price at time + model version) starts on day one, so forward data builds up while you use it.

## 10. Dashboard layout

1. Header: name, price, market cap, signal badge, confidence, data timestamp.
2. Snapshot: P/E, P/B, EV/EBITDA, ROE, ROCE, debt/equity, dividend yield, promoter holding and pledge, each vs sector median.
3. Financials: 10-year annual and 8-quarter tables, revenue / EBITDA / PAT / margin charts.
4. Valuation: fair value range, football field, reverse DCF line, editable assumptions (change growth or WACC, see value update).
5. Catalysts: news and regulatory tailwinds/headwinds, dated, linked.
6. Sentiment: X, news tone, divergence.
7. Sector: sector rating, related bullish sectors, correlation heatmap.
8. Scenarios: bear / base / bull 12-month.
9. Red flags.
10. Sources.

Plus a watchlist page and a journal page (past reports and how they scored).

## 11. Phases

| Phase | Work | Estimate |
|---|---|---|
| 0. Spike | Resolver; check data coverage for 10 test stocks (a private bank, NBFC, IT, FMCG, PSU, metal, pharma, holdco, small cap, recent IPO). Decide sources. | 3-4 days |
| 1. Data layer | Adapters, cache, point-in-time storage, tests | 1.5 weeks |
| 2. Valuation engine | Models per sector type, reverse DCF, red flags, tests against hand-checked cases | 1.5 weeks |
| 3. Research agent | Claude integration, schema, sourcing rules | 1 week |
| 4. Sentiment | Grok integration, pump detection | 3-4 days |
| 5. Sector module | Index data, scores, correlation, linkage map | 1 week |
| 6. Dashboard | Next.js report page, watchlist, journal | 1.5 weeks |
| 7. Backtest + journal scoring | Historical engine backtest, scheduled forward scoring | 1 week |

Roughly 8-9 weeks for one developer. Phases 4 and 5 can run alongside 3.

## 12. Risks

- Scrapers break when NSE / Screener change pages. Mitigation: adapters, fallbacks, health checks.
- Fundamentals data gaps for small caps and SME stocks. Mitigation: confidence drops, page says what is missing (missing is not zero).
- LLM invents a regulation or misdates it. Mitigation: source URL required, date shown, unsourced dropped.
- Subscription usage limits on the Claude path. Mitigation: provider interface, cache research per company for a few hours.
- Overconfidence in the signal. Mitigation: ranges, confidence level, journal scoring before trusting it with money.

## 12a. Phase 0 results (25 Nov 2026, measured)

| Source | Status | Notes |
|---|---|---|
| NSE `EQUITY_L.csv` | Works | 2,632 listed equities; resolver refreshes daily |
| NSE bhavcopy (UDiFF zip) | Works | Official EOD OHLCV; no file on holidays (24 Nov was one) |
| NSE `integrated-filing-results` (Financials) | Works | Results 2025 onward, XBRL per quarter, consolidated and standalone |
| NSE `corporates-financial-results` | Works | Legacy results, quarterly XBRL from 2018 to Dec 2024 |
| NSE `results-comparision` | Stale | Stops at Dec 2024; not used |
| NSE `corporate-share-holdings-master` | Works | Promoter / public %; pledge needs a separate call (todo) |
| NSE `corporate-announcements` | Works | For news/catalyst layer |
| NSE `quote-equity` (live) | Blocked | 403 even with browser impersonation; use yfinance |
| yfinance `.NS` | Works | Delayed intraday + adjusted history |

Coverage on 10 test stocks (private bank, NBFC, IT, FMCG, PSU, metal, pharma, holdco, small cap, Oct 2025 IPO): all 10 resolve, all 10 have quarterly results from 2018 (IPO from listing), all 10 have prices from both sources. Banks file a separate banking taxonomy (NII, PPOP, provisions, advances, deposits, GNPA %, CET1); consolidated bank filings leave the ratios blank (tagged 0.0), so those come from the standalone filing. Quarterly history goes back to 2018 only; 10-year annual history needs another source (Screener export or annual-report XBRL) - next.

## 12b. Phase 2 status (25 Nov 2026)

Valuation engine built (`backend/src/eqr/valuation/`, formulas in `docs/FORMULAS.md`). 13 value formulas and 9 quality/safety checks, sector-aware blend, reverse DCF and implied ROE, confidence with red flags. Run: `uv run python scripts/value.py TCS "HDFC Bank"`. Two independent code reviews done, findings fixed.

Observation from the 10 test stocks: on CAPM costs of equity (10.5-14.5%) with conservative growth, the classic formulas call most Indian large caps fairly valued or overvalued. The reverse DCF / implied ROE line shows the gap (HUL priced for 23% FCF growth vs 6.5% history; HDFC Bank for 27% ROE vs 14%). Whether the signal predicts anything is for the Phase 7 backtest.

Next: Phase 3 (Claude research agent: news, regulation, catalysts), standalone bank asset-quality ratios, holding-company sum-of-the-parts.

## 12c. Phases 3 and 5 status (25 Nov 2026)

Phase 3, research agent (`backend/src/eqr/research/`, `scripts/research.py`): Claude via the local Claude Code CLI on the user's own login, isolated (temp dir outside HOME, no user settings/hooks/MCP, API-key env vars stripped). Inputs: company facts and our valuation, NSE announcements (120 days), and the text of key filings (results, call transcripts, acquisitions) downloaded and extracted locally because NSE's archive times out for web fetch. Output is a typed report; every catalyst/regulation must cite a URL that Claude's tools actually returned or one of the NSE documents, so invented sources are dropped. A run with no web research is refused. Sonnet takes 1-3 minutes per company; results cached 12 hours.

Phase 5, sectors (`backend/src/eqr/sectors/`, `scripts/sectors.py`): NSE's official daily all-index file (169 indices with P/E) instead of Yahoo, which lacks most sector indices. 32 sectors scored on 3m/6m strength vs Nifty 50 and trend; 13 indices only exist since 2026 and are marked "short history". Related sectors = curated economic links (with reasons) plus co-movement after removing the market, each with its measured correlation.

Phase 4 (Grok sentiment) is blocked on an xAI API key; no grok CLI on this machine.

## 13. Open decisions

1. Prices: DECIDED 25 Nov 2026: yfinance (free, delayed). Kite Connect stays available as a drop-in adapter later.
2. Claude path: DECIDED 25 Nov 2026: own subscription via `claude -p` / Agent SDK, run locally. API key kept as a later switch behind the provider interface.
3. Grok: xAI API key with a monthly cap?
4. Stack: Next.js + FastAPI (recommended), or all-Python with Streamlit (faster to build, plainer UI)?

## Sources

- Anthropic subscription OAuth policy: https://code.claude.com/docs/en/legal-and-compliance , https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access , https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/ , https://www.theregister.com/ai-ml/2026/05/14/anthropic-tosses-agents-into-the-api-billing-pool/5240748
- xAI pricing: https://docs.x.ai/developers/pricing , https://runtimewire.com/article/xai-is-changing-the-economics-of-x-search-runtimewire-was-built-for-a-narrower-r
- Kite Connect pricing: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis , https://www.marketcalls.in/fintech/zerodha-makes-trading-api-free-for-personal-use-bundles-historical-data-with-connect-api.html
- Indian data options: https://github.com/onlyoneaman/dalal , https://tapetide.com/compare/best-api-indian-stock-market-data
- SEBI RA and AI disclosure: https://taxguru.in/?p=1045785 , https://www.taxmann.com/post/blog/sebi-master-circular-for-research-analysts-fees-dual-registration-renewals/
- SEBI enforcement on unregistered tips: https://webiis08.mondaq.com/india/securities/1726258/sebis-crackdown-on-finfluencers-regulations-and-enforcement , https://rhnvrm.github.io/stock-market-circulars/circulars/sebi/2026/sebi-2026-04-30-1c57bcaedfe3bf77-order-in-the-matter-of-unregistered-investment-advisor-research-analyst-activiti/
- NSE delayed data tariff: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Download_15mins_delayeddata_tariff.pdf
