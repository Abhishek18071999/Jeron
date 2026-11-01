# FIP momentum v1, and every untested strategy: one run on the same data

Date: 2026-11-01. Runs 1 to 8 on a fresh install: NSE bhavcopy 2016-01-01 to
2026-10-30 (2,683 sessions, 2,930 stocks, delisted included), index closes, security
lists, 97,759 board meetings. Engine `engine-v3`, idle cash at 6.5% a year, the same
folds as every report: walk-forward test 2019-10 to 2025-10, untouched holdout
2025-10-31 to 2026-10-30. Data fingerprint `5f61059ef5e24625` (runs 1 to 7). 2,683
quality reports: all WARN (no second-source cross-check), none FAIL.

`fip-momentum-v1` was pre-registered in `docs/plans/fip-momentum-v1.md` (commit
e36c283) before its code was written or any data was loaded, and run once. The other
untested versions (`momentum-v1`, `reversal-v1`, `top-score-v1`, `combined-book-v1`)
were run once as their own plans say. `quality-trend-v1` was not run: the quarterly
results import was still going.

**Verdict: `fip-momentum-v1` is the strongest strategy Jeron has tested.** It passes all
seven section 6 checks, it is the only strategy whose evidence rating is *strong*
(decision 0018), its holdout year was clearly positive (+0.39R over 42 trades, +8.5%
while Nifty 500 fell 8.2%), and against all 67 variants tried it has the highest
deflated Sharpe of any strategy (0.37). That last number is also the honest limit: 0.37
is far from 0.95, so luck across ten years of trying is not ruled out. It moves to paper
trading with alerts; real money only after the paper gate.

## Results (walk-forward test, after costs)

| | FIP momentum | Momentum | RS pullback | Combined book | Results drift | Sector rotation | Reversal | Top score | Spec bar |
|---|---|---|---|---|---|---|---|---|---|
| Trades | 212 | 206 | 280 | 292 | 209 | 263 | 1,202 | 441 | >= 100 |
| Win rate | 41% | 38% | 41% | 41% | 45% | 41% | 60% | 36% | reported |
| Expectancy | **0.493R** | **0.667R** | 0.323R | 0.237R | 0.341R | 0.278R | 0.039R | 0.015R | > 0.15R |
| Profit factor | **1.85** | 1.79 | 1.59 | 1.54 | 1.49 | 1.50 | 1.15 | 0.96 | >= 1.3 |
| Max drawdown | 14.1% | 15.3% | 13.5% | 13.3% | 12.0% | 17.0% | 11.1% | 14.0% | <= 20% |
| CAGR (with interest) | 15.2% | 12.6% | 15.6% | 13.6% | 12.4% | 12.0% | 9.3% | 3.4% | |
| Sharpe above 6.5% | **0.85** | 0.61 | **0.85** | 0.70 | 0.69 | 0.57 | 0.38 | -0.30 | > Nifty 500's 0.59 |
| Positive regimes | bull, bear | all three | bull, sideways | all three | all three | bull, sideways | bull, bear | bear, sideways | >= 2 of 3 |
| Holdout expectancy | **+0.392R** (42) | **+0.531R** (35) | +0.003R (46) | +0.038R (54) | -0.159R (41) | +0.226R (38) | -0.012R (209) | -0.223R (86) | > 0 |
| Holdout return | +8.5% | **+20.9%** | +2.3% | +4.1% | -2.6% | +11.0% | 0.0% | -2.3% | Nifty 500: -8.2% |
| Section 6 | **7 of 7** | **7 of 7** | **7 of 7** | **7 of 7** | 6 (holdout) | 6 (benchmark) | 3 | 3 | 7 of 7 |
| Evidence rating | **strong** | moderate | moderate | not rated | weak | moderate | weak | weak | |
| Deflated Sharpe, own grid | **0.97** (1) | 0.87 (4) | 0.95 (4) | | 0.87 | 0.81 | 0.82 | 0.23 | 0.95 |
| Deflated Sharpe, all 67 variants | **0.37** | 0.19 | 0.37 | 0.25 (61) | 0.24 | 0.16 | | | 0.95 |

Nifty 500 over the test period: CAGR 16.4%, Sharpe above 6.5% of 0.59, max drawdown
38.3%. No strategy beats its raw CAGR; the eligible ones do it with about a third of the
drawdown, which is what the Sharpe check measures.

## FIP momentum against plain momentum (the question the plan asked)

The idea predicted that keeping only the smooth risers would give higher expectancy and a
smaller drawdown than plain momentum. Half of that held:

- **Better:** Sharpe 0.85 against 0.61, drawdown 14.1% against 15.3%, profit factor 1.85
  against 1.79, CAGR 15.2% against 12.6%, deflated Sharpe against all trials 0.37
  against 0.19, and an evidence rating of strong against moderate.
- **Worse:** expectancy per trade 0.49R against 0.67R, and the holdout return, +8.5%
  against +20.9%. Plain momentum's trades are larger winners on average but its equity
  is bumpier; FIP gives up some of the big winners for a steadier curve.

Daily returns correlate 0.70 with momentum-v1, 0.58 with rs-pullback-v1 and 0.57 with
results-drift-v1: the same family of edge (relative strength), not a new one.

## Robustness of FIP momentum (confidence engine)

| Check | Value | |
|---|---|---|
| 95% interval of expectancy | +0.25R to +0.75R | pass |
| 95% interval of profit factor | 1.23 to 2.68 | pass |
| Slippage x2 | +0.484R over 202 trades | pass |
| Charges x1.5 | +0.500R | pass |
| Entries one session late | +0.564R | pass |
| Without its 5 best trades | +0.314R | pass |
| Without its best year (2020) | +0.370R | pass |
| Largest sector share of gains | Information Technology, 24% | pass |

By year (expectancy, trades): 2019 -0.54R (7), 2020 +1.14R (34), 2021 +0.81R (32), 2022
+0.25R (43), 2023 +1.15R (31), 2024 -0.23R (32), 2025 +0.14R (33). Two losing years out
of seven, and 2024's loss came in a year Nifty 500 rose 15%: momentum lags in sharp
rotations.

## What this report doesn't claim

- **Not proof of an edge.** The deflated Sharpe against all 67 variants is 0.37. Jeron
  has now tried many ideas on the same ten years; the best of them is expected to look
  good partly by luck. The paper gate is what decides.
- **Not the most profitable possible strategy.** It is the best of what was tested, with
  rules fixed before the data, which is the version most likely to keep working.
- **The future is not the backtest.** Momentum has well-documented crashes (sharp market
  reversals, when last year's losers lead); the test years include 2020 and 2022 but not
  every kind of crash.
- **The holdout was read once.** FIP's holdout year had not been seen before this run.
  Momentum-v1's had not either; rs-pullback's, results-drift's and sector-rotation's had.

## Next

1. Paper-trade `fip-momentum-v1` with alerts in the long-term section (the autopilot's
   `paper` step opens the account). Paper gate: 3 months and 30 trades, expectancy above
   0 and inside the backtest's range, before any real money; then 10 to 20% of intended
   capital for 3 months.
2. `momentum-v1` and `rs-pullback-v1` also paper-trade; the combined book passes too but
   adds nothing over its members.
3. `reversal-v1` and `top-score-v1` failed: research only. `quality-trend-v1` runs once
   the results import finishes.
4. No new variant of any of these is tried on the same data; a change is a v2 with its
   own plan.
