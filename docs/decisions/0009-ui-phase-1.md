# 0009: Five-item navigation, the Today screen and the market mood

Date: 2026-10-05. Status: proposed (UI phase 1).

**Decision.**
1. Navigation has five items: Today (`/`), Stocks (`/stocks`), Portfolio (`/portfolio`),
   Journal (`/journal`) and Research (`/research`, a hub linking Scanner, Backtests, Paper
   trading, Compare, Data quality and Spot check). Desktop shows them in the header next
   to the stock search; phones get a fixed bottom tab bar. Every earlier route still
   works; research pages highlight "Research".
2. Today answers "what do I do before the open?" in its first line, then shows the market
   mood, three cards (actions due, new signals, your risk), sector strength and the
   system status. Actions come from the pre-open check (`app.exits.job`) via
   `GET /portfolio`; with stale prices it shows no actions and says which command to run.
3. The market mood (`app/market/mood.py`, `GET /market/mood`) uses the engine's regime
   filter unchanged (`market_state`: Nifty 50 below its 200-day EMA, or India VIX in the
   top decile of five years) and adds breadth only to word the advice:
   - **defend**: regime filter on; risk per trade x0.5 (what the engine already does);
   - **attack**: filter off, at least 60% of the scan universe above its 200-day EMA, and
     more new 52-week highs than lows; risk x1.0;
   - **normal**: anything else; risk x1.0.
   New highs and lows use adjusted prices: the day's high above every high of the
   previous 251 sessions (lows likewise), counted only with 252 sessions of history.
   Sector strength is the median 6-month return per NSE industry (from the Nifty 500
   list), strongest first.
4. Portfolio risk uses the engine's definitions: open risk = (entry - today's stop) x
   shares (zero once the stop is at breakeven), heat against the 5% warning and 6% block,
   sector exposure against `JERON_SECTOR_CAP_PCT`, all on `JERON_CAPITAL`.
5. Look: colour tokens in `globals.css` for light and dark (system setting), green/red
   only for gains and losses, one accent for "act now", amber for limits; tabular digits;
   shared components in `src/components/ui.tsx`. Every empty state names the command
   that fills it.

**Why.** The mode must never disagree with what the engine, paper trading and signals
actually do, so it adds no sizing rule of its own; the 60% breadth line is the only new
threshold and it changes wording, not money.

**Consequences.** "Attack" and "normal" size trades the same. The 60% threshold is
untested; if breadth is ever used for sizing it needs a backtest and a new strategy
version first.
