# M3 backtest report: none of the first three strategies passes

Date: 2026-10-02. Runs 7, 8 and 9 in the database (runs 4 to 6 are the identical
reproducibility runs). Engine `engine-v1`, data fingerprint `531f9e4416cdcc24`.

**Verdict: no strategy is live-eligible.** All three make a little money after costs,
but none comes close to the spec's bar (expectancy above 0.15R, profit factor 1.3 or
more), and none beats buy-and-hold Nifty 500 on a risk-adjusted basis. Following the
ground rule "no signal without a backtested strategy behind it", M4 should not issue
signals from any of them.

## Data

- NSE bhavcopy, 2016-01-01 to 2026-10-01: 2,664 sessions, 2,897 stocks that could ever
  pass the price and turnover rules (delisted stocks included, renamed stocks joined).
- Corporate actions from NSE's PR files; prices split- and bonus-adjusted.
- Nifty 500, Nifty 50 and India VIX closes for every session except 2023-04-06 to
  2023-04-11 (three files NSE didn't serve; the last close is carried forward).
- NSE security lists (bands, GSM) from 2020-01-01.
- 2,664 data-quality reports: none FAIL. All are WARN, mainly because most days have no
  second-source cross-check yet.

## How it was tested

- Warm-up until 2017-01-09 (252 sessions).
- Walk-forward test **2019-10-03 to 2025-10-01**: six yearly windows, each traded with the
  grid point that had the best training Sharpe ratio on everything before it.
- Untouched holdout **2025-10-03 to 2026-10-01**.
- ₹10 lakh starting capital, 1% risk per trade, Zerodha delivery charges, slippage by
  liquidity, all section 5 sizing and exit rules (see `docs/plans/M3.md`).

## Results (walk-forward test period, after costs)

| | Score crossing (swing) | 52-week breakout (positional) | Pullback in uptrend (swing) | Spec bar |
|---|---|---|---|---|
| Trades | 427 | 504 | 359 | >= 100 |
| Win rate | 37.7% | 31.8% | 36.8% | reported only |
| Expectancy | **0.084R** | **0.092R** | **0.024R** | > 0.15R |
| Profit factor | **1.17** | **1.17** | **0.99** | >= 1.3 |
| Max drawdown | 20.0% | **25.6%** | 17.2% | <= 20% |
| CAGR | 3.2% | 5.1% | 0.2% | |
| Sharpe | **0.43** | **0.51** | **0.06** | > Nifty 500's 0.96 |
| Positive regimes | bear, bull | bull, bear, sideways | bear, sideways | >= 2 of 3 |
| Deflated Sharpe | 0.67 | 0.82 | 0.26 | 0.95 = unlikely to be luck |
| Holdout expectancy | 0.074R (71 trades) | 0.062R (91 trades) | 0.024R (63 trades) | > 0 |
| Holdout return | +1.8% | +1.9% | -2.2% | Nifty 500: -4.7% |
| Checks passed | 4 of 7 | 3 of 7 | 4 of 7 | 7 of 7 |

Nifty 500 over the same test period: CAGR 16.7%, Sharpe 0.96, max drawdown 38.3%.

## Why none passes

1. **The edge is too small.** Average trades make 0.02 to 0.09R. Costs (STT, charges,
   DP fees, slippage) take about 0.03R per trade, so even before costs no strategy
   reaches 0.15R. The shape is the same for all three: about 40% of trades hit the
   stop for -1.05R, about 20% run to the trailing stop for +2.1 to +2.4R, and the rest
   end near breakeven. That is not enough winners to pay for the losers.
2. **The results depend on the year.** All three did well in 2020, 2021 and 2023, and
   lost in 2022. The breakout strategy also lost in 2024 and 2025 (-0.2R and -0.3R a
   trade). The walk-forward kept switching settings for the score strategy (five
   different settings in seven windows), which is another sign that there's no stable
   edge to find.
3. **Buy-and-hold was very hard to beat from 2019 to 2025.** Nifty 500 compounded at
   16.7% a year. With 1% risk per trade and five to eight positions, the strategies
   are mostly in cash, and the backtest earns nothing on idle cash. So their returns
   are low (0% to 5% a year), and so are their Sharpe ratios, even though their
   drawdowns are about half the index's.
4. **The tech-v1 score isn't selective enough.** On most days far more stocks qualify
   than there are slots (the score strategy skipped 38,605 qualifying signals for lack of a
   slot over six years), and ranking by score doesn't pick better ones. The score strategy's best
   results came in bear-regime signals (+0.36R over 64 trades), and it was weakest in
   bull markets (+0.06R over 330 trades). That is too few trades to rely on.

## What did hold up

- In the holdout year, when Nifty 500 fell 4.7%, two strategies still made a small
  profit, and all three had drawdowns under 9%.
- Risk control worked as designed. No strategy lost more than 26% from its peak, while
  the index fell 38% in the same years. The drawdown brake paused new entries one to
  five times per strategy.

## What I'd try next (not done, needs your OK)

Every new idea is another trial and lowers the deflated Sharpe, so these should be few
and chosen before looking at the data again:

- **Credit idle cash** at a liquid-fund rate (about 6 to 7% a year). This is how you
  would actually hold the cash, and it changes the Sharpe comparison with the index.
  It's a change to the spec's benchmark rule, so it needs your decision.
- **Wait for the other two brains (M6).** The spec expects the fundamental and news
  scores to add selectivity. The technical score alone doesn't add enough.
- **A trend-following, longer-hold version of the breakout** (positional tier, wider
  trail, Nifty 500 members only). The breakout's winners came from long trends, and
  its losses from short failed breakouts.

## Bug found by the real-data run

A stock that paid a dividend larger than its stop distance lost the dividend in the
backtest. The bug was in the engine's handling of a stop that fires on the ex-date
(Majesco's ₹974 special dividend on 2020-12-23 was the case). It's fixed: a position
held into an ex-date is paid the dividend even if it's sold that day, and there's a
golden test for it.

## Caveats

- GSM exclusion applies only from 2020-01-01, the first NSE security list. ASM uses
  imported lists only, so it is not point in time.
- A circuit lock is detected only when the whole day trades at one price.
- The benchmark is the Nifty 500 price index without dividends, so it slightly
  understates buy-and-hold.
- Sector caps and the correlation check are not simulated yet (M4).

## Reproducibility

`python -m app.cli backtest` was run twice on the same database. Runs 4 to 6 and 7 to 9
have the same fingerprint and identical summaries, equity curves and trade lists. One
full run of all three strategies takes about 3 minutes, 2.5 of them loading data.
