# Every strategy version, compared: NSE data, 2026-11-06

Date: 2026-11-06. This completes the backtest of every strategy version on NSE data. The
autopilot ran `high52-v1` (run 11). The seven versions it had marked as tried but never
stored (`score-swing-v1`, `breakout-52w-v1`, `pullback-trend-v1`, their `-events`
versions and `trend-breakout-v1`) were run by hand as runs 12 to 18, with the same
command as `runs-2026-11-01/scripts/bt.sh`. Runs 1 to 10 are the stored runs of
2026-11-01 (see `fip-momentum-v1-report.md`) and `low-vol-v1` of 2026-11-03.

Data: NSE bhavcopy 2016-01-01 to 2026-11-06 (2,688 sessions, 2,938 stocks, delisted
included), index closes, security lists, board meetings, 25,128 quarterly results
(newest quarter 2024-12-31), news labels for 2026 only (gemini-3.8-flash). Engine
`engine-v3`, idle cash at 6.5% a year, after costs, out of sample. Same folds as every
report: walk-forward test from late 2019, then an untouched 12-month holdout. Code hash
`02afdc73ea42155b` for runs 11 to 18. Data fingerprint `fa63d60ee8d9ae38` (run 11) and
`69af92389673a74f` (runs 12 to 18): the same sessions to 2026-11-06. The fingerprint also
hashes the optional inputs a batch builds (high52's rank in one batch, the results
blackout and news score in the other), so the two differ. No strategy rule or parameter
was changed. Every new version was run once.

**Verdict: `fip-momentum-v1` is still the best strategy.** Of 18 versions, it is the only
one that passes all seven section 6 checks *and* has a *strong* evidence rating (decision
0018), with a clearly positive holdout (+0.39R over 42 trades, +8.5% while Nifty 500 fell
8.2%). Three others pass all seven checks with *moderate* evidence: `momentum-v1`,
`rs-pullback-v1` and `combined-book-v1`. Of the eight versions tested today, none passes all seven.
`trend-breakout-v1` comes closest (6 of 7, only bull-market regimes positive).
`high52-v1` fails, as it did on Yahoo data.

## Every strategy (walk-forward test, after costs)

Sorted by checks passed, then evidence. **New** marks the eight versions first run today.

| Strategy | Trades | Expectancy | PF | Max DD | CAGR | Sharpe | Positive regimes | Holdout expectancy (trades) | Holdout return | Section 6 | Evidence | Deflated Sharpe, own grid |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **fip-momentum-v1** | 212 | **0.493R** | **1.85** | 14.1% | 15.2% | **0.85** | bull, bear | **+0.392R** (42) | +8.5% | **7 of 7** | **strong** | **0.97** |
| momentum-v1 | 206 | **0.667R** | 1.79 | 15.3% | 12.6% | 0.61 | all three | **+0.531R** (35) | **+20.9%** | **7 of 7** | moderate | 0.87 |
| rs-pullback-v1 | 280 | 0.323R | 1.59 | 13.5% | **15.6%** | **0.85** | bull, sideways | +0.003R (46) | +2.3% | **7 of 7** | moderate | 0.95 |
| combined-book-v1 | 292 | 0.237R | 1.54 | 13.3% | 13.6% | 0.70 | all three | +0.038R (54) | +4.1% | **7 of 7** | moderate | 0.85 |
| trend-breakout-v1 (new) | 302 | 0.309R | 1.40 | 11.5% | 14.5% | 0.70 | bull only | +0.172R (31) | +6.5% | 6 (regimes) | moderate | 0.82 |
| sector-rotation-v1 | 263 | 0.278R | 1.50 | 17.0% | 12.0% | 0.57 | bull, sideways | +0.226R (38) | +11.0% | 6 (benchmark) | moderate | 0.81 |
| quality-trend-v1 | 201 | 0.637R | 1.91 | 16.0% | 14.2% | 0.76 | all three | 0 trades | (cash only) | 6 (holdout untestable) | weak | 0.93 |
| results-drift-v1 | 209 | 0.341R | 1.49 | 12.0% | 12.4% | 0.69 | all three | -0.159R (41) | -2.6% | 6 (holdout) | weak | 0.87 |
| low-vol-v1 | 167 | 0.485R | 1.66 | 14.8% | 9.1% | 0.34 | bull, bear | +0.137R (36) | -0.4% | 6 (benchmark) | weak | 0.79 |
| score-swing-events-v1 (new) | 391 | 0.147R | 1.31 | **10.0%** | 10.6% | 0.46 | bull, bear | +0.033R (69) | +5.9% | 5 (expectancy, benchmark) | moderate | 0.61 |
| high52-v1 (new) | 230 | 0.193R | 1.17 | 12.8% | 7.4% | 0.15 | all three | +0.085R (55) | -3.0% | 5 (PF, benchmark) | weak | 0.64 |
| score-swing-v1 (new) | 449 | 0.046R | 1.02 | 15.1% | 5.2% | -0.11 | bull, bear | +0.061R (72) | +8.3% | 4 | weak | 0.13 |
| pullback-trend-v1 (new) | 362 | 0.003R | 0.91 | 15.9% | 3.1% | -0.40 | bull, sideways | +0.096R (59) | +4.1% | 4 | weak | 0.03 |
| breakout-52w-events-v1 (new) | 500 | 0.129R | 1.20 | 21.4% | 11.0% | 0.44 | bull, bear | +0.183R (98) | +9.0% | 3 | weak | 0.79 |
| breakout-52w-v1 (new) | 501 | 0.090R | 1.15 | 22.2% | 10.1% | 0.36 | bull, bear | +0.233R (96) | +10.4% | 3 | weak | 0.76 |
| reversal-v1 | 1,202 | 0.039R | 1.15 | 11.1% | 9.3% | 0.38 | bull, bear | -0.012R (209) | 0.0% | 3 | weak | 0.82 |
| top-score-v1 | 441 | 0.015R | 0.96 | 14.0% | 3.4% | -0.30 | bear, sideways | -0.223R (86) | -2.3% | 3 | weak | 0.23 |
| pullback-trend-events-v1 (new) | 396 | -0.005R | 0.89 | 18.0% | 2.5% | -0.51 | bull, bear | -0.040R (65) | +6.0% | 3 | weak | 0.03 |
| *Spec bar* | >= 100 | > 0.15R | >= 1.3 | <= 20% | | > Nifty 500 | >= 2 of 3 | > 0 | | 7 of 7 | | 0.95 |

