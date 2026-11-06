# Low volatility v1: the calmest stocks, monthly (invest tier)

Status: pre-registered on 2026-11-01, before any code or run on data. Abhishek gave a
free hand ("add the features or strategies you want"); the idea-first rule
(post-review-v2, P) still applies. Run it once with
`python -m app.cli backtest --strategy low-vol`.

## Why this idea
Every strategy that has passed so far (rs-pullback-v1, momentum-v1, fip-momentum-v1)
leans on relative strength, and their daily returns correlate 0.58 to 0.70: one bad
year for momentum hits all of them. The low-volatility anomaly is a different edge with
a long record: stocks with the least volatile prices have earned about as much as the
most volatile, or more, with much less risk (Ang, Hodrick, Xing and Zhang, 2006; Blitz
and van Vliet, 2007; Frazzini and Pedersen's "betting against beta", 2014). The usual
explanation is that many investors can't or won't use leverage and so overpay for
exciting, volatile stocks. In India NSE publishes the Nifty Low Volatility 30 index on
this idea. It is defensive: it should hold up in falls and lag in sharp rallies, the
opposite of momentum.

## The volatility rank
For each stock and session `t`, using only data up to `t`: the standard deviation of
daily returns over the last 252 sessions (at least 200 defined), the same measure
`momentum-v1` divides by. **Volatility rank:** its percentile among that day's universe,
0 = calmest. NaN outside the universe or with too little history.

## Rules, fixed now
- **Tier:** invest (long-term section): at most 15 positions, book half at +3R, trail
  4 x ATR(14), exit if not +1R within 250 sessions. Sizing, heat, drawdown brake, costs
  and fills are the engine's (`engine-v3`), unchanged.
- **Rebalance day:** the first session of each calendar month.
- **Entry** at the close of a rebalance day when the volatility rank is at most 0.10
  (the calmest tenth of the universe). No trend or regime filter: the idea is the low
  volatility itself, and the engine already halves risk when the market is risk-off.
- **Exit** at the next open after a rebalance day on which the volatility rank is above
  0.30 (no longer among the calmest three tenths). An unknown rank is not an exit. The
  tier's other exits also apply.
- **Busy days:** the engine's existing order (highest tech-v1 score first).

Grid: one point, `stop_atr` 4.0. The 0.10 and 0.30 cut-offs and the 252-session window
are fixed, not tuned.

## How it is judged
- Spec section 6, all seven checks, on the same walk-forward folds and holdout as every
  other strategy; out-of-sample and after-cost numbers only.
- Beside the gates: the correlation of its daily returns with `fip-momentum-v1`,
  `momentum-v1` and `rs-pullback-v1` (the reason it exists is to be different), its
  results by regime (the idea predicts bear markets best), the evidence rating, and the
  deflated Sharpe against all variants tried so far.
- The holdout year has not been seen for this strategy; it is read once.
- If it passes, it paper-trades with alerts in the long-term section; real money only
  after the paper gate. If it fails, research only, said plainly.
- Run once. No rule above changes after a result; a change is `low-vol-v2`.

## Building it
- `market.py`: `volatility_ranks(close, universe)`, stored as `Market.vol_rank`, in the
  run's data fingerprint.
- `strategies.py`: `LOW_VOL`, registered 2026-11-01.
- Tests: the rank uses no future data and puts the calmest stock first, entries only on
  rebalance days in the calmest tenth, the exit, the walk-forward; the strategy guide
  and a Learn lesson.
