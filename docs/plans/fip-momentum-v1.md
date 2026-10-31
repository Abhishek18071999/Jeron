# FIP momentum v1: momentum that came smoothly (invest tier)

Status: pre-registered on 2026-10-31, before any code or run on data. Asked for by
Abhishek ("make your own new most profitable strategy, best suitable for the future").
Run it once with `python -m app.cli backtest --strategy fip-momentum`.

Nobody can promise "the most profitable strategy ever", and the way to give a new
strategy its best chance of working after the backtest is this project's own rule
(post-review-v2, P): start from a documented effect, fix the rules before the data, run
once. This plan does that.

## Why this idea
Da, Gurun and Warachka, "Frog in the Pan: Continuous Information and Momentum"
(Review of Financial Studies, 2014): momentum built from many small moves in the same
direction ("continuous information") persists, and keeps paying for months; momentum
built from a few large jumps does not. Investors react to a big headline at once but
under-react to a slow trickle of small good news, like the frog that doesn't notice the
water warming. In their US data, the momentum profits came almost all from the
continuous third; the discrete third earned little. The effect has been reported in
other markets since; the evidence for India is thinner, which is what this test is for.

It is chosen because:
- it is a documented anomaly with a reason behind it, not a parameter search;
- it is a filter on `momentum-v1`, so the test asks one clean question: does keeping
  only the smooth risers improve the momentum leaders? Everything else is identical;
- it trades monthly (low costs, mostly long-term tax) and needs only prices.

It is not a new kind of edge compared with `momentum-v1` and `rs-pullback-v1` (all lean
on relative strength); the report gives the correlation of daily returns with both.

## Information discreteness (ID)
For each stock and session `t`, using only data up to `t`, over the daily returns inside
`momentum-v1`'s 12-1 window (the returns from session `t - 251` to `t - 21`, 231 of
them, at least 180 defined):
- `pos` = share of those returns above 0, `neg` = share below 0;
- **ID = sign(12-1 return) x (neg - pos)**. Low (negative) ID = many small moves in the
  direction of the trend (continuous); high ID = the trend came from a few jumps.
- **FIP rank:** ID's percentile (0 = most continuous) among that day's universe stocks
  whose momentum rank is at least 0.8 (`momentum-v1`'s top fifth). NaN for every other
  stock.

## Rules, fixed now
- **Tier:** invest (long-term section), as `momentum-v1`: at most 15 positions, book
  half at +3R, trail 4 x ATR(14), exit if not +1R within 250 sessions. Sizing, heat,
  drawdown brake, costs and fills are the engine's (`engine-v3`), unchanged.
- **Rebalance day:** the first session of each calendar month.
- **Entry** at the close of a rebalance day when the momentum rank is at least 0.8 and
  the FIP rank is at most 1/3 (the most continuous third of the top fifth).
- **Exit** as `momentum-v1`: at the next open after a rebalance day on which the
  momentum rank is below 0.75. An unknown rank is not an exit. The tier's other exits
  also apply.
- **Busy days:** the engine's existing order (highest tech-v1 score first).

Grid: one point, `stop_atr` 4.0 (`momentum-v1`'s default). The 0.8 and 1/3 cut-offs are
the paper's quintile and tercile sorts, not tuned; the windows are `momentum-v1`'s.

## How it is judged
- Spec section 6, all seven checks, on the walk-forward folds and holdout used by every
  other strategy; out-of-sample and after-cost numbers only.
- Beside the gates: the same numbers for `momentum-v1` run on the same data (the idea
  predicts higher expectancy and a smaller drawdown than plain momentum), the correlation
  of daily returns with `momentum-v1` and `rs-pullback-v1`, and the deflated Sharpe
  against its own grid and against every variant tried so far.
- The holdout year has not been seen for this strategy; it is read once, after the run.
- If it passes, it is live-eligible: paper trading with alerts in the long-term section,
  then the paper gate (3 months, 30 trades) and a moderate or strong evidence rating
  before any real money (decision 0018). If it fails, it is research only, and the
  report says so plainly.
- Run once. No rule above changes after seeing a result; a change is `fip-momentum-v2`
  with its own plan.

## Building it
- `market.py`: `fip_ranks(close, universe, mom_rank)` beside `momentum_ranks`, stored
  as `Market.fip_rank`; included in the run's data fingerprint.
- `strategies.py`: `FIP_MOMENTUM`, registered 2026-10-31, the exit shared with
  `momentum-v1`.
- Tests: the ID sign and range, no future data, entries only on rebalance days among the
  top fifth's smooth third, the walk-forward runs; `strategy-guide.ts` gets the entry.
