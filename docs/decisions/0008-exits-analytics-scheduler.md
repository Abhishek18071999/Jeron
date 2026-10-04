# 0008: Real positions use the engine's exit rules; stages are gated on resampled ranges

Date: 2026-10-04. Status: proposed (M7).

**Decision.**
1. The exit plan for a real position is the engine's rules (stop, breakeven at +1R, half
   at T1 = +2R from my average entry, 2 x ATR(14) trail on closing basis, the tier's time
   stop) replayed on adjusted bars since my first buy. Rule constants come from the
   engine, and a test checks both decide the same exit day on the same bars.
2. The pre-open check gives an action per position (sell all, sell half, hold) and never
   places orders. With missing prices it gives no actions and says why. A stale check is
   not stored as sent, so the next run after the daily job still goes out.
3. Tradebook fills are stored with "zerodha:<exchange>:<trade id>" (unique), so imports
   are idempotent. Charges are estimated at delivery rates and flagged as estimates.
4. The paper gate (3 months, 30 trades, expectancy > 0) and the small-real gate also
   require the result to sit inside an expected range: the 5th to 95th percentile of the
   average R of n trades resampled from the stage before. Short records get wide ranges.
5. The weekly revalidation retires a strategy version (paper account status "retired",
   with the reason and date) on a rolling 50-trade expectancy below 0, paper or real, or a
   paper drawdown above 1.5 x the backtest's. A retired version gets no new paper
   account; it needs a new version.
6. Jobs run from one APScheduler process (`scheduler` service): `preopen` 08:30 IST,
   `daily` 19:00 IST, `weekly` after the last session of the week.

**Why.** The same rules in backtest, paper and real are what make the comparison mean
something. Resampled ranges turn "within reason" into a number without a new tunable.

**Consequences.** Positional trades exit at the 60-session review if not +1R, as in the
engine. Years missing from `nse_holidays.csv` (2026 for now) fall back to weekdays, with
NSE's "not published" days counted as holidays when looking back.
