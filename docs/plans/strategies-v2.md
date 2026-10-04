# Strategy research v2: pre-registered candidates

Status: pre-registered on 2026-10-04, before any of these rules was run on data.
Results: `docs/backtests/strategies-v2-report.md`.

## Why
None of the M3 strategies passes spec section 6 (`m3-backtest-report.md`): small edge
(best 0.19R, profit factor 1.25), results that depend on the year (2022 lost, the
breakout lost in 2024 and 2025), and an entry rule that isn't selective (tech-v1 had
40,849 qualifying signals skipped for lack of slots). The report's suggestion was a
trend breakout restricted to the strongest stocks.

## Rules of the test (unchanged from M3)
- Exits, sizing and costs are spec section 5's and the engine's; only the entry
  condition and the stop distance differ.
- Same walk-forward folds, the same holdout (2025-10 to 2026-10), out-of-sample and
  after-cost numbers only, and every grid point is logged.
- Candidates and grids below are fixed now. If none passes, the result is reported as
  is; no new variants are added after seeing the holdout.
- The deflated Sharpe is reported twice: against the strategy's own grid, and against
  every variant tried so far in M3, M6 and this research (all of them are trials).

## New input: relative-strength rank
`rs6_rank`: each day, the stock's 6-month return relative to the Nifty 500, as a
percentile (0 to 1) among the stocks in the scan's universe that day. It is the same
ranking tech-v1 already uses for its RS points, only exposed on its own.

## Candidate A: `trend-breakout-v1` (positional)
Enter at the close when all hold:
- close above the highest high of the previous 252 sessions;
- volume at least `volume_x` times the 20-day average;
- close > 50-day EMA > 200-day EMA;
- `rs6_rank` >= 0.8 (top fifth of the universe);
- the market regime is bull (Nifty 500 above its 200-day EMA, EMA rising over 20
  sessions).

Grid: `volume_x` in {1.5, 2.0}, `stop_atr` in {2.5, 3.0}. Four variants.

## Candidate B: `rs-pullback-v1` (positional)
Enter at the close when all hold:
- `rs6_rank` >= `min_rs` (a leader);
- close > 50-day EMA > 200-day EMA;
- the day's low touched the 20-day EMA (low <= EMA20) and the close held above it;
- the market regime is not bear.

Grid: `min_rs` in {0.8, 0.9}, `stop_atr` in {2.0, 3.0}. Four variants.

## Pass mark
Spec section 6, all gates, on the out-of-sample record: expectancy > 0.15R, profit
factor >= 1.3, max drawdown <= 20%, at least 100 trades, positive in at least 2 of 3
regimes, Sharpe above buy-and-hold Nifty 500. A pass also needs a positive holdout.
