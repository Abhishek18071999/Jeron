# Low volatility v1: defensive as predicted, but not enough return for its risk

Date: 2 November 2026. Run 10, `python -m app.cli backtest --strategy low-vol`, run once
as pre-registered in `docs/plans/low-vol-v1.md` (commit c09ea92, before any code). Engine
`engine-v3`, the same data, folds and holdout as runs 1 to 9
(`docs/backtests/fip-momentum-v1-report.md`), idle cash at 6.5% a year.

**Verdict: research only.** It passes six of the seven section 6 checks and fails the
benchmark: a Sharpe ratio of 0.30 against buy-and-hold Nifty 500's 0.59. Its evidence
rating is weak. It paper-trades as research (no alerts). Per the plan, nothing is changed
after the result; a change would be `low-vol-v2` with its own plan.

## Results (walk-forward test 2019-10 to 2025-10, after costs)

| | Low volatility | FIP momentum (for comparison) | Spec bar |
|---|---|---|---|
| Trades | 168 | 212 | >= 100 |
| Expectancy | 0.453R | 0.493R | > 0.15R |
| Profit factor | 1.81 | 1.85 | >= 1.3 |
| Max drawdown | 13.0% | 14.1% | <= 20% |
| CAGR (with interest) | 8.7% | 15.2% | |
| Sharpe above 6.5% | **0.30** | 0.85 | > Nifty 500's 0.59 |
| Positive regimes | bear, bull | bull, bear | >= 2 of 3 |
| Holdout | +0.010R over 32 trades, +1.1% | +0.392R over 42, +8.5% | > 0 |
| Evidence rating | weak | strong | |
| Deflated Sharpe, own grid (1 point) | 0.76 | 0.97 | 0.95 |

## What the idea predicted, and what happened

- **Defensive: yes.** By regime: bear markets +1.36R a trade (41 trades), bull +0.25R
  (108), sideways -0.37R (19). It did best exactly when momentum struggles, as the
  literature says.
- **Different from momentum: only partly.** Daily returns correlate 0.58 with
  fip-momentum-v1, 0.56 with momentum-v1 and 0.51 with rs-pullback-v1. Lower than the
  momentum strategies with each other (up to 0.70), but not the independent edge hoped
  for: all of them trade the same liquid universe through the same engine and exits.
- **Return for the risk: no.** Per trade it is nearly as good as fip-momentum, but its
  account grew 8.7% a year: it was invested 64% of the time and the calmest stocks move
  little, so trades of +0.45R add up slowly, and the 4 x ATR stops on calm stocks are
  tight in rupees. Above the 6.5% cash rate that leaves a Sharpe of 0.30.
- By year: 2019 -0.46R (9 trades), 2020 +0.43R, 2021 +0.46R, 2022 +0.89R, 2023 +1.82R,
  2024 -0.14R, 2025 +0.12R.

The deflated Sharpe against all variants tried was not computed: the strategy already
fails a gate, so the extra hour of computing can't change the verdict.

## What it doesn't claim

The low-volatility effect is about long holding periods with few trades and no stops;
this test runs it through Jeron's R-based engine with stops, targets and a trail. That is
the right test for Jeron (it is how Jeron would trade it), not a test of the academic
effect itself.
