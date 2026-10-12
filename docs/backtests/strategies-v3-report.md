# Strategy research v3: two strong candidates, neither passes section 6

Date: 2026-10-08. Runs 18 (`results-drift-v1`) and 19 (`sector-rotation-v1`), engine
`engine-v2`, idle cash at 6.5% a year, the same data as v2 (prices to 2026-10-01).
Rules and grids were fixed in `docs/plans/strategies-v3.md` and pushed before any run.

**Verdict: neither strategy passes all seven checks, so both stay research only: Jeron
paper-trades them but does not alert their signals.** Each fails exactly one check:

- **Post-results drift** has the best test-period record of any strategy Jeron has tried
  (0.475R a trade, profit factor 1.89, drawdown 9.2%, profitable in bull, bear and
  sideways markets) but lost in the holdout year: -0.329R over 34 trades.
- **Sector rotation** passes the holdout (+0.225R over 48 trades) but its Sharpe ratio,
  0.58, is just under buy-and-hold Nifty 500's 0.60.

Per the plan, no variant was added or changed after seeing these results.
`rs-pullback-v1` stays the only live-eligible strategy.

## Results (walk-forward test 2019-10-03 to 2025-10-01, after costs)

| | Post-results drift (C) | Sector rotation (D) | RS pullback (v2, passes) | Spec bar |
|---|---|---|---|---|
| Trades | 212 | 247 | 338 | >= 100 |
| Win rate | 46.7% | 41.7% | 39.6% | reported only |
| Expectancy | **0.475R** | 0.275R | 0.288R | > 0.15R |
| Profit factor | **1.89** | 1.54 | 1.44 | >= 1.3 |
| Max drawdown | **9.2%** | 15.2% | 18.3% | <= 20% |
| CAGR (with interest) | 17.5% | 12.1% | 14.7% | |
| Sharpe above 6.5% | **1.12** | **0.58** | 0.73 | > Nifty 500's 0.60 |
| Positive regimes | bull, bear, sideways | bull, sideways | bull, sideways | >= 2 of 3 |
| Holdout expectancy | **-0.329R** (34 trades) | +0.225R (48 trades) | +0.022R (51 trades) | > 0 |
| Holdout return | -3.3% | +7.9% | +5.8% | Nifty 500: -4.7% |
| Checks passed | 6 of 7 | 6 of 7 | 7 of 7 | 7 of 7 |
| Deflated Sharpe, own 4 variants | **0.98** | 0.86 | 0.92 | 0.95 |
| Deflated Sharpe, all 60 variants | 0.68 | 0.21 | (0.39 of 52) | 0.95 |
| Correlation with RS pullback (daily) | 0.50 | 0.55 | 1 | |

Post-results drift is the first strategy whose deflated Sharpe against its own grid
clears 0.95, and against all 60 variants tried so far it is the highest yet (0.68; the
next best was trend-breakout's 0.57). That makes it the strongest evidence of a real
edge in this project, and still not enough: the holdout says it did not work in the
last 12 months.

## By year (expectancy per trade)

| | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025* | Holdout |
|---|---|---|---|---|---|---|---|---|
| C: post-results drift | 1.69R | 0.71R | 0.61R | -0.05R | 0.85R | 0.02R | 0.23R | -0.33R |
| D: sector rotation | 0.22R | 0.41R | 0.48R | 0.02R | 1.07R | -0.30R | 0.06R | +0.22R |
| RS pullback | 0.61R | 0.41R | 0.36R | -0.13R | 1.23R | -0.13R | 0.12R | +0.02R |

\* part years. The drift strategy was about flat in 2022 and 2024, the two years that
hurt every other strategy, rather than losing. Its weakness is recent: 2024 onwards is
close to zero and the holdout is negative.

## Is it the settings?

Each grid point run on its own, with no choosing, over the same test years:

| Variant | Test trades | Expectancy | Profit factor | Holdout |
|---|---|---|---|---|
| C jump 5%, stop 2.5 ATR (chosen) | 212 | 0.48R | 1.89 | -0.33R (34) |
| C jump 5%, stop 3 ATR | 179 | 0.36R | 1.59 | +0.21R (30) |
| C jump 8%, stop 2.5 ATR | 201 | 0.34R | 1.69 | -0.03R (37) |
| C jump 8%, stop 3 ATR | 181 | 0.26R | 1.55 | -0.17R (35) |
| D top 2 sectors, stop 2.5 ATR | 299 | 0.26R | 1.45 | +0.20R (59) |
| D top 2 sectors, stop 3 ATR (chosen) | 247 | 0.28R | 1.54 | +0.22R (48) |
| D top 3 sectors, stop 2.5 ATR | 314 | 0.22R | 1.45 | +0.11R (60) |
| D top 3 sectors, stop 3 ATR | 264 | 0.27R | 1.52 | +0.23R (41) |

Every variant of both strategies clears 0.15R and a profit factor of 1.3 in the test
years, so neither result hangs on one lucky setting. The drift strategy's holdout
depends heavily on the setting (-0.33R to +0.21R on 30 to 37 trades each), which says
the holdout sample is too small to judge it either way. Sector rotation's holdout is
positive for every variant.

## Do they add something rs-pullback doesn't?

Partly. Daily returns correlate about 0.5 with rs-pullback's, so roughly half of each
strategy's ups and downs are the same market moves. The drift strategy's trades come
from a different reason (a results surprise, not a chart pattern) and it held up in the
years rs-pullback lost, which is what a second edge is for. A combined account was not
part of this plan and was not tested.

## What this means for Jeron

- After this merges, run `backtest --strategy results-drift --strategy sector-rotation`
  on your machine, then `paper`. Both are then paper-traded as research only: no
  Telegram alerts, and `/compare` tracks them. Nothing changes for rs-pullback.
- The drift strategy is the one to watch. If its paper record over the next months
  is positive and inside its backtest range, that is the evidence the holdout did not
  give. Changing its rules now to rescue the holdout would be fitting to the answer, so
  it stays as registered; any rule change later is a new version with a new test.
- Real money still needs a strategy to pass section 6 and then the paper gate.

## Caveats

- **Results dates** come from board-meeting intimations. A meeting that was postponed
  can be on the wrong day; the 2x volume rule filters most of those out. 19,278 reaction
  days were measured on universe stocks.
- **Measured sectors**: only 52% of universe stock-days could be assigned a sector.
  Capital goods, chemicals and several other industries have no NSE index going back to
  2016, so their stocks either map to the closest index or to none. The measured sector
  avoids the survivorship bias of using today's Nifty 500 industry list.
- Same as before: GSM exclusion only from 2020, ASM not point in time, sector caps and
  the correlation check not simulated, benchmark without dividends.
- The deflated Sharpe "all variants" figure uses each variant's Sharpe on the full
  pre-holdout period (2017 to 2025) as the trial set, as in v2.
- The holdout was looked at once, after the rules were fixed.
