# Strategy research v2: the RS-leader pullback passes section 6

Date: 2026-10-04. Runs 13 and 14 (new strategies) and 15 to 17 (the M3 strategies
re-run on the same data, identical to the M3 report). Engine `engine-v2`, idle cash at
6.5% a year. Candidates and grids were fixed in `docs/plans/strategies-v2.md` before
any of them was run.

**Verdict: `rs-pullback-v1` passes all seven checks and is live-eligible, which in
Jeron means it moves to paper trading with alerts.** It is not proof of an edge: its
holdout year was about breakeven, it lost in 2022 and 2024, and against all 52
variants tried so far its deflated Sharpe is 0.39 (0.95 would mean unlikely to be
luck). The spec's paper gate (3 months, 30 trades, expectancy above 0 and inside the
backtest's range) is what should decide whether it ever gets real money.
`trend-breakout-v1` has the better numbers but fails two checks.

## Results (walk-forward test 2019-10-03 to 2025-10-01, after costs)

| | Trend breakout (A) | RS-leader pullback (B) | Best M3: 52-week breakout | Spec bar |
|---|---|---|---|---|
| Trades | 298 | 338 | 440 | >= 100 |
| Win rate | 39.9% | 39.6% | 33.9% | reported only |
| Expectancy | 0.319R | 0.288R | 0.179R | > 0.15R |
| Profit factor | 1.50 | 1.44 | **1.23** | >= 1.3 |
| Max drawdown | 13.4% | 18.3% | 16.9% | <= 20% |
| CAGR (with interest) | 17.1% | 14.7% | 11.2% | |
| Sharpe above 6.5% | 0.92 | 0.73 | **0.40** | > Nifty 500's 0.60 |
| Positive regimes | **bull only** | bull, sideways | bull, bear | >= 2 of 3 |
| Holdout expectancy | **-0.014R** (46 trades) | +0.022R (51 trades) | +0.133R (92 trades) | > 0 |
| Holdout return | +1.9% | +5.8% | +3.8% | Nifty 500: -4.7% |
| Checks passed | 5 of 7 | **7 of 7** | 5 of 7 | 7 of 7 |
| Deflated Sharpe, own 4 variants | 0.96 | 0.92 | 0.84 | 0.95 |
| Deflated Sharpe, all 52 variants | 0.57 | 0.39 | 0.14 | 0.95 |

Nifty 500 over the test period: CAGR 16.7%, Sharpe above 6.5% of 0.60, max drawdown
38.3%. Interest on idle cash is part of the CAGR: ₹3.9 lakh of B's ₹13.1 lakh pre-tax
gain, ₹4.4 lakh of A's ₹15.8 lakh.

Trend breakout fails the regime check by construction: it only buys in a bull market,
so all its trades are bull trades. That should have been seen before the run; the rule
stays as registered rather than being changed after the result.

## By year (expectancy per trade)

| | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025* | Holdout |
|---|---|---|---|---|---|---|---|---|
| A: trend breakout | 0.13R | 0.90R | 0.52R | -0.08R | 0.66R | -0.15R | 0.22R | -0.01R |
| B: RS pullback | 0.61R | 0.41R | 0.36R | -0.13R | 1.23R | -0.13R | 0.12R | +0.02R |

\* part years. Both lost in 2022 and 2024, the same years every M3 strategy lost.
B's average leans on 2023 (1.23R over 44 trades).

## Is it the settings?

No. Each of the eight grid points run on its own, with no choosing, over the same test
years:

| Variant | Test trades | Expectancy | Profit factor | Holdout |
|---|---|---|---|---|
| A volume 1.5x, stop 2.5 ATR | 307 | 0.36R | 1.65 | -0.15R |
| A volume 1.5x, stop 3 ATR | 262 | 0.33R | 1.63 | -0.01R |
| A volume 2x, stop 2.5 ATR | 305 | 0.33R | 1.50 | +0.18R |
| A volume 2x, stop 3 ATR | 268 | 0.37R | 1.64 | +0.03R |
| B top 20% RS, stop 2 ATR | 392 | 0.22R | 1.34 | -0.03R |
| B top 20% RS, stop 3 ATR | 256 | 0.43R | 1.77 | -0.08R |
| B top 10% RS, stop 2 ATR | 417 | 0.28R | 1.37 | +0.05R |
| B top 10% RS, stop 3 ATR | 269 | 0.30R | 1.52 | +0.03R |

Every variant clears 0.15R and a profit factor of 1.3 in the test years, which the M3
strategies never did. The holdout is weak for all of them (-0.15R to +0.18R): the
last 12 months were a falling market, and the edge did not show there.

## What changed from M3

Restricting to relative-strength leaders (top fifth or tenth of the universe by
6-month return against Nifty 500) and to stocks with 50-day EMA above 200-day roughly
doubled the expectancy of both the breakout and the pullback. Exits, sizing and costs
are unchanged.

## What this means for Jeron

- On your machine, after this merges, run the backtest for the two strategies. The
  paper job then trades `rs-pullback-v1` as a live-eligible strategy: its signals are
  alerted on Telegram, and `/compare` tracks it against the paper gate.
- No real money until the paper gate passes (spec section 7). With roughly 55 trades
  a year, 30 paper trades takes about 6 months.
- `trend-breakout-v1` stays research only (paper-traded, not alerted).

## Caveats

- Same as M3: GSM exclusion only from 2020, ASM not point in time, sector caps and the
  correlation check not simulated, benchmark without dividends.
- The deflated Sharpe "all variants" figure uses each variant's Sharpe on the full
  pre-holdout period (2017 to 2025) as the trial set, as the per-strategy figure does.
- The holdout was looked at once, after the rules were fixed.
