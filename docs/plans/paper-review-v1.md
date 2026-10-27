# Paper review v1: paper trading performance and strategy optimisation

Asked for on 2026-10-26: paper-trade every stock in the Stocks section that scores above
90/100, strictly by its plan, and add a section that reviews the paper results and
proposes improvements, which are only adopted after testing on unseen data.

## What already existed (reused, not rebuilt)

- **Paper trading** (`app/paper/job.py`, decision 0006): each strategy version has a
  paper account that the backtest engine replays every trading day from real
  end-of-day data, after the daily scan, run by the scheduler. Entry zone, stop, target,
  trailing exit, time stop, sizing, heat, drawdown brakes, costs and slippage are the
  engine's. Signals are stored once (spec section 4 schema), never changed.
- **Trade list, equity, drawdown** per paper account (`/paper/[id]`).
- **Backtest vs paper vs real** (`app/analytics/compare.py`) and the weekly
  revalidation that retires failing strategies (`app/analytics/weekly.py`).
- **Walk-forward backtester** with a 12-month holdout and the section 6 gates.

Being built in other threads, so not rebuilt here: the confidence engine, strategy
status labels and degradation monitor ("Prove Jeron's edge"), and the "bought anyway"
measure of entries skipped for opening above the zone (PR #38).

## The 90+ score

The score in the Stocks section is **tech-v1** (0 to 100, technical only). There is no
combined score yet: the fundamental and news brains are separate numbers. So "above
90" means tech-v1 >= 90.

The M3 report found tech-v1 at 70 to 85 isn't selective enough (`score-swing-v1`,
0.110R, 4 of 7 checks). 90 is outside that grid, so it is a **new strategy version**,
not a setting: `top-score-v1`, registered 2026-10-26, one fixed grid point (no
selection, so one trial):

- Enter when tech-v1 closes at or above 90 after being below it the day before.
- Stop 2 x ATR(14); the swing tier's exits (half at +2R, breakeven at +1R, 2 x ATR
  trail, 15-session time stop) and every section 5 sizing and risk rule.
- M6's results blackout and bad-news filter on.

Like every strategy, the autopilot backtests it, then the paper job trades it every
day from the scheduler's run. Until it passes section 6 its signals are research only
(never alerts). No trade is ever seeded or typed in: an account starts on the day it
opens and only the replay of stored end-of-day data fills it.

## The section (`/paper/performance`)

One page per paper account (picker at the top; `top-score` first), always headed
"simulated", with the data limits listed.

1. **Live trade journal**: open positions (entry, stop now, last close, unrealised P&L,
   share of equity), closed trades (entry/exit dates and prices, charges, net P&L, R,
   why it was entered from the signal's reasons, why it was sold), capital allocation
   (positions, sectors, cash).
2. **Performance**: return, win rate, average win/loss R, realised reward:risk,
   expectancy with its 95% range, profit factor, max drawdown, Sharpe and Sortino above
   the 6.5% cash rate, streaks, exposure, against Nifty 500 over the same days and the
   backtest's numbers.
3. **Plan evaluation**: what worked (exit reasons, best trades), what failed (stops,
   false signals: stopped out within 3 sessions), stops that gapped through (worse than
   -1.2R), missed opportunities (signals the rules skipped, by reason, with the stock's
   move over the next 10 sessions against the trades taken), and deviations: signals
   issued late (catch-up), and signals a later replay no longer gives (data changed).
   Paper follows the plan by construction, so these are where reality and plan parted.
4. **Root causes**: closed trades grouped by what was known at the signal: market
   regime, regime filter on/off, sector, score band, ATR % band, RSI band. Each group's
   average R with its 95% range; loss concentration.
5. **Strategy optimisation**: proposals, made by a fixed rule, never by hand-picking: a
   group of at least 20 closed trades whose average R's 95% range is entirely below 0,
   while the other trades (also at least 20) average above 0, becomes "skip entries
   where <group>". A strategy that loses everywhere gets no proposal; the weekly
   revalidation deals with it. Each proposal is stored with the evidence and
   time it was made and is never changed; its status moves on in its own columns.
   Exit, sizing and risk-control changes are shown as observations only: they change
   the engine's rules and need a new strategy version written by hand.
6. **Validation**: a proposal is tested on data its evidence never saw.
   - Backtest: the strategy with and without the filter, walk-forward with the 12-month
     holdout, on the history **before the paper account opened** (the evidence came
     from the paper period). Passes if the filtered version has at least 100
     out-of-sample trades, better out-of-sample expectancy, positive and better holdout
     expectancy, and a max drawdown no more than 2 points worse.
     This needs about five years of stored history before the account opened (warm-up,
     two years of training, a test year and the holdout); with less, the proposal is
     marked "could not test" with the reason.
   - Forward: the paper trades signalled after the proposal was made, split by the
     filter. Reporting only; under 20 trades it says too few to judge.
   - A proposal that passes is "ready for a new version": adopting it means registering
     a new strategy version in code, backtested like any other. Jeron never changes a
     strategy by itself. Every proposal tested counts as a trial.

## Audit trail

`paper_events` (append-only): signal issued, trade entered, partial exit, trade closed,
signal skipped, with the date it refers to and the time Jeron first recorded it. Paper
trades are re-derived on every replay; the events keep what was seen when. If a replay
later disagrees (data corrected), the earlier event stays and the account notes say so.

## Schema

- `paper_trades.context` (JSONB): what was known at the signal close (score, regime,
  regime filter, sector, ATR %, RSI, volume ratio) and the signal's reasons.
- `paper_events`: account, kind, event date, ticker, detail, recorded_at; unique on
  (account, kind, event date, ticker).
- `strategy_proposals`: strategy version, account, filter (dimension, group), evidence,
  created_at; backtest result and status with their own timestamps; forward result.

## Jobs

- The paper job stores the context, the missed-opportunity summary, the performance
  numbers and the new audit events on every update.
- `python -m app.cli paper-review` records proposals and refreshes forward checks.
- `python -m app.cli proposal-validate [ID] [--limit N]` runs the backtest check. The
  scheduler runs `paper-review` and `proposal-validate --limit 2` after the weekly job.

## Tests

- `top-score-v1` entries: crossing 90, the regime filter, one grid point.
- Review (pure): metrics, false signals, gap-through stops, groups and intervals,
  proposal rule (fires only with 20+ trades and the range below 0), filter masks match
  the trade context.
- Validation rule (pure): each pass/fail condition.
- Database: the paper job stores context, events once (a re-run adds none), missed
  summary; the review API; proposals recorded once; validation end to end on the
  made-up market.

## Not in v1

- Intraday fills or timestamps: Jeron only has end-of-day data, so fills are at the
  open price of the day and times are the session dates.
- Automatic adoption of anything.
- A combined three-brain score: the spec asks for it, the weights aren't calibrated yet.
