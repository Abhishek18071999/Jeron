# Residual momentum v1: the leaders after the market's share is taken out (invest tier)

Status: pre-registered on 2026-11-07, before any code or run on data. Asked for by
Abhishek ("make the world's most successful and most profitable strategy ever").
Run it once with `python -m app.cli backtest --strategy residual-momentum`.

Nobody can build "the most profitable strategy ever", and nobody can know in advance
which strategy will be best after the backtest. 68 variants have been tried on these ten years and
the best, `fip-momentum-v1`, has a deflated Sharpe of 0.38 against all of them
(`docs/backtests/all-strategies-2026-11-06-report.md`): luck is not ruled out even for
the winner. Picking the best of many more tries would only make that worse. A new
strategy gets its best chance of working after the backtest through the project's rule
(post-review-v2, P): one documented effect, rules fixed before the data, one run.

## Why this idea
Blitz, Huij and Martens, "Residual momentum" (Journal of Empirical Finance, 2011): rank
stocks on the part of their past-year return that the market factors don't explain,
scaled by that part's volatility, instead of on the total return. In their US data
(1930-2009) residual momentum earned about the same return as plain momentum at about
half the volatility. That roughly doubles the Sharpe ratio. It also lost far less in
momentum's crashes, because plain momentum loads on whatever the market did over the
past year and residual momentum does not. Gutierrez and Prinsky (Journal of Financial
Markets, 2007) report the same for "alpha momentum" on market-model residuals: it keeps
paying, while total-return momentum partly reverses.

It is chosen because:
- it goes after the weakness the reports keep finding in Jeron's best family: the
  momentum strategies' drawdowns (14 to 15%) and their Sharpe barely above Nifty 500's
  (`momentum-v1` 0.61 against 0.57). The paper's main finding is that residual momentum
  keeps the return and drops the market-driven part of the risk;
- it is a documented anomaly with a reason behind it (investors under-react to
  stock-specific news; a rise that came only from a high beta in a rising market is not
  news about the company), not a parameter search;
- it is a different ranking of `momentum-v1`'s universe on `momentum-v1`'s calendar, with
  `momentum-v1`'s exit rule. So the test asks one clean question: does ranking on the
  residual instead of the total return improve the momentum leaders?
- it trades monthly (low costs, mostly long-term tax) and needs only prices and Nifty
  500, both already in Jeron.

It is still the momentum family, which post-review-v2's point 1 warns about. The report
gives the correlation of its daily returns with `momentum-v1` and `fip-momentum-v1`. The
paper predicts a correlation well below 1 and a smaller drawdown. If neither shows, that
is a finding too.

## Deviation from the paper, decided now
The paper uses the Fama-French three factors over 36 months of monthly returns. Jeron has
no Indian size and value factors, and 36 months would drop every stock listed less than
three years before each day. So v1 uses the market model on daily returns (as Gutierrez
and Prinsky), over `momentum-v1`'s 12-1 window. It is a simpler version of the effect,
not the paper's exact one, and the report says so.

## Residual momentum score
For each stock and session `t`, using only data up to `t`, over the daily returns inside
`momentum-v1`'s 12-1 window (returns at sessions `t - 251` to `t - 21`, 231 of them, as
`fip-momentum-v1`), on the sessions where both the stock's and Nifty 500's daily return
are defined (at least 180 of them):
- **beta** = OLS slope of the stock's daily return on Nifty 500's daily return in that
  window (with an intercept);
- **residual** on each session = the stock's return minus beta x Nifty 500's return.
  The intercept is left in the residual: that steady excess return is the signal;
- **score = sum of residuals / standard deviation of residuals**, both over the window
  (the paper's residual return over residual volatility);
- **rank:** the score's percentile among the day's universe (1 = strongest). NaN outside
  the universe or with too few returns.

## Rules, fixed now
- **Tier:** invest (long-term section), as `momentum-v1`: at most 15 positions, book half
  at +3R, trail 4 x ATR(14), exit if not +1R within 250 sessions. Sizing, heat, drawdown
  brake, costs and fills are the engine's (`engine-v3`), unchanged.
- **Rebalance day:** the first session of each calendar month.
- **Entry** at the close of a rebalance day when the residual momentum rank is at least
  0.9 (the top tenth: the paper's top decile).
- **Exit:** at the next open after a rebalance day on which the residual momentum rank is
  below 0.75 (out of the top quarter, `momentum-v1`'s buffer). An unknown rank is not an
  exit. The tier's other exits also apply.
- **Busy days:** the engine's existing order (highest tech-v1 score first).

Grid: one point, `min_rank` 0.9 and `stop_atr` 4.0 (`momentum-v1`'s defaults). The decile
is the paper's sort and the windows are `momentum-v1`'s; nothing is tuned.

## How it is judged
- Spec section 6, all seven checks, on the walk-forward folds and holdout used by every
  other strategy; out-of-sample and after-cost numbers only.
- Beside the gates: the evidence rating (decision 0018), and the same numbers for
  `momentum-v1` and `fip-momentum-v1` from their stored runs. The idea predicts a lower
  drawdown and a higher Sharpe than `momentum-v1` at a similar expectancy. Also reported:
  the correlation of daily returns with both, and the deflated Sharpe against its own
  grid and against every variant tried so far (69 with this one).
- The holdout year has not been seen for this strategy; it is read once, after the run.
- If it passes, it is live-eligible: paper trading with alerts in the long-term section,
  then the paper gate (3 months, 30 trades) and a moderate or strong evidence rating
  before any real money (decision 0018). If it fails, it is research only, and the
  report says so plainly.
- Run once. No rule above changes after seeing a result; a change is
  `residual-momentum-v2` with its own plan.

## Building it
- `market.py`: `residual_momentum_ranks(close, universe, nifty500)` beside
  `fip_ranks`, stored as `Market.resmom_score` and `Market.resmom_rank`; the rank is
  included in the run's data fingerprint.
- `strategies.py`: `RESIDUAL_MOMENTUM`, registered 2026-11-07.
- `signals/build.py`: the signal's "why" lines; `web/src/lib/strategy-guide.ts`: the guide.
- Tests: beta and the residual against a direct least-squares fit, a high-beta stock that
  only rode the market ranks below a stock with the same return and no beta, no future
  data, too few returns, entries only on rebalance days in the top tenth, the exit, one
  grid point, and the walk-forward run.
