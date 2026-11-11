# Value v1: the cheapest rising stocks, monthly (invest tier)

Status: pre-registered on 2026-11-11, before any code or run on data. Under Abhishek's
standing request ("discover, build and execute the most profitable realistic strategy
possible"); the idea-first rule (post-review-v2) applies. Run it once with
`python -m app.cli backtest --strategy value-trend`.

## Why this idea, and what it costs
Jeron has tested momentum four ways, low volatility, the 52-week high, reversal,
results drift, sector rotation and quality with a trend. It has never tested **value**:
buying what is cheap against its earnings. Value is the oldest documented anomaly
(Basu 1977 on earnings yield; Fama and French 1992), it is the classic partner of
momentum because the two tend to fail at different times (Asness, Moskowitz and
Pedersen, "Value and Momentum Everywhere", 2013), and NSE publishes value indices on it
(Nifty 500 Value 50). Until 2026-11-11 it could not be tested through the holdout:
quarterly results stopped at December 2024 (`fundamentals-fetch-v1.md`).

Plain value buys falling knives, so practitioners pair it with a trend condition
(O'Shaughnessy's "trending value"; Asness et al.'s combination). This plan takes that
form, fixed now: cheap **and** rising.

The cost, said before the run: this is the 75th variant on the same ten years, and its
holdout year (2025-11-10 to 2026-11-09) has already been read for five other versions.
A pass is weaker evidence than it would have been a month ago, and the report counts it
against all variants. It is also not what `quality-trend-v1` was: that scored growth,
margins and P/E against the stock's own history; this ranks earnings yield across
stocks and ignores quality.

## The value rank
For each stock and session `t`, using only filings published before `t`
(`quarters_known`, as fund-v1):
- **Earnings yield** = trailing-four-quarter profit per share over the price: the
  inverse of `fundamentals/score.py` `pe_ratio`, taken at the raw close on the day each
  filing is published and carried forward by the adjusted price change (so a split
  between filings does not distort it). Undefined when the trailing profit is not
  positive, when a recent filing's units look wrong (`units_mismatch`), with fewer than
  four quarters known, and once the newest quarter is more than `STALE_DAYS` old.
- **Value rank:** its percentile among that day's universe stocks with a defined
  earnings yield, 0 = cheapest (highest yield). NaN outside the universe.

Banks and lenders are ranked with everyone else. Their earnings yields run higher; that
is a known lean of every simple value sort and is reported (sector share of the gains),
not adjusted.

## Rules, fixed now
- **Tier:** invest (long-term section): at most 15 positions, book half at +3R, trail
  4 x ATR(14), exit if not +1R within 250 sessions. Sizing, heat, drawdown brake, costs
  and fills are the engine's (`engine-v3`), unchanged.
- **Rebalance day:** the first session of each calendar month.
- **Entry** at the close of a rebalance day when the value rank is at most 0.20 (the
  cheapest fifth) and the stock's 12-1 return (`Market.mom_return`, momentum-v1's) is
  above 0. No market-regime filter beyond the engine's.
- **Exit** at the next open after a rebalance day on which the value rank is above 0.50
  (no longer in the cheaper half). An unknown rank is not an exit. The tier's other exits
  also apply.
- **Busy days:** the engine's existing order (highest tech-v1 score first).

Grid: one point, `stop_atr` 4.0. The 0.20 and 0.50 cut-offs are the conventional
quintile and median, fixed, not tuned.

## How it is judged
- Spec section 6, all seven checks, on the same walk-forward folds and holdout as every
  other strategy; out-of-sample and after-cost numbers only.
- Beside the gates: the evidence rating (decision 0018), the correlation of its daily
  returns with `fip-momentum-v1`, `momentum-v1` and `quality-trend-v1` (the idea predicts
  a lower correlation with the momentum versions than they have with each other, 0.72),
  the sector share of its gains, and the deflated Sharpe against all variants tried.
- The holdout is read once. If it fails, research only, said plainly, and no v2 tuned
  on what was seen.
- If it passes: live-eligible, paper trading in the long-term section; real money only
  after the paper gate and a moderate or strong rating. Statuses are the owner's.

## Building it
- `market.py`: `earnings_yields(days, symbols, fundamentals, raw_close, close)` and
  `value_ranks(yield, universe)`, stored as `Market.earnings_yield` and
  `Market.value_rank`; the rank is in the run's data fingerprint.
- `strategies.py`: `VALUE_TREND`, registered 2026-11-11.
- `signals/build.py`: the signal's reasons.
- Tests: the yield uses no filing before it is published and survives a split, the rank
  puts the cheapest first, entries only on rebalance days in the cheapest fifth with a
  positive 12-1 return, the exit, the walk-forward; the strategy guide.
