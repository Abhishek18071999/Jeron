# Momentum v1: monthly 12-1 momentum leaders (invest tier)

Status: pre-registered on 2026-10-18, before any run on data. Asked for by Abhishek
("add the next strategies"), item 5 of the returns roadmap
(project files, `jeron/roadmap-returns.md`). Run it once with
`python -m app.cli backtest --strategy momentum`.

## Why
Every Jeron strategy so far buys a chart setup and waits for it with most of the
capital in cash. Price momentum, owning the stocks that rose most over the past year
(skipping the latest month) and replacing them as they fade, is one of the most studied
effects in stock returns, including Indian stocks (NSE runs momentum indices built on
it). It trades monthly, not daily, so it pays fewer costs and less short-term tax, and
it doesn't need the quarterly results that the long-term section is waiting for.

It is not a new kind of reason to buy compared with `rs-pullback-v1` (both lean on
relative strength), so the report gives the correlation of its daily returns with
rs-pullback's, as v3 did.

## The momentum rank
For each stock and session `t`, using only data up to `t`:
- **12-1 return:** close at `t - 21` over close at `t - 252`, minus 1 (adjusted
  closes; the latest month is skipped because one-month returns tend to reverse);
- **volatility:** the standard deviation of daily returns over the last 252 sessions, at
  least 200 of them defined;
- **momentum score:** 12-1 return divided by volatility (risk-adjusted, so a quiet steady
  riser ranks above a wild one with the same return);
- **momentum rank:** the score's percentile (0 to 1) among that day's universe, as
  `rs6_rank` is. NaN outside the universe or when either input is missing.

## Rules, fixed now
- **Tier:** invest (long-term section): at most 15 positions, book half at +3R, trail
  4 x ATR(14), exit if not +1R within 250 sessions. Sizing, heat, drawdown brake, costs
  and fills are the engine's (`engine-v3`), unchanged.
- **Rebalance day:** the first session of each calendar month.
- **Entry** at the close of a rebalance day when the stock's momentum rank is at least
  `min_rank`. No trend or regime filter: the engine already halves risk when the
  market is risk-off.
- **Exit** at the next open after a rebalance day on which the momentum rank is below
  0.75 (the stock left the top quarter). An unknown rank is not an exit. All the tier's
  other exits (stop, breakeven, trail, time stop) also apply.
- **Busy days:** the engine's existing order (highest tech-v1 score first). Most
  rebalance days have more candidates than free slots or open-risk room.

Grid: `min_rank` in {0.9, 0.95}, `stop_atr` in {3.0, 4.0}. Four variants. The exit
level (0.75) and the 12-1 and 252-session windows are fixed, not tuned.

## How it is judged
- Spec section 6, all seven checks, on the walk-forward folds and holdout used by every
  other strategy; out-of-sample and after-cost numbers only.
- The deflated Sharpe is reported against its own grid and against every variant tried
  so far: 60 strategy variants, the combined book and these 4, 65 trials.
- The holdout year has been looked at for other strategies, not for this one; it is
  read once, after the run.
- If it passes, it is live-eligible: paper trading with alerts in the long-term section,
  then the paper gate (3 months, 30 trades) before real money. With monthly entries and
  long holds it trades less than rs-pullback, so 30 paper trades may take longer.
- Run once. No rule above changes after seeing a result; a change is `momentum-v2`.

## Building it
- `Market.mom_rank` (`app/backtest/market.py`, `momentum_ranks`).
- `MOMENTUM` in `app/backtest/strategies.py`, `registered_on` 2026-10-18, with its exit
  condition; the signal's reasons give the rank and the 12-1 return.
- Tests: the rank uses no future data and is a universe percentile; entries only on
  rebalance days; the exit only on rebalance days below 0.75; it runs through the
  walk-forward.
