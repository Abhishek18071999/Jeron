# Every strategy on real prices (Yahoo second source), 2026-11-06

Why: NSE's archive could not be reached from the session, so every strategy was run on
real daily bars from Yahoo, Jeron's second source (`app/data/yahoo.py`), through the
unchanged `build_market` and `evaluate` (engine-v3, the usual folds: walk-forward test
2019-10 to 2025-10, holdout 2025-10-28 to 2026-10-27, after costs, out of sample).

**Research only, not a replacement for the NSE runs.** 346 of 368 hand-listed large
and mid caps that still trade today (`scripts/syms.txt`): no delisted stocks, so results
are survivorship-biased upward; no security list (bands, GSM/ASM), fundamentals, news or sectoral indices. The
**results calendar** comes from the bundled `backend/seed/nse-results-2016-2026.zip`
(each filing's dissemination time, after 15:30 counted on the next day; company names
matched to Yahoo's long names: 335 of 346 stocks, 12,354 dates; treated as known 7 days
ahead, SEBI's minimum notice). The seed has few filings after mid-2025. Benchmark is Nifty 500 (`^CRSLDX`).

| Strategy | Trades | Expectancy | PF | CAGR | Max DD | Sharpe | Holdout | Section 6 |
|---|---|---|---|---|---|---|---|---|
| **combined-book-v1** | 264 | +0.414R | 1.75 | 17.6% | 13.1% | 1.05 | **+0.04R (49), +5.8%** | **7 of 7** |
| results-drift-v1 | 166 | +0.339R | 1.83 | 12.3% | 9.0% | 0.74 | 0 trades (no 2026 results in seed) | 6 (holdout untestable) |
| reversal-v1 | 1,208 | +0.023R | 1.09 | 7.2% | 10.0% | 0.13 | -0.09R (211) | 3 |
| **momentum-v1** | 226 | **+0.833R** | 1.78 | 16.5% | 16.4% | 0.88 | **+0.18R (36), +3.8%** | **7 of 7** |
| fip-momentum-v1 | 220 | +0.569R | 2.03 | 17.5% | 15.5% | 0.96 | -0.29R (37) | 6 (holdout) |
| rs-pullback-v1 | 251 | +0.443R | 1.93 | 18.7% | 11.8% | 1.13 | -0.10R (53) | 6 (holdout) |
| high52-v1 (new) | 219 | +0.312R | 1.62 | 11.1% | 12.5% | 0.53 | -0.32R (46) | 5 (benchmark, holdout) |
| trend-breakout-v1 | 271 | +0.208R | 1.33 | 11.5% | 10.6% | 0.48 | +0.12R (36) | 5 (regimes, benchmark) |
| breakout-52w (+events) | 302 | +0.163R | 1.33 | 9.5% | 14.3% | 0.34 | -0.04R (52) | 5 |
| score-swing (+events) | 375 | +0.146R | 1.37 | 11.1% | 8.1% | 0.53 | -0.16R (75) | 4 |
| pullback-trend (+events) | 371 | +0.073R | 1.08 | 6.6% | 14.5% | 0.05 | -0.15R (68) | 3 |
| top-score-v1 | 422 | +0.023R | 1.00 | 4.4% | 14.3% | -0.18 | +0.07R (68) | 4 |

Nifty 500's Sharpe over the test: 0.60. The `-events` versions use the results blackout
(no news labels): it helped breakout-52w (+0.21R vs +0.16R) and pullback-trend, hurt
score-swing.

Not testable: `quality-trend-v1` needs fundamental scores (XBRL from NSE) and refuses
with a clear error; `sector-rotation-v1` made no trades without the sectoral indices.

## Reading

- **momentum-v1 is the only strategy that passes all seven checks here**, as it did on
  NSE data (2026-11-01: +0.67R, holdout +0.53R). Positive in bull, bear and sideways
  markets; by year 2019 -0.54R (8), 2020 +1.49R, 2021 +1.73R, 2022 +0.15R, 2023 +1.78R,
  2024 -0.17R, 2025 +0.32R. Two sources, same answer: it is the most robust strategy
  Jeron has.
- fip-momentum-v1 and rs-pullback-v1 have the best Sharpe in the test years but lost in
  this holdout year, unlike on NSE data. The holdout windows differ by a few days and
  the universes differ, so this is a warning, not a verdict: one year, ~40 trades.
- **high52-v1 failed** (pre-registered, run once): positive test years but below the
  benchmark Sharpe and a losing holdout. Research only; per its plan, not tuned.
- **combined-book-v1** (rs-pullback + results-drift in one account) also passes all
  seven, with a higher Sharpe (1.05) and smaller drawdown (13.1%) than momentum, but a
  thinner holdout (+0.04R). Two strategies pass on this data: momentum for expectancy,
  the combined book for a smoother curve.
- reversal-v1 fails again, as on NSE data.
- No parameter was changed after seeing these numbers.

Reproduce from `backend/`: `PYTHONPATH=. uv run python scripts/fetch.py DIR/yh
scripts/syms.txt`, then `PYTHONPATH=. uv run python scripts/run.py DIR` (with `syms.txt`
copied into `DIR`).
