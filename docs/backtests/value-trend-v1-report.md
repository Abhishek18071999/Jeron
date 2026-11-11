# value-trend-v1: the cheapest rising stocks, 2026-11-11

Pre-registered in `docs/plans/value-trend-v1.md` (committed before any code), run once:
`python -m app.cli backtest --strategy value-trend`. No rule was changed after the run.

**Verdict: it passes all seven section 6 checks and all eleven evidence checks (rating:
strong), with a holdout year that made money. It is live-eligible for paper trading. It
is not proven: against all 75 variants tried its deflated Sharpe is 0.34, and its holdout
is a year already read for five other versions.** On this evidence it stands beside
`fip-momentum-v1` as one of the two best-supported versions, not above it.

## The numbers

Research database of `residual-momentum-v1-report.md` with the results loaded through
September 2026; walk-forward test years from late 2019, after costs, `engine-v3`; holdout
2025-11-10 to 2026-11-09.

| | Trades | Expectancy | Profit factor | CAGR | Max drawdown | Sharpe | Holdout | Holdout return | Checks | Evidence | Deflated Sharpe, own grid | against all 75 variants |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **value-trend-v1** | 166 | **0.834R** | **2.39** | 16.2% | **12.9%** | 0.84 | +0.229R (39), profit factor 1.61 | +12.0% | 7 of 7 | **strong** | 0.98 | 0.34 |
| fip-momentum-v1 | 202 | 0.416R | 1.79 | 13.9% | 13.5% | 0.71 | +0.549R (43), 2.48 | +11.5% | 7 of 7 | strong | 0.95 | 0.24 |
| momentum-v1 | 209 | 0.685R | 1.79 | 13.0% | 15.0% | 0.64 | +0.594R (40), 2.36 | +24.0% | 7 of 7 | moderate | 0.89 | 0.19 |
| quality-trend-v1 | 224 | 0.684R | 2.28 | 18.2% | 14.7% | 0.98 | -0.058R (67), 0.77 | -4.1% | 6 of 7 | weak | 0.97 | 0.47 |
| rs-pullback-v1 | 279 | 0.358R | 1.65 | 17.2% | 13.4% | 0.96 | -0.012R (54), 0.93 | +0.5% | 6 of 7 | weak | 0.97 | 0.45 |

Nifty 500: Sharpe 0.58 and a 38.3% drawdown in the test years, +0.2% in the holdout year.

By year: 2019 +0.18R (6 trades), 2020 +0.96R (27), 2021 +0.81R (23), 2022 +0.55R (37),
2023 +2.89R (18), 2024 -0.32R (25), 2025 +0.94R (30). By regime: bear +1.62R (46), bull
+0.64R (106), sideways -0.31R (14). Exits: 77 stops, 53 trailing stops, 51 breakeven
stops, 7 "no longer cheap", 1 time stop.

Evidence checks, all passed: 95% interval of expectancy +0.47R to +1.21R, of profit
factor 1.53 to 3.63; positive with slippage doubled (+0.77R), charges x1.5 (+0.82R) and
entries a session late (+0.71R); +0.57R without its five best trades and +0.58R without
its best year (2023); largest sector Financial Services, 39% of the gains.

## Reading it, for and against

For:
- It is the only version with a strong rating, a profitable holdout and the highest
  expectancy and profit factor at once, and it has the smallest drawdown of the five.
- It did what the idea predicted in one respect: it made money in 2025 and in the
  holdout, the stretch where `quality-trend-v1` and `rs-pullback-v1` did not.
- It survives every robustness re-run by a wide margin.

Against:
- **Selection.** This is the 75th variant on these ten years; counted against all of
  them its deflated Sharpe is 0.34. The 0.98 on its own grid only says its single grid
  point was not picked from many.
- **A used holdout.** The holdout year had been read for five versions before this plan
  was written. I chose the idea knowing which kinds of strategy had done badly in it
  (quality with a trend, pullbacks). The plan was fixed before the run, but the choice
  of family was not blind.
- **It is not far from momentum.** Daily returns correlate 0.63 to 0.65 with the
  momentum versions and 0.66 with `quality-trend-v1` (they correlate 0.72 with each
  other). Its bad year is the same one, 2024. Only 7 of 166 exits were "no longer
  cheap": the trend condition and the tier's stops do most of the work, and this run does
  not show how much of the result is the value sort. That would need a comparison run,
  which is another trial and is not done here.
- **Thin early data.** Filings before about 2019 have no XBRL, so a year of profit is
  first known in 2019-20: 151 of 319 universe stocks had an earnings yield in January
  2020, about two thirds from 2021, 774 of 963 today.
- **Naive earnings.** Trailing profit includes one-off gains; a few stocks show yields
  above 100%. They sit in the cheapest fifth by construction. Banks and lenders give 39%
  of the gains, the usual lean of an earnings-yield sort.
- **Sideways markets lost** (-0.31R over 14 trades), and 2024 lost.

## What follows

1. Live-eligible by the gates: a paper account with alerts in the long-term section,
   then the paper gate (3 months, 30 trades). Its status is the owner's to set; none was
   changed here.
2. It needs current results to trade at all: `python -m app.cli fundamentals-fetch
   --start 2025-03-31` on the install, then in each results season. Without it the
   earnings yields go stale 200 days after December 2024 and the account sits in cash.
3. Paper-trade it beside `fip-momentum-v1` and `momentum-v1`. Three accounts that share
   a bad year (2024) are not three independent bets; size any future real money as one
   family.
4. No `value-trend-v2`, no tuning of the 0.20 and 0.50 cut-offs, no cleaning of the
   earnings after the fact. Forward paper results are now the only evidence that can
   raise or lower this.

## Caveats

- Research database, not the install (three index closes missing, no cross-check, no ASM
  list, no news labels, 194 unreadable filings). The install's own run is the one of
  record and should be close.
- Idle cash earns the liquid-fund rate in all these numbers; positions are sized by the
  spec's 1% risk rule, so more than half the account is idle on average
  (`allocation-2026-11-10-report.md`).

Files: `nse-2026-11-11/` (`runs.json` run 7, `equity.json`, `gates.txt`,
`deflated-all.txt`).
