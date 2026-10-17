# Combined book v1: rs-pullback and results drift in one account

Status: pre-registered on 2026-10-17, before any combined run. Not built yet: the
engine trades one strategy at a time, so running this needs the change described under
"Building it".

## Why
`rs-pullback-v1` is the only strategy that passes spec section 6, and it leaves a lot of
cash idle: ₹3.9 lakh of its ₹13.1 lakh backtest gain was interest on cash.
`results-drift-v1` had the best test-period record (0.475R, profit factor 1.89) but lost
in the holdout. The two strategies' daily returns correlate about 0.5, and they buy for
different reasons (a chart pattern, a results surprise). One account trading both should
keep more capital at work and lean less on one edge. The v3 report flagged this as
untested (`docs/backtests/strategies-v3-report.md`).

## Rules, fixed now
- **Strategies:** `rs-pullback-v1` and `results-drift-v1`, with no change to either
  one's entry, stop or exit rules. Each one trades the grid point its own walk-forward
  chose for that fold (the schedule in its own run). Nothing new is chosen.
- **Engine:** `engine-v3` (M8): open-only fills and no 2% or 5% price bands.
- **One account:** ₹10 lakh, 1% risk per trade with the engine's halvings (risk-off
  regime, 10% drawdown) and its pause after a 15% drawdown. At most 8 open positions in
  total (both are positional; the positional limit), 6% total open risk, 20% of equity
  and 1% of 20-day average volume per position. Idle cash earns 6.5% a year, as in every
  other run.
- **One position per stock:** a stock already held or ordered by either strategy is
  skipped.
- **Order on a busy day:** when the two strategies have more signals than free slots,
  the strategy with fewer open positions in the book goes first; on a tie,
  `rs-pullback-v1` goes first. Within a strategy, the engine's existing order (highest
  tech-v1 score first).
- **Not in the backtest:** the 30% sector cap and the correlation check. NSE's archive
  has no point-in-time sectors, so they can't be simulated honestly; the paper account
  applies them, as for every other strategy.

## How it is judged
- The same walk-forward folds and holdout as v2 and v3, out-of-sample and after-cost
  numbers only, against the same seven section 6 checks. The report sets the combined
  book beside each strategy alone on `engine-v3`.
- It counts as one new trial: the deflated Sharpe is reported against all 61.
- **The holdout is not a clean test here:** both strategies' holdout results were
  already seen. The report says so, and the evidence that decides is paper trading.
- If it passes section 6, it is paper-traded with alerts as a strategy of its own, and
  its paper gate (3 months, 30 trades, expectancy above 0 and inside the backtest's
  range) applies before any real money. If it fails, it is paper-traded as research only.
  Either way `rs-pullback-v1` keeps its own account.
- Run once. No rule above changes after seeing the result; any change is a
  `combined-book-v2` with its own plan.

## Building it
- `simulate` takes a schedule of variants for one tier. The combined book needs both
  strategies' entries each day, tagged with their strategy, and the order rule above
  when slots are short. Every other rule (fills, exits, sizing, costs) stays the
  engine's, so the golden tests in `tests/test_backtest_engine.py` must pass unchanged.
- A test with two made-up strategies checks the busy-day order, the one-position-per-
  stock rule and the shared limits before the real run.
