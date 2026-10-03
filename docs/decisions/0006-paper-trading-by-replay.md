# 0006: Paper trading replays the backtest engine; signals are stored once

Date: 2026-10-03. Status: proposed (M4).

**Decision.**
1. Paper trading is the backtest engine run forward: each day, every strategy's paper
   account is replayed by `app.backtest.engine.simulate` from its first day to the
   newest scanned day, on the stored data, with the grid point and portfolio settings
   it opened with.
2. The engine's orders become signals in the spec's section 4 schema
   (`app/signals/`), validated and stored once (`signals`), never changed. Paper trades
   and daily equity are re-derived on each replay.
3. The risk manager is the engine: sizing, heat, drawdown brakes, exits and costs were
   already there; the sector cap, correlation check and configurable position limits
   are new opt-in rules (off in backtests, so M3's results don't change).
4. Strategies that failed section 6 are paper-traded too, with every signal marked
   research only.

**Why.**
- Spec section 7 asks for paper trading "with the same rules". Sharing the engine
  makes that true by construction; a separate paper trader would drift from it.
- A replay needs no stored engine state (open positions, trailing stops, pauses), so
  a missed day, a restart or a code fix can't leave an account half-updated. With the
  same data, a replay gives the same trades every day (the engine is deterministic).
- Signals are what a person would have seen, so they are kept as issued even if a
  later replay differs (for example after a data correction); the account's notes say
  when that happens.
- Research-only paper trading gathers forward evidence on the M3 strategies without
  breaking "no signal without a backtested strategy behind it": they are never alerts.

**Consequences.** Each update rebuilds the market from the account's first day minus
450 sessions, so it grows slowly over the years (a backtest over ten years takes
minutes, so this stays cheap). Changing an account's parameters or settings means a
new account (`paper --restart`). The sector cap uses today's NSE industries, so it is
not applied to backtests.
