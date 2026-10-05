# 0010: Trade plan with a pre-buy checklist, watchlist, sector heatmap, command palette

Date: 2026-10-05. Status: proposed (UI phase 1b).

**Decision.**
1. **Trade plan** (`/plan/[symbol]`, `?signal=<id>` starts from a signal's levels). The
   pure `app/plan/calc.py` sizes with the engine's own `position_size` and checks
   reward:risk with the engine's `reward_risk` (both extracted from
   `app/backtest/engine.py` unchanged, so golden trades are untouched): risk % of
   `JERON_CAPITAL` x the mood's multiplier (0.5 in defend, the engine's regime filter),
   capped at 20% of capital and 1% of the 20-day average volume. Targets are the
   engine's: T1 = +2R, T2 = +3R.
   - Hard checks (saving is refused, on the server too): stop below entry; stop at
     least 1 x ATR(14) and at most 12% (swing) / 20% (positional) below the entry;
     reward:risk to T2 at least 2 after costs; at least one share; portfolio heat after
     the buy at most 6%; the sector at most `JERON_SECTOR_CAP_PCT` after the buy; no
     results board meeting within the blackout (`blackout_signal_days`, as the
     `-events` strategies use).
   - Shown, not blocking: heat at the 5% warning, defend mode, a results calendar that
     isn't loaded, ex-dates in the next 30 days, a stock without a known sector.
   - Five checklist items must all be ticked to save.
   - The plan's entry is the price I intend to pay (default: the signal's zone high,
     which the engine sizes on, else the last close); the engine measures stop % from
     the signal close. Stocks outside the scan get ATR and volume from their own bars.
   - The account's drawdown brake is not applied: the journal doesn't know the
     account's equity curve. Capital is the setting, as on the Portfolio page.
2. **Plans are never changed** (`trade_plans`, a SQLAlchemy `before_update` guard
   raises). Saving again makes a new row with `supersedes_id`. A plan stores every
   number behind it and the checks as they were. Journal entries carry `plan_id`; the
   journal forms start from the plan (stop, reason, shares and price of the first fill).
3. **Watchlist** (`watchlist`, one row per stock): optional alert price, above (the
   day's high reaches it) or below (the day's low does), and a note. The alerts job (so
   `daily` and `alerts`) sends one alert per item, direction and price, keyed
   `watch:<id>:<direction>:<price>` in `alerts`; a re-run or a stock that stays above
   never alerts again, a new price arms it again. A hit is not a signal: the message
   says to plan it first.
4. **Stocks page**: a heatmap of NSE industries (the mood's sector strength: median
   6-month return, green/red by sign, stronger for bigger moves) and the latest scan's
   full ranked list (`GET /stocks/ranked`), 50 a page, by score, 6-month relative
   strength or return, filtered by the tile tapped.
5. **Command palette** (Ctrl+K / Cmd+K, a Search button on phones): stocks through the
   existing `/api/search` proxy, pages, and "plan <stock>". A modal dialog with focus
   kept on its input, arrow keys, Enter, Esc.

**Why.** A plan that sized or checked differently from the engine would teach habits
the backtests never tested; reusing the engine's functions keeps one definition.
Immutable plans make "followed the plan" in the journal measurable.

**Consequences.** Changing sizing in the engine changes plans too (by design). The
journal's "followed the plan" is still my own judgement; comparing fills to the linked
plan automatically is left for later.
