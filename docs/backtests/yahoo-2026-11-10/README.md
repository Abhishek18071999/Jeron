# residual-momentum-v1 on real prices (Yahoo second source), 2026-11-10

Why: `residual-momentum-v1` was pre-registered on 2026-11-07
(`docs/plans/residual-momentum-v1.md`) and built, but never run: NSE's archive can't be
reached from the session that built it, and still can't. So it was run once on Yahoo
daily bars, the way every other version was on 2026-11-06 (`../yahoo-2026-11-06/`), with
`momentum-v1`, `fip-momentum-v1` and `rs-pullback-v1` re-run on the same market for the
comparisons its plan asks for. No rule or parameter was changed, before or after.

**Research only. The run that decides is the one on NSE data**, which the plan says to
run once: `python -m app.cli backtest --strategy residual-momentum` (the autopilot does
it on its own for an untested version). 346 hand-listed large and mid caps that still
trade today: no delisted stocks, so every number here is biased upward; no security list
(bands, GSM/ASM). Engine `engine-v3`, after costs, out of sample: walk-forward test
2019-10 to 2025-10, holdout 2025-10-28 to 2026-10-27. The three re-run strategies give
exactly the 2026-11-06 numbers, so the data matches that report's.

| Strategy | Trades | Expectancy | PF | CAGR | Max DD | Sharpe | Holdout | Section 6 | Evidence | Deflated Sharpe, all 70 variants |
|---|---|---|---|---|---|---|---|---|---|---|
| **residual-momentum-v1** | 188 | +0.816R | **2.30** | **21.4%** | 14.9% | **1.27** | +0.10R (37), PF 0.80, -1.9% | **7 of 7** | weak | **0.77** |
| momentum-v1 | 226 | +0.833R | 1.78 | 16.5% | 16.4% | 0.88 | +0.18R (36), PF 1.26, +3.8% | **7 of 7** | **strong** | 0.44 |
| fip-momentum-v1 | 220 | +0.569R | 2.03 | 17.5% | 15.5% | 0.96 | -0.29R (37), -1.9% | 6 (holdout) | weak | 0.52 |
| rs-pullback-v1 | 251 | +0.443R | 1.93 | 18.7% | **11.8%** | 1.13 | -0.10R (53), -1.8% | 6 (holdout) | weak | 0.67 |

Nifty 500 over the test: Sharpe 0.60, CAGR 16.7%, max drawdown 38.3%; over the holdout
-8.8%.

## Reading

- **In the test years it is the best version Jeron has run on this data.** The Sharpe
  ratio (1.27) is the highest of all 18 versions here (next: rs-pullback 1.13,
  combined-book 1.05), with the highest return and profit factor. It is positive in all
  three regimes (bear +1.15R over 55 trades, bull +0.75R over 115, sideways +0.20R over
  18) and in six of seven years (2024: -0.05R). Bootstrap intervals: expectancy +0.51R
  to +1.13R, profit factor 1.52 to 3.41. It stays positive with slippage x2 (+0.84R),
  charges x1.5 (+0.83R), entries one session late (+0.57R), without its five best trades
  (+0.60R) and without its best year (+0.64R).
- **The plan's prediction, checked.** Against `momentum-v1` it predicted a higher Sharpe
  (yes: 1.27 against 0.88), a similar expectancy (yes: 0.82R against 0.83R), a smaller
  drawdown (barely: 14.9% against 16.4%) and a daily-return correlation "well below 1"
  (**no: 0.85**, and 0.79 with fip). It wins more often (48% against 38%) and its losing
  years are milder (2022: +0.1% against -9.6%), but it is the same bet as momentum, not
  a second one. Holding both would diversify very little.
- **The holdout year is the weak point, and it sets the rating.** Expectancy was just
  positive (+0.10R over 37 trades) so the section 6 check passes, but the profit factor
  was 0.80: the account lost ₹55,000 on its trades and 1.9% overall while Nifty 500 lost
  8.8%. The evidence rating is "weak" for that one failed check (decision 0018).
  `momentum-v1` is the only one of the four with a profitable holdout and a "strong"
  rating. One year, 37 trades: a warning, not a verdict.
- **Luck is still not ruled out.** Its deflated Sharpe against all 70 variants that can
  run on this market is 0.77, the highest of the four and well above the 0.38 that led
  on NSE data, but below 0.95. Against its own single grid point it is 1.00.

## What follows

Nothing changes in what is traded. On NSE data it has no result yet, and the Yahoo
universe flatters every strategy. If the NSE run also passes, the plan already says what
happens: paper trading with alerts in the long-term section, then the paper gate (3
months, 30 trades) and a moderate or strong evidence rating before any real money. If the
NSE run fails, it is research only, whatever this page says.

Files: `results.json` (each run's full summary, the deflated Sharpe), `equity.json` (daily
equity curves), `scripts/residual.py` (how it was run).
