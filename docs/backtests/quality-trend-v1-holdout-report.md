# quality-trend-v1 with its holdout tested at last, 2026-11-11

`quality-trend-v1` had the best test years of any version and had never traded its
holdout: Jeron's quarterly results stopped at December 2024, so from early 2025 every
fundamental score went stale and the strategy sat in cash. This report closes that gap.

**Verdict: it passes all seven section 6 checks and has the best test-year numbers of any
version, but its holdout year lost money, so its evidence rating is weak.** It earns a
paper account. It has not earned real money, and it does not displace `fip-momentum-v1`
or `momentum-v1`, whose holdouts made money.

## Why the results had stopped, and the fix

NSE's "Financial Results" list ends with the December 2024 quarter. From the March 2025
quarter, companies file under **"Integrated Filing - Financials"**, a different list on
nseindia.com (SEBI's integrated filing rule). Saving the old CSV again would never have
brought in a later quarter. The owner's install has the same gap.

The new list answers a plain request through `app/data/http.py`'s `Fetcher`, and
`app/data/fundamentals.py` `parse_xbrl` reads the new XBRL files unchanged (same `OneD`,
`OneI` and `FourD` contexts). Two small scripts in `nse-2026-11-11/scripts/` do the rest:

- `integrated_fetch.py` saves the list for each quarter end (seven quarters, March 2025
  to September 2026: 30,251 filings);
- `integrated_csv.py` writes them as a CSV with the Financial Results columns, which
  `fundamentals-import` loads as it is. Each filing is dated by the later of its
  broadcast and creation times, so nothing is known before the exchange showed it.

Loaded into the research database of `residual-momentum-v1-report.md`: 25,359 filings
from the seed (2016 to 2024; 192 unreadable) and 9,545 from the new list (2 unreadable),
1,110 to 1,340 companies a quarter through September 2026. Spot checks of March 2025
quarters line up with the quarters before them.

## The run

`python -m app.cli backtest --strategy quality-trend`, once, no rule changed. Same
database, folds and holdout (2025-11-10 to 2026-11-09) as the four momentum runs.

| | Trades | Expectancy | Profit factor | CAGR | Max drawdown | Sharpe | Holdout | Holdout return | Checks | Evidence | Deflated Sharpe, own grid | against all 74 variants |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **quality-trend-v1** | 224 | 0.675R | **2.20** | **18.1%** | 14.7% | **0.97** | +0.046R (63), profit factor 0.60 | **-6.1%** | 7 of 7 | **weak** | 0.97 | 0.46 |
| fip-momentum-v1 | 202 | 0.416R | 1.79 | 13.9% | 13.5% | 0.71 | +0.549R (43), 2.48 | +11.5% | 7 of 7 | strong | 0.95 | 0.24 |
| momentum-v1 | 209 | 0.685R | 1.79 | 13.0% | 15.0% | 0.64 | +0.594R (40), 2.36 | +24.0% | 7 of 7 | moderate | 0.89 | 0.19 |
| rs-pullback-v1 | 279 | 0.358R | 1.65 | 17.2% | 13.4% | 0.96 | -0.012R (54), 0.93 | +0.5% | 6 of 7 | weak | 0.97 | 0.45 |
| residual-momentum-v1 | 203 | 0.458R | 1.60 | 13.1% | 15.1% | 0.68 | +0.170R (45), 0.74 | 0.0% | 7 of 7 | weak | 0.95 | 0.22 |

Nifty 500: Sharpe 0.58 and a 38.3% drawdown in the test years, +0.2% in the holdout year.
`quality-trend-v1` by year: 2020 +0.41R (31 trades), 2021 +0.67R (44), 2022 +0.30R (46),
2023 +2.27R (34), 2024 +0.33R (30), 2025 +0.20R (39). Positive in bear, bull and sideways
regimes. Exits: 118 stops, 60 trailing stops, 56 breakeven stops, 37 "results weakened".

## Reading it

- **The test years are the best Jeron has.** Highest profit factor, CAGR and Sharpe of
  the five, every year positive, 11 of 12 evidence checks passed: the 95% interval of
  expectancy is +0.38R to +1.00R, it survives doubled slippage, higher charges, late
  entries, the loss of its five best trades and of its best year, and all four grid
  points are positive on their own.
- **The holdout year lost money.** The seventh check passes on the average R (+0.046R
  over 63 trades), but the profit factor is 0.60 and the account fell 6.1% with a 12.2%
  drawdown while the index was flat. The larger positions lost and the smaller ones won.
  This is the one evidence check it fails, and it is the one that matters most: the only
  year it never saw.
- **It is the only passing strategy that is not pure momentum,** and it correlates least
  with the others: 0.58 to 0.63 on daily returns, against 0.72 to 0.73 inside the
  momentum family. That is still high. It buys strong trends, filtered by fundamentals.
- **Against every variant tried (74 with its grid counted), its deflated Sharpe is 0.46,**
  level with `rs-pullback-v1` and about twice the momentum versions'. None is near 0.95.
- **Its 2026-11-06 numbers were understated,** not overstated: 201 trades, 0.637R, Sharpe
  0.76, with 2025 spent in cash. With the results present, 2025 traded and was positive.

## What follows

1. `quality-trend-v1` is live-eligible by the gates: a paper account with alerts in the
   long-term section. Weak evidence means no real money until the paper gate (3 months,
   30 trades) and a moderate or strong rating. The status is the owner's to set.
2. For it to trade at all on the install, the install needs the 2025-26 results. Until
   then its paper account stays in cash. The two scripts work as they are; a proper
   command (a `fundamentals-fetch` beside `fundamentals-import`, with tests, and run by
   `daily` in results season) is the lasting fix and is not built here.
3. Nothing is promoted over anything. Two versions made money in the year none of them
   had seen (`momentum-v1` +24.0%, `fip-momentum-v1` +11.5%); the version with the best
   history did not. That is the clearest sign in all of this that the ranking inside ten
   years of backtests does not carry forward, and why the paper accounts decide.
4. The honest portfolio reading: one long-term account each for `fip-momentum-v1`,
   `momentum-v1` and `quality-trend-v1` on paper is a better test than any one of them,
   because they fail in different years (momentum in 2024, quality-trend in 2025-26).

## Caveats

- Research database, not the install: see "About this database" in
  `residual-momentum-v1-report.md` (three index closes missing, no cross-check, no ASM
  list, no news labels). The install's own run is the one of record.
- 194 filings could not be read; a company whose filing is missing has a stale score for
  that quarter and is not bought.
- Revisions in the new list carry only a creation time; they are dated by it.
- No rule was changed and this is not a new trial: the same version, with the data it was
  always meant to have.

Files: `nse-2026-11-11/` (`runs.json` and `equity.json` now hold five runs, `gates.txt`,
`deflated-all.txt`, `scripts/`).
