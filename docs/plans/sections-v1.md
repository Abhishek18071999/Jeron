# Four sections: swing, intraday, positional and long-term investing

Status: asked for by Abhishek on 2026-10-17 ("a separate section for swing, intraday,
positional and long term investment ... each will work on their own strategies and tell
me what and when and how much to buy and also the reason behind it"). The long-term
strategy below is pre-registered here, before any run on data.

## What a section is
One place per holding horizon, in the web app (Trade, `/trade/<section>`) and in the
Telegram summary. Each section shows:

- **Its state, in one line:** "live" (a strategy passed spec section 6 and is paper
  trading with alerts), "research only" (strategies exist, none passed: nothing to buy),
  "waiting for its first backtest", or "not running" (intraday: no data).
- **What to buy today:** the section's new live signals, each with
  - *what:* the stock, the setup and the strategy version;
  - *when:* the session it is valid for and how to place it (a limit at the top of the
    entry zone in the 09:00-09:07 pre-open auction; cancel at 09:15 if not filled), and
    what cancels it;
  - *how much:* shares, the rupees it costs at the top of the zone, the rupees at risk and
    what share of capital that is;
  - *why:* the signal's reasons, the exit plan, event risk and the strategy's
    out-of-sample backtest record.
- Research-only signals, labelled as not trades, below the live ones.
- The section's strategies with their stage (backtest gates passed, paper record) and its
  open paper positions.

Nothing new is decided here: every signal is still the engine's order from a paper
account (decision 0006), and a section with no strategy that passed section 6 says so
instead of showing picks. "No signal without a backtested strategy behind it" (spec 12)
holds in every section.

## The sections

| Section | Holding | Strategies | State today |
|---|---|---|---|
| Swing | 3-15 sessions | `score-swing-v1`, `pullback-trend-v1` and their `-events` versions | Research only: none passed (M3 report) |
| Intraday | same day | none | Not running: no intraday prices (below) |
| Positional | 1-6 months | `rs-pullback-v1` (passed), `breakout-52w`, `trend-breakout`, `results-drift`, `sector-rotation` (research only) | Live: rs-pullback-v1 |
| Long-term | 6-12+ months | `quality-trend-v1` (new, below) | Waiting for its first backtest |

The combined book (`combined-book-v1`) stays a backtest only, as its plan says.

## Intraday: what it would take
Jeron only has NSE's end-of-day files. An intraday strategy needs minute bars for years
to be backtested the way every other strategy is (walk-forward, costs, the seven
checks), and live bars during the day. What exists, as of October 2026 (from Zerodha's
and Angel One's forums and docs; to be confirmed before building):

- **NSE** publishes no free intraday history.
- **Yahoo Finance** gives 1-minute bars for the last 7 days only: enough to watch, not to
  test.
- **Zerodha Kite Connect** (the paid Connect plan, reported at ₹500 a month in 2026; the
  free Personal plan has no market data) includes historical minute candles and live
  quotes.
- **Angel One SmartAPI** is free with an Angel One account and serves historical candles
  (users report NSE equity intraday back to about 2016) and live quotes.

Spec section 0 says to ask before adding a data vendor, so the intraday section is built
as "not running" with this explanation, and nothing is fetched. With a source chosen,
intraday becomes its own milestone: an intraday `DataProvider`, bar storage, an
intraday engine (MIS costs, the broker's 15:20 square-off, intraday circuit handling),
pre-registered strategies, and the same seven checks.

## Long-term: `quality-trend-v1` (invest tier), fixed now

**Idea.** Own companies whose quarterly results are strong (fund-v1, decision 0013) while
the price confirms it with a long-term uptrend; sell when the results weaken or the trend
breaks. This is the spec's investing tier (section 1) and the first strategy that uses
the fundamental brain.

**The fundamental score, point in time.** For each stock, fund-v1 is computed on the day
each results filing is published, from the filings known before that day (the latest
filing per quarter, consolidated preferred, as on the stock page), with the raw close of
that day for P/E. A filing is used from the session after the day NSE published it. The
score holds until the next filing, and is unknown (no entry) once the newest quarter
ended more than 200 days ago. A qualified audit opinion scores 0. The valuation part
uses the price on the filing day, not each day's price: a simplification, said here.

**Entry** at the close, for a stock in the scan's universe, on the first day all of
these hold (they did not all hold the session before):
- fund-v1 at least `min_fund`;
- the close above the 50-day EMA and the 50-day EMA above the 200-day EMA.

No market-regime filter: the investing tier holds through regimes. The engine still
halves risk when the regime filter is on or the account is 10% below its peak.

**Stop** `stop_atr` x ATR(14) below the signal close; skip if that is more than 20% away
(the schema's limit for the invest tier).

**Exits (the invest tier's rules in the engine).**
- Stop to breakeven once a close is +1R.
- Book half at +3R (T1); T2 is +5R. The rest trails at 4 x ATR(14) below the highest
  close, closing basis, sold at the next open.
- Fundamental exit: sell everything at the next open after a new filing takes fund-v1
  below 50 (a qualified opinion included). An unknown score is not an exit.
- Time stop: sell at the next open if +1R isn't reached within 250 sessions.

**Portfolio.** At most 15 open positions (spec section 5, investing), 1% risk per trade,
6% heat and the engine's other rules, unchanged.

**Grid:** `min_fund` in {60, 70}, `stop_atr` in {3, 4}. Four variants; the walk-forward
picks on training data only.

**How it is judged.** The same folds, holdout and seven checks as every strategy,
out-of-sample and after costs. The deflated Sharpe is reported against its own 4
variants and against every variant tried so far (65 with these). Caveats known now:
- Fundamentals start in about 2019 (XBRL), so the early folds have few or no trades and
  100 trades may not be reached in the test years. Fewer than 100 fails the check; the
  report says so rather than widening the rules.
- The holdout year has been looked at for other strategies, so it is not untouched
  market history; paper trading decides, as with the combined book.
- Run once. No rule above changes after seeing a result; a change is `quality-trend-v2`.

**Trial count.** The combined book's deflated Sharpe stays against the 61 trials
its plan named; adding this strategy doesn't change that run.

## Building it
- `Tier.INVEST` with its own rules (`TierRules`: 15 positions, 20% stop, T1 +3R, T2 +5R,
  trail 4 x ATR, 250-session time stop); the engine, the signal, the exit check and the
  trade plan take T1, T2 and the trail from the tier. Swing and positional keep the
  section 5 values, so every golden trade stays the same.
- A strategy may have an exit condition (sell at the next open); only
  `quality-trend-v1` has one.
- `Market.fund_score`, built from `financial_results` in `load_inputs`.
- `JERON_MAX_POSITIONS_INVEST` (default 15), also on the Settings page.
- `app/sections/` (what each section holds and its state; pure) with `GET /sections` and
  `GET /sections/{key}`; the web app's Trade pages; the Telegram summary grouped by
  section and each signal alert headed with its section.

## Tests
- Engine: invest-tier exits (T1 at +3R, the 4 x ATR trail, the fundamental exit, the
  250-session time stop); golden trades unchanged.
- The point-in-time fund-v1 series: a filing counts from the next session, revisions
  replace, staleness, qualified opinion.
- `quality-trend-v1`'s entry (crossing) and exit conditions.
- Sections: state per section from strategy and account states; the signal card's what,
  when, how much and why; the API; the summary text.

## Acceptance
- `/trade` shows four sections; each says plainly whether there is anything to buy.
- Positional shows rs-pullback-v1's signals with what, when, how much and why; swing and
  long-term say why they have none; intraday says what it would take.
- After `backtest --strategy quality-trend` and `paper`, the long-term section shows the
  strategy's result and its paper account (research only unless it passes).
