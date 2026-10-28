# Reversal v1: short-term reversal of no-news losers (swing)

Status: pre-registered on 2026-10-28, before any run on data. Item 5 of the post-review
hardening plan (`docs/plans/post-review-v2.md`): a second strategy family that is not
momentum, chosen from a documented anomaly ("idea-first"), tested once. Run it once with
`python -m app.cli backtest --strategy reversal` (the autopilot does this by itself, as
it does for every untested version).

## Why this idea
Every live-eligible Jeron strategy, and most of the research ones, buys strength:
`rs-pullback-v1`, `trend-breakout-v1`, `momentum-v1`, `sector-rotation-v1` all rank
on relative strength, and their daily returns correlate 0.5 or more with each other. A
regime that hurts momentum (a violent rebound led by laggards, 2020 and 2022 in Jeron's
history) hurts all of them at once.

Short-term reversal is the opposite bet: the stocks that fell most over the last week
tend to recover part of it over the next one or two. It is one of the oldest documented
effects in stock returns (Jegadeesh 1990, "Evidence of predictable behavior of security
returns"; Lehmann 1990, "Fads, martingales and market efficiency"). Its best-known
refinement matters here: the reversal belongs to drops **without news**; drops on news
(results, announcements) tend to keep drifting (Chan 2003, "Stock price reaction to news
and no-news"; that drift is what `results-drift-v1` trades on the upside). So the rule
excludes stocks with results or bad news behind the fall.

It buys weakness, so it should do best in sideways, choppy markets, where momentum
struggles, and its returns should correlate little with rs-pullback's. Whether that is
true is a result to report, not an assumption.

Known risks, written down now: the effect is strongest in small, illiquid stocks (part
of it is the bid-ask bounce, which Jeron's universe of ₹5 crore median turnover mostly
removes); it trades often, so costs matter; and a stock that keeps falling is caught by
the stop, not avoided.

## The reversal rank
For each stock and session `t`, using only data up to `t`:
- **5-session return:** adjusted close at `t` over adjusted close at `t - 5`, minus 1;
- **reversal rank:** that return's percentile (0 lowest, 1 highest) among that day's
  universe, as `rs6_rank` is. NaN outside the universe or without the two closes.

## Rules, fixed now
- **Tier:** swing (at most 5 positions, book half at +2R, trail 2 x ATR(14), exit if not
  +1R within 15 sessions). Sizing, heat, drawdown brake, costs and fills are the
  engine's (`engine-v3`), unchanged.
- **Entry** at the close of a session when:
  - the stock's reversal rank is at most 0.10 (the 10% of the universe that fell most
    over 5 sessions);
  - no results session (the first session on or after a results board meeting) in the
    5 sessions up to and including `t`: the fall is not a results reaction;
  - the results blackout and the news filter of the `-events` versions: no entry from 3
    sessions before a results meeting through the meeting day, none while the news
    score is below 40.
  No trend, regime or score filter.
- **Its own exit:** sell at the next open after a session on which the reversal rank is
  at least 0.50 (the fall has been made up against the universe). An unknown rank is not
  an exit. The tier's other exits (stop, breakeven, T1, trail, time stop) also apply.
- **Stop:** 2.5 x ATR(14) below the signal close.
- **Busy days:** the engine's existing order (highest tech-v1 score first).
- **Needs** the results calendar (the events job); without it the strategy refuses to run
  rather than run without its news rule.

One grid point: `max_rank` 0.10, `stop_atr` 2.5. Nothing is tuned. This is the
"test the idea once" the review asked for: the deflated Sharpe pays for one trial, not
four.

## How it is judged
- Spec section 6, all seven checks, on the walk-forward folds and holdout used by every
  other strategy; out-of-sample and after-cost numbers only.
- Reported beside the gates: the correlation of its daily returns with
  `rs-pullback-v1`'s, its expectancy by regime (the idea predicts sideways best), and
  the deflated Sharpe against its own grid (one point) and against every variant tried so
  far.
- The holdout year has been seen for other strategies, not for this one; it is read
  once, after the run.
- If it passes, it is live-eligible: paper trading with alerts in the swing section,
  then the paper gate (3 months, 30 trades) and a moderate or strong evidence rating
  before any real money (decision 0018). The review's "only after paper trading" is kept
  by that ladder: nothing here lets it skip paper.
- Run once. No rule above changes after seeing a result; a change is `reversal-v2`.

## Building it
- `Market.rev_rank` and `Market.rev_return` (`app/backtest/market.py`, `reversal_ranks`).
- `REVERSAL` in `app/backtest/strategies.py`, `registered_on` 2026-10-28, with its exit
  condition; the signal's reasons give the 5-session fall and the rank.
- Tests: the rank uses no future data and is a universe percentile; no entry after a
  results session in the window; the exit at rank 0.50; it refuses to run without the
  results calendar; it runs through the walk-forward.
