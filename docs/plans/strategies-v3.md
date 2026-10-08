# Strategy research v3: post-results drift and sector rotation

Status: pre-registered on 2026-10-08, before any of these rules was run on data.
Results: `docs/backtests/strategies-v3-report.md`.

## Why
Only `rs-pullback-v1` passes spec section 6, and its edge is thin (holdout about
breakeven, losses in 2022 and 2024). One strategy is one point of failure. The goal here
is a second edge that behaves differently: an entry reason other than "a relative-strength
leader in an uptrend", so its good and bad years need not line up with rs-pullback's.

Two ideas with long records in the research literature, both testable on data Jeron
already stores:
- **Post-earnings drift:** prices keep moving for weeks in the direction of a strong
  results surprise. Jeron has no fundamentals yet, so the surprise is measured the way
  much of that literature does without analyst estimates: the price reaction itself
  (the earnings-announcement return).
- **Sector momentum:** sectors that led over the last few months tend to keep leading
  for a while. Money moves between sectors, and individual stocks ride it.

## Rules of the test (unchanged from M3 and v2)
- Exits, sizing and costs are spec section 5's and the engine's; only the entry
  condition and the stop distance differ.
- Same walk-forward folds, the same holdout (the latest 12 months), out-of-sample and
  after-cost numbers only, and every grid point is logged.
- Candidates and grids below are fixed now. If none passes, the result is reported as
  is; no new variants are added after seeing the holdout.
- The deflated Sharpe is reported against the strategy's own grid and against every
  variant tried so far (52 before this research, 60 with it).
- New: the report also gives the correlation of each candidate's daily out-of-sample
  returns with rs-pullback-v1's, since the point is a second, different edge.

## Candidate C: `results-drift-v1` (positional)
The results calendar is the board meetings table (`app/data/events.py`, purpose
classified as results). For each results meeting of a stock:
- meeting session `m`: the first session on or after the meeting date; reaction session
  `r = m + 1` (most companies publish after the close, so the reaction may land on `r`;
  measuring from the close before `m` also covers results published during `m`);
- reaction: the stock's return from the close of session `m - 1` to the close of `r`,
  minus Nifty 500's over the same sessions.

Enter at the close of `r` when:
- the reaction is at least `min_jump`;
- volume on `m` or `r` is at least 2x its 20-day average (the meeting really happened
  and the market noticed).

No trend or market-regime filter: the drift is a reaction to news, and v2 showed that a
bull-only filter fails the regime check by construction.

Grid: `min_jump` in {0.05, 0.08}, `stop_atr` in {2.5, 3.0}. Four variants.

## Candidate D: `sector-rotation-v1` (positional)
Sectors are NSE's sectoral indices with history from 2016: Nifty Auto, Financial
Services, PSU Bank, Energy, FMCG, IT, Media, Metal, Pharma and Realty.

- **Which sector a stock belongs to** is measured, not looked up: Jeron only knows the
  industry of today's Nifty 500 members, so using it would trade survivors only. Every
  21 sessions, each stock is assigned to the sector index its daily returns, in excess of
  Nifty 500's, are most correlated with over the last 252 sessions (at least 200 days of
  returns, correlation at least 0.2; otherwise no sector). The assignment holds until
  the next one. Only data up to the day is used.
- **Sector strength:** each sector index's 63-session return minus Nifty 500's, ranked
  among the ten sectors each day (1 = strongest).

Enter at the close when:
- the stock's sector ranks in the top `top_n`;
- the close is above the highest high of the previous 50 sessions (a fresh 10-week high);
- close > 50-day EMA > 200-day EMA;
- the market regime is not bear.

Grid: `top_n` in {2, 3}, `stop_atr` in {2.5, 3.0}. Four variants.

## Pass mark
Spec section 6, all gates, on the out-of-sample record: expectancy > 0.15R, profit
factor >= 1.3, max drawdown <= 20%, at least 100 trades, positive in at least 2 of 3
regimes, Sharpe above buy-and-hold Nifty 500. A pass also needs a positive holdout.
A strategy that passes is live-eligible, which in Jeron means paper trading with alerts;
real money still waits on the paper gate (spec section 7).