Nifty 500 over the test period: Sharpe above 6.5% of 0.59 (runs 1 to 9) and 0.57 (runs 11
to 18), CAGR 16.0 to 16.4%, max drawdown 38.3%. Win rates are in `runs-2026-11-06/runs.json`
and the 2026-11-01 report. Holdout returns include interest on idle cash, so a strategy
can lose on its trades and still show a small positive return (pullback-trend-events-v1).

**The holdout windows are not the same.** Runs 1 to 9: 2025-10-31 to 2026-10-30 (Nifty 500
-8.2%). Run 10 (low-vol): 2025-11-04 to 2026-11-03 (Nifty 500 -5.4%). Runs 11 to 18:
2025-11-07 to 2026-11-06 (Nifty 500 -0.2%). They overlap by about 51 weeks, so a
strategy's holdout from an earlier run is not directly comparable with today's.

## Failed section 6 checks, by strategy

| Strategy | Expectancy | PF | Drawdown | Trades | Regimes | Benchmark | Holdout |
|---|---|---|---|---|---|---|---|
| fip-momentum, momentum, rs-pullback, combined-book | pass | pass | pass | pass | pass | pass | pass |
| trend-breakout-v1 | pass | pass | pass | pass | **fail** (bull only) | pass (0.70 vs 0.57) | pass |
| sector-rotation-v1 | pass | pass | pass | pass | pass | **fail** (0.57 vs 0.59) | pass |
| quality-trend-v1 | pass | pass | pass | pass | pass | pass | **fail** (0 trades, no results after 2024) |
| results-drift-v1 | pass | pass | pass | pass | pass | pass | **fail** |
| low-vol-v1 | pass | pass | pass | pass | pass | **fail** (0.34) | pass |
| score-swing-events-v1 | **fail** (0.147R) | pass | pass | pass | pass | **fail** (0.46) | pass |
| high52-v1 | pass | **fail** (1.17) | pass | pass | pass | **fail** (0.15) | pass |
| score-swing-v1, pullback-trend-v1 | **fail** | **fail** | pass | pass | pass | **fail** | pass |
| breakout-52w-v1, breakout-52w-events-v1 | **fail** | **fail** | **fail** (22.2%, 21.4%) | pass | pass | **fail** | pass |
| reversal-v1, top-score-v1, pullback-trend-events-v1 | **fail** | **fail** | pass | pass | pass | **fail** | **fail** |

## The eight versions tested today

- **trend-breakout-v1** is the best of today's eight. It has +0.31R over 302 trades,
  profit factor 1.40, a smaller drawdown (11.5%) than any of the four that pass all seven, and
  Sharpe 0.70 against 0.57. Its holdout was positive (+0.17R over 31 trades). It fails one
  check: every trade fell in a bull regime, so "positive in 2 of 3 regimes" can't be
  shown. It buys breakouts by relative-strength leaders, so the regime filter keeps it
  out of bear and sideways markets. It is not shown to lose there, but nothing shows it
  works there either. The evidence rating is moderate: every robustness check passes
  except the deflated Sharpe (0.82). Research only, as section 6 requires.
