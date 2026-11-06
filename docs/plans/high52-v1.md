# 52-week-high leaders v1 (invest tier)

Status: pre-registered on 2026-11-06, before any code or run on data. Asked for by
Abhishek ("develop the most profitable strategy possible, data-driven, thoroughly
validated"). Run it once with `python -m app.cli backtest --strategy high52`.

Nobody can promise "the most profitable strategy possible". This plan follows the
project's rule (post-review-v2): start from a documented effect, fix the rules before the
data, run once.

## Why this idea
George and Hwang, "The 52-Week High and Momentum Investing" (Journal of Finance, 2004):
ranking stocks by how close the price is to its 52-week high predicts future returns
better than past returns do, and the profits do not reverse in the long run. The reason
offered is anchoring: investors treat the 52-week high as a ceiling and under-react to
good news that would push a stock through it, so stocks near their high keep drifting
up. The effect has been reported in many markets since, including emerging ones; the
evidence for India is thinner, which is what this test is for.

It is chosen because:
- it is a documented anomaly with a behavioural reason, not a parameter search;
- it asks a clean question against `momentum-v1`: is nearness to the high a better
  monthly ranking than the 12-1 return? Rebalance day, exit shape and tier are the same;
- it trades monthly (low costs, mostly long-term tax) and needs only prices;
- it is not `breakout-52w` (a swing entry on the day of a new high); this is a monthly
  cross-sectional ranking held for months.

It is the same family as `momentum-v1` and `fip-momentum-v1` (relative strength); the
report gives the correlation of daily returns with both.

## Nearness to the high (PTH)
For each stock and session `t`, using only data up to `t`, on split/bonus-adjusted
prices:
- **PTH = close(t) / highest high over the last 252 sessions including t**, at least 200
  of those sessions traded. PTH is in (0, 1]; 1 = closing at the 52-week high.
- **High rank:** PTH's percentile (1 = nearest the high) among that day's universe.
  NaN outside the universe or where an input is missing.

## Rules, fixed now
- **Tier:** invest (long-term section), as `momentum-v1`: at most 15 positions, book
  half at +3R, trail 4 x ATR(14), exit if not +1R within 250 sessions. Sizing, heat,
  drawdown brake, costs and fills are the engine's (`engine-v3`), unchanged.
- **Rebalance day:** the first session of each calendar month.
- **Entry** at the close of a rebalance day when the high rank is at least 0.9 (the
  paper's top 30% sort, narrowed to a tenth so a 15-position book picks from leaders
  only, as `momentum-v1` does) **and** the 12-1 return is above 0 (a stock near a high
  that it reached by falling less than others is not the effect).
- **Exit** at the next open after a rebalance day on which the high rank is below 0.7
  (out of the paper's top 30%). An unknown rank is not an exit. The tier's other exits
  also apply.
- **Busy days:** the engine's existing order (highest tech-v1 score first).

Grid: one point, `stop_atr` 4.0. The cut-offs are fixed here, not tuned.

## How it is judged
- Spec section 6, all seven checks, on the walk-forward folds and holdout used by every
  other strategy; out-of-sample and after-cost numbers only.
- Beside the gates: `momentum-v1` and `fip-momentum-v1` on the same data, the
  correlation of daily returns with both, and the deflated Sharpe against its own grid
  and against every variant tried so far (68 with this one).
- The holdout year is read once, after the run.
- If it passes: paper trading with alerts in the long-term section, then the paper gate
  (3 months, 30 trades) and a moderate or strong evidence rating before real money
  (decision 0018). If it fails, it is research only, and the report says so plainly.
- Run once. No rule above changes after seeing a result; a change is `high52-v2` with
  its own plan.

## Building it
- `market.py`: `high52_ranks(close, high, universe)` beside `momentum_ranks`, stored as
  `Market.high52_rank`.
- `strategies.py`: `HIGH52`, registered 2026-11-06.
- Tests: PTH range and no future data, entries only on rebalance days among the leaders
  with a positive 12-1 return, the exit, the walk-forward runs; `strategy-guide.ts`
  gets the entry.
