# quality-trend-v1 with its holdout tested at last, 2026-11-11

`quality-trend-v1` had the best test years of any version and had never traded its
holdout: Jeron's quarterly results stopped at December 2024, so from early 2025 every
fundamental score went stale and the strategy sat in cash. This report closes that gap.

**Verdict: it fails. It has the best test-year numbers of any version and passes six of
the seven section 6 checks, but its holdout year lost money: -0.058R over 67 trades, the
account down 4.1%.** By the project's rule it is research only. It does not displace
`fip-momentum-v1` or `momentum-v1`, whose holdouts made money.

**Correction, same day.** The first run of this report (run 5) said 7 of 7 with a holdout
of +0.046R. That run was made on a faulty load: every 2025-26 filing carried a made-up
form name, and `quarter_of` treats any form but "Ind-AS New" as a lender, giving ordinary
companies a flat 5 quality points in place of the interest-cover test. With the forms
labelled correctly (run 6) the holdout is negative. Run 5 is kept in `runs.json`, never
overwritten; run 6 is the result. The mistake was in the data conversion, not in the
strategy, and no rule was changed between the two.

## Why the results had stopped, and the fix

NSE's "Financial Results" list ends with the December 2024 quarter. From the March 2025
quarter, companies file under **"Integrated Filing - Financials"**, a different list on
nseindia.com (SEBI's integrated filing rule). Saving the old CSV again would never have
brought in a later quarter. The owner's install has the same gap.

The new list answers a plain request through `app/data/http.py`'s `Fetcher`, and
`app/data/fundamentals.py` `parse_xbrl` reads the new XBRL files unchanged (same `OneD`,
`OneI` and `FourD` contexts). This is now a command, `python -m app.cli
fundamentals-fetch` (`docs/plans/fundamentals-fetch-v1.md`). The research load used two
scripts in `nse-2026-11-11/scripts/` that do the same thing:

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

`python -m app.cli backtest --strategy quality-trend`, no rule changed (run 6; see the
correction above). Same
database, folds and holdout (2025-11-10 to 2026-11-09) as the four momentum runs.

| | Trades | Expectancy | Profit factor | CAGR | Max drawdown | Sharpe | Holdout | Holdout return | Checks | Evidence | Deflated Sharpe, own grid | against all 74 variants |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **quality-trend-v1** | 224 | 0.684R | **2.28** | **18.2%** | 14.7% | **0.98** | **-0.058R (67), profit factor 0.77** | **-4.1%** | **6 of 7** | **weak** | 0.97 | 0.47 |
| fip-momentum-v1 | 202 | 0.416R | 1.79 | 13.9% | 13.5% | 0.71 | +0.549R (43), 2.48 | +11.5% | 7 of 7 | strong | 0.95 | 0.24 |
| momentum-v1 | 209 | 0.685R | 1.79 | 13.0% | 15.0% | 0.64 | +0.594R (40), 2.36 | +24.0% | 7 of 7 | moderate | 0.89 | 0.19 |
| rs-pullback-v1 | 279 | 0.358R | 1.65 | 17.2% | 13.4% | 0.96 | -0.012R (54), 0.93 | +0.5% | 6 of 7 | weak | 0.97 | 0.45 |
| residual-momentum-v1 | 203 | 0.458R | 1.60 | 13.1% | 15.1% | 0.68 | +0.170R (45), 0.74 | 0.0% | 7 of 7 | weak | 0.95 | 0.22 |

Nifty 500: Sharpe 0.58 and a 38.3% drawdown in the test years, +0.2% in the holdout year.
`quality-trend-v1` by year: 2020 +0.41R (31 trades), 2021 +0.67R (44), 2022 +0.30R (46),
2023 +2.27R (34), 2024 +0.33R (30), 2025 +0.26R (39). Positive in bear, bull and sideways
regimes. Exits: 118 stops, 60 trailing stops, 60 breakeven stops, 37 "results weakened".

## Reading it

- **The test years are the best Jeron has.** Highest profit factor, CAGR and Sharpe of
  the five, every year positive, 11 of 12 evidence checks passed: the 95% interval of
  expectancy is +0.39R to +1.02R, it survives doubled slippage, higher charges, late
  entries, the loss of its five best trades and of its best year, and all four grid
  points are positive on their own.
- **The holdout year lost money.** -0.058R over 67 trades, profit factor 0.77, the
  account down 4.1% with a 12.3% drawdown while the index was flat. It fails the seventh
  check and the matching evidence check, and it is the one that matters most: the only
  year it never saw.
- **It is the only passing strategy that is not pure momentum,** and it correlates least
  with the others: 0.58 to 0.63 on daily returns, against 0.72 to 0.73 inside the
  momentum family. That is still high. It buys strong trends, filtered by fundamentals.
- **Against every variant tried (74 with its grid counted), its deflated Sharpe is 0.47,**
  level with `rs-pullback-v1` and about twice the momentum versions'. None is near 0.95.
- **Its 2026-11-06 numbers were understated,** not overstated: 201 trades, 0.637R, Sharpe
  0.76, with 2025 spent in cash. With the results present, 2025 traded and was positive.

## What follows

1. `quality-trend-v1` is research only: it failed its holdout. Its signals stay out of
   alerts. Whether it keeps a research paper account is the owner's call; a year of
   forward paper results would say more than this one bad year.
2. The install needs the 2025-26 results whatever happens to this strategy: the stock
   page's fundamentals and fund-v1 score are stale without them. Run
   `python -m app.cli fundamentals-fetch --start 2025-03-31` once (about 9,500 filings,
   under three hours), then with no arguments in each results season.
3. Nothing is promoted over anything. Two versions made money in the year none of them
   had seen (`momentum-v1` +24.0%, `fip-momentum-v1` +11.5%); the version with the best
   history did not. That is the clearest sign in all of this that the ranking inside ten
   years of backtests does not carry forward, and why the paper accounts decide.
4. No `quality-trend-v2`. The tempting fix (tune the fundamentals filter until 2025-26
   turns positive) is exactly the search the holdout exists to stop.

## Caveats

- Research database, not the install: see "About this database" in
  `residual-momentum-v1-report.md` (three index closes missing, no cross-check, no ASM
  list, no news labels). The install's own run is the one of record.
- 194 filings could not be read; a company whose filing is missing has a stale score for
  that quarter and is not bought.
- Revisions in the new list carry only a creation time; they are dated by it.
- No rule was changed and this is not a new trial: the same version, with the data it was
  always meant to have. Two runs exist only because the first load was wrong.

Files: `nse-2026-11-11/` (`runs.json` holds six runs, `equity.json` the latest of each version, `gates.txt`,
`deflated-all.txt`, `scripts/`).