- **high52-v1** fails (pre-registered in `docs/plans/high52-v1.md`, run once on NSE
  data). Its test years are positive (+0.19R) but thin (profit factor 1.17, Sharpe 0.15),
  and its holdout is barely positive (+0.09R, profit factor 0.61). Two sources, same
  answer: it failed on Yahoo data too. Per its plan, it is not tuned.
- **The M3 originals and their `-events` versions all fail.** score-swing,
  breakout-52w and pullback-trend sit near zero expectancy. The results blackout and news
  filter help score-swing (+0.05R to +0.15R, drawdown 15.1% to 10.0%, rating weak to
  moderate) and breakout-52w a little (+0.09R to +0.13R). pullback-trend gets nothing
  from them. Even the best of these, score-swing-events-v1, misses the 0.15R bar by
  0.003R and loses to Nifty 500's Sharpe. The news filter had labels only for 2026, so
  these runs effectively tested the results blackout, not the news brain.

## Why fip-momentum-v1 is still the best

- It is the only *strong* rating among 18 versions. Its bootstrap intervals are clear of
  zero (+0.25R to +0.75R, profit factor 1.23 to 2.68). It stays positive with slippage
  x2 (+0.48R), charges x1.5 (+0.50R), entries one session late (+0.56R), without its
  five best trades (+0.31R) and without its best year (+0.37R). It is the only strategy
  whose own-grid deflated Sharpe clears 0.95 (0.97, one grid point).
- `momentum-v1` has the higher expectancy (0.67R) and the better holdout (+0.53R,
  +20.9%), and it is positive in all three regimes. On risk-adjusted terms it is weaker
  (Sharpe 0.61, only 0.02 above Nifty 500) and its evidence is moderate. It was also the
  only strategy to pass all seven checks on Yahoo data
  (`docs/backtests/yahoo-2026-11-06/`), where fip-momentum lost its holdout. Momentum
  is the most robust *family*. Within it, fip-momentum-v1 has the steadier curve on NSE
  data and momentum-v1 travels better across sources.
- `rs-pullback-v1` matches fip's Sharpe (0.85) but its holdout was flat (+0.003R).
  `combined-book-v1` adds nothing over its members.

## What this report doesn't claim

- **Not proof of an edge.** fip-momentum-v1's deflated Sharpe against all 67 variants
  tried by 2026-11-01 was 0.37. Today's eight versions add more trials on the same ten
  years, which can only lower that number. It was not recomputed here.
- **The holdout read differs by version.** fip, momentum, rs-pullback, results-drift and
  sector-rotation had their holdouts read on 2026-11-01 (some earlier). Today's eight
  versions read theirs for the first time, on a window a week later and in a flatter
  market (-0.2% against -8.2%).
- **quality-trend-v1 is untested, not failed.** Its test years are among the best
  (+0.64R, profit factor 1.91), but Jeron has no quarterly results after December 2024,
  so it can't trade in the holdout.
- **The news filter is barely tested.** News labels exist only for 2026 (40 so far), so
  the `-events` versions' gains come from the results blackout.

## Next

1. Keep `fip-momentum-v1` paper-trading with alerts, as the 2026-11-01 report set out.
   Paper gate: 3 months and 30 trades, expectancy above 0 and inside the backtest's
   range, before any real money.
2. `momentum-v1`, `rs-pullback-v1` and `combined-book-v1` keep paper-trading. Every other
   version is research only.
3. `trend-breakout-v1` is the one near miss worth watching. Its failure is about missing
   evidence, not losses. Paper trading will show its bear-market behaviour only when a
   bear market comes. No v2 on the same data.
4. Load 2025-26 quarterly results (Financial Results CSVs with XBRL from nseindia.com)
   and run `quality-trend-v1` again: same version, new data.

## Reproduce

`docs/backtests/runs-2026-11-06/`: `runs.json` (runs 11 to 18: metadata and full
summaries) and `scripts/extract.py` (prints every stored run's gates, holdout and
evidence checks). The commands, run inside the `scheduler` container:

```
python -m app.cli backtest --strategy high52        # run 11, by the autopilot
python -m app.cli backtest --strategy score-swing --strategy breakout-52w \
  --strategy pullback-trend --strategy score-swing-events \
  --strategy breakout-52w-events --strategy pullback-trend-events \
  --strategy trend-breakout                          # runs 12 to 18, by hand
```

Runs 1 to 9 are in `runs-2026-11-01/runs.json`. Run 10 (`low-vol-v1`, 2026-11-03) is in
the database but was made by code on branch `ccr-a8d19389-i000c5`, which is not merged
into this branch.
