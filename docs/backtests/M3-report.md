# M3 backtest report: none of the first three strategies passes

Date: 2026-10-03. Runs 13, 14 and 15 in the database. Engine `engine-v2` (idle cash
earns a liquid-fund rate), data fingerprint `531f9e4416cdcc24`. The first version of
this report (runs 4 to 9, `engine-v1`, no interest on cash) is summarised at the end.

**Verdict: no strategy is live-eligible.** With idle cash earning 6.5% a year, the
52-week breakout passes five of the seven checks and the score crossing four, but none
reaches a profit factor of 1.3, and none beats buy-and-hold Nifty 500 on a
risk-adjusted basis. Following the ground rule "no signal without a backtested strategy
behind it", M4 should not issue signals from any of them.

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
- **Idle cash earns 6.5% a year**, as it would in a liquid fund (your decision,
  2026-10-03). The interest is taxed at the 30% slab in the tax estimate. Sharpe ratios,
  for the strategies and for Nifty 500, count only returns above that 6.5%, so a
  strategy gets no risk-adjusted credit for sitting in cash.

## Results (walk-forward test period, after costs)

| | Score crossing (swing) | 52-week breakout (positional) | Pullback in uptrend (swing) | Spec bar |
|---|---|---|---|---|
| Trades | 417 | 442 | 360 | >= 100 |
| Win rate | 38.4% | 33.9% | 36.7% | reported only |
| Expectancy | **0.110R** | 0.186R | **0.024R** | > 0.15R |
| Profit factor | **1.22** | **1.25** | **1.03** | >= 1.3 |
| Max drawdown | 17.1% | 16.9% | 14.0% | <= 20% |
| CAGR (with interest) | 8.8% | 11.2% | 5.5% | |
| of which interest on cash | about 4% a year | about 3.5% a year | about 4% a year | |
| Sharpe above 6.5% | **0.30** | **0.43** | **-0.08** | > Nifty 500's 0.60 |
| Positive regimes | bull, bear, sideways | bull, bear | bear, sideways | >= 2 of 3 |
| Deflated Sharpe | 0.54 | 0.84 | 0.20 | 0.95 = unlikely to be luck |
| Holdout expectancy | 0.037R (70 trades) | 0.133R (92 trades) | 0.066R (59 trades) | > 0 |
| Holdout return | +6.5% | +3.8% | +1.3% | Nifty 500: -4.7% |
| Checks passed | 4 of 7 | 5 of 7 | 4 of 7 | 7 of 7 |

Nifty 500 over the same test period: CAGR 16.7%, Sharpe above 6.5% of 0.60, max
drawdown 38.3%.

Interest is a large part of the profit: of the pre-tax gain over six years, it is
₹3.5 lakh of ₹6.9 lakh for the score crossing, ₹3.2 lakh of ₹8.8 lakh for the breakout
and ₹3.0 lakh of ₹3.3 lakh for the pullback. The trades themselves earned about ₹3.4
lakh, ₹5.6 lakh and ₹0.3 lakh.

## Why none passes

1. **The edge is too small.** Average trades make 0.02 to 0.19R, and the profit
   factor is 1.03 to 1.25. Costs (STT, charges, DP fees, slippage) take about 0.03R
   per trade. The shape is the same for all three: about 40% of trades hit the
   stop for about -1R, about 20% run to the trailing stop for +2 to +2.5R, and the rest
   end near breakeven. That is not enough winners to pay for the losers.
2. **The results depend on which settings the walk-forward picks, and that is not
   stable.** Crediting interest changed which grid point won some training windows,
   and the trades changed with it: the breakout went from 0.092R (first version) to
   0.186R, the score crossing from 0.084R to 0.110R. A real edge would not move that
   much on a detail of how settings are chosen. The breakout's 0.186R is still below the
   bar on profit factor and Sharpe, and its deflated Sharpe (0.84) says it could be
   luck.
3. **The results depend on the year.** All three did well in 2020, 2021 and 2023, and
   lost in 2022. The breakout strategy also lost in 2024 and 2025 (-0.15R and -0.19R
   a trade), so its good average rests on 2020, 2021 and 2023. The walk-forward kept
   switching settings for the score strategy (four different settings in seven
   windows), which is another sign that there's no stable edge to find.
4. **Buy-and-hold was very hard to beat from 2019 to 2025.** Nifty 500 compounded at
   16.7% a year. With 1% risk per trade and five to eight positions, the strategies
   are mostly in cash. Interest on that cash lifts their returns to 5.5% to 11% a
   year, but their returns above the cash rate are small next to their swings, so
   their Sharpe ratios stay below the index's, even though their drawdowns are less
   than half the index's.
5. **The tech-v1 score isn't selective enough.** On most days far more stocks qualify
   than there are slots (the score strategy skipped 40,849 qualifying signals for lack
   of a slot over six years), and ranking by score doesn't pick better ones. The score
   strategy's best results came in bear-regime signals (+0.28R over 61 trades), and it
   was weakest in bull markets (+0.09R over 320 trades). That is too few trades to rely
   on.

## What did hold up

- In the holdout year, when Nifty 500 fell 4.7%, all three made money (+1.3% to
  +6.5%, interest included) with drawdowns under 9%, and all three had positive
  expectancy on their trades.
- Risk control worked as designed. No strategy lost more than 17.1% from its peak,
  while the index fell 38% in the same years. The drawdown brake paused new entries
  once for two of the strategies.

## What I'd try next (not done, needs your OK)

Every new idea is another trial and lowers the deflated Sharpe, so these should be few
and chosen before looking at the data again:

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

`python -m app.cli backtest` was run twice on the same database with `engine-v1`: runs 4
to 6 and 7 to 9 have the same fingerprint and identical summaries, equity curves and
trade lists. The engine has no randomness; runs 13 to 15 were run once, as agreed. One
full run of all three strategies takes about 3 minutes, 2.5 of them loading data.

## First version (engine-v1, no interest on cash)

Runs 7 to 9, 2026-10-02. Idle cash earned nothing and Sharpe ratios had no risk-free
rate.

| | Score crossing | 52-week breakout | Pullback |
|---|---|---|---|
| Trades | 427 | 504 | 359 |
| Expectancy | 0.084R | 0.092R | 0.024R |
| Profit factor | 1.17 | 1.17 | 0.99 |
| Max drawdown | 20.0% | 25.6% | 17.2% |
| CAGR | 3.2% | 5.1% | 0.2% |
| Sharpe (Nifty 500: 0.96) | 0.43 | 0.51 | 0.06 |
| Deflated Sharpe | 0.67 | 0.82 | 0.26 |
| Checks passed | 4 of 7 | 3 of 7 | 4 of 7 |

An intermediate run (10 to 12) credited the interest but still measured Sharpe from
zero, which counted the riskless 6.5% as skill: the score crossing showed a Sharpe of
1.40 against the index's 0.96. That comparison was wrong, so runs 13 to 15 measure both
above the cash rate. Runs 10 to 12 stay in the database, as every run does.
