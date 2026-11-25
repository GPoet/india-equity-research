# Valuation formulas used

Each formula below runs on every company where it applies. Code: `backend/src/eqr/valuation/`.
Rates are from `backend/config/market_inputs.toml` (dated, with sources).

## Inputs shared by most formulas

| Input | How it is set |
|---|---|
| Rupee risk-free rate | 10-year G-sec yield minus India's sovereign default spread (Damodaran's method): 7.30% - 1.87% = 5.43% |
| Cost of equity (Ke) | Risk-free + beta x equity risk premium (7.08%, Damodaran Jan 2026). Beta: 2 years of weekly returns vs Nifty 50, Blume-adjusted |
| WACC | Market-value weights of equity and debt; cost of debt = finance costs / debt, kept between the G-sec yield and G-sec + 6% |
| Growth | The lower of revenue-per-share and profit-per-share growth over up to 5 years, kept between 0 and 20%. Revenue only when profits are cyclical (a loss, or a fall of more than 30% in a year). Per share so that mergers paid in stock do not count as growth; bonus issues and splits are adjusted using the filings |
| Terminal growth | 5% nominal, below the rupee risk-free rate |

## Value per share

| Formula | Who uses it | Equation | Notes |
|---|---|---|---|
| Discounted cash flow (FCFF) | Damodaran, institutional analysts | PV of free cash flow (CFO - capex) for 10 years (5 at growth g, 5 fading to terminal) + terminal value, at WACC; minus debt, plus cash | Base = average of up to 3 years of free cash flow. Not for lenders |
| Reverse DCF | Michael Mauboussin | Growth rate at which the DCF equals today's price | Shows what the market is betting on |
| Owner earnings | Warren Buffett (1986 letter) | Profit + depreciation - maintenance capex, valued over 10 years | Buffett discounts at the bond rate and asks for a wide margin of safety; here it is discounted at cost of equity |
| Maintenance capex | Bruce Greenwald | Capex - (PPE / sales) x increase in sales | Falls back to min(capex, depreciation) |
| Earnings power value | Bruce Greenwald | After-tax operating profit / WACC, minus debt plus cash | The business with zero growth: a floor |
| Graham number | Benjamin Graham | sqrt(22.5 x EPS x book value per share) | Most a defensive investor should pay (P/E 15 x P/B 1.5) |
| Graham formula (1974) | Benjamin Graham | EPS x (8.5 + 2g) x 4.4 / Y | g capped at 15%; Y = Indian AAA corporate yield (G-sec + 0.71) |
| PEG fair value | Peter Lynch | Fair P/E = growth rate (capped at 25); also (growth + dividend yield) / P/E | Lynch wanted 2 or more; below 1 is expensive |
| Sticker price | Phil Town (Rule #1) | EPS x (1+g)^10 x future P/E / 1.15^10; buy at half | Future P/E = lower of 2 x growth and historical median P/E |
| Dividend discount | John Burr Williams, Gordon | Two-stage PV of dividends at cost of equity | Only for steady payers (payout 30%+, 4 of 5 years) |
| Residual income | Edwards-Bell-Ohlson; standard for banks | Book value + PV of (ROE - Ke) x book; ROE fades to Ke after 5 years | Main model for banks and NBFCs |
| Justified P/B | Gordon growth; banks | Fair P/B = (ROE - g) / (Ke - g) | |
| Reverse residual income | Damodaran, for banks | ROE at which residual income equals today's price | The lender version of the reverse DCF |

## Quality and safety

| Formula | Who uses it | What it checks | Cutoff |
|---|---|---|---|
| Piotroski F-score | Joseph Piotroski | 9 yes/no tests on profitability, leverage, liquidity and efficiency | 7-9 strong, 0-3 weak |
| Altman Z'' (emerging markets) | Edward Altman | Bankruptcy risk from working capital, reserves, operating profit and leverage | Safe above 5.85, distress below 4.15 |
| Beneish M-score | Messod Beneish | Signs of earnings manipulation (8 ratios) | Above -1.78 is a red flag |
| Magic formula | Joel Greenblatt | Earnings yield (EBIT/EV) and return on capital | Here: yield above the G-sec and ROC 25%+ |
| Coffee Can | Saurabh Mukherjea (Marcellus) | Revenue growth 10%+ and ROCE 15%+ every year for 10 years (lenders: ROE 15%+) | Checked on the years available |
| Buffett checks | Warren Buffett | ROE 15%+, debt below half of equity, steady profit growth, no losses | All must pass |
| $1 retained-earnings test | Warren Buffett | Market value created per rupee of earnings retained | At least 1; skipped for companies that pay out almost everything |
| Earnings yield vs bonds | Buffett, the "Fed model" | Earnings / price against the 10-year G-sec | |
| ROIC vs WACC | Buffett, Munger, Mauboussin | Whether returns on capital beat the cost of capital (a moat) | |

## How the fair value is combined

| Company type | Weights |
|---|---|
| Operating company | DCF 30%, owner earnings 25%, EPV 15%, Graham formula / Lynch / Rule #1 7.5% each, DDM 5%, Graham number 2.5% |
| Lender (bank, NBFC) | Residual income 40%, justified P/B 25%, DDM 15%, Graham formula / Lynch 7.5% each, Graham number 5% |

Weights are renormalised over the formulas that could run (at least 3). A formula that returns a negative equity value counts as zero and raises a red flag. The range runs from the weighted 25th to 75th percentile of the formula values, widened to include the weighted mid. "Buy below" = mid minus the 15% margin of safety.

Signal: Undervalued only when the price is below both the range and the buy-below price; Overvalued only when it is above both the range and mid plus 15%. Otherwise Fairly valued. This keeps small price moves from flipping the signal.

Confidence (high / medium / low) drops for each of: fewer than 2 core models, models disagreeing (range wider than 60% of the mid), fewer than 5 formulas, any red flag (Altman distress, Beneish manipulation, weak Piotroski, ROIC below WACC, a negative model value), and data-quality warnings (mis-tagged share capital, unconfirmed share jumps, missing years, stale market inputs). Confidence measures how much the models agree on clean data, not whether the market will agree.

## Share counts, bonuses and splits

- Share count = paid-up capital / face value, cross-checked against profit / EPS; if they differ by more than 5% the filing is mis-tagged and profit / EPS is used (seen in Bajaj Holdings).
- Splits are read from face-value changes. A bonus is recognised only for the standard a:b forms (a, b up to 5, plus 1:10), within 1.5%, between years with exact share counts, and only when the balance sheet shows no money came in. Anything else is treated as real dilution, so a merger paid in shares does not look like growth.
- Yahoo's split list is not used (it missed Bajaj Finance's 2025 bonus); its price and dividend history is adjusted correctly and is used.

## Known limits

- Balance sheets in NSE results XBRL start in FY23, and full-year cash flows exist only for some years, so 10-year tests (Coffee Can) run on fewer years.
- Holding companies need sum-of-the-parts on their listed stakes; that is not built, so their values are rough.
- Bank asset-quality ratios (GNPA, NNPA, CET1) come from the standalone filing, not loaded yet.
- These formulas were built for US markets at lower valuations. On Indian large caps they often show "overvalued"; the reverse DCF and implied ROE show what the market is pricing in instead.
