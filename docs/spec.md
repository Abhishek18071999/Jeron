# Jeron specification

The build brief every milestone follows. Changes to it need Abhishek's approval.


You are a senior quant engineer and full-stack developer. Build **Jeron**, a personal
research and decision-support tool for Indian cash equities (NSE/BSE), used by one
person (me) to find, plan, track and review swing, positional and long-term trades.

Jeron has one job: **prove, with honest numbers, whether its rules make money after
costs, and then help me follow those rules with discipline.** It must earn my real
money step by step: backtest, then paper trade, then small real capital, then full
capital. If the evidence says a strategy doesn't work, Jeron says so plainly.

Build it so it can grow into a multi-user product later (clean modules, a
`DataProvider` interface, a `users` table), but do **not** build multi-user features,
payments, marketing pages or compliance flows now.

### 0. How you work (read first)

1. Before writing code for a milestone, write a short plan in `docs/plans/M<n>.md`
   (scope, data sources, schema changes, tests, acceptance checks) and wait for my
   approval.
2. One milestone = one branch + one pull request. Keep `main` working.
3. Maintain `CLAUDE.md` (how to run, test, lint; conventions) and `docs/decisions/`
   (one short note per significant choice).
4. Tests are part of "done": unit tests for every indicator, sizing rule and risk rule;
   golden-file tests for the backtester (known inputs → known trades → known P&L).
5. Never commit secrets (API keys, broker tokens). Use `.env.example` + env vars.
6. Ask me before signing up for any paid service or adding any data vendor.
7. Prefer simple over clever. When a rule here is ambiguous or looks wrong, say so and
   propose a fix instead of guessing.

### 1. Trading horizons

| Tier | Holding period | Starting brain weights (Tech / Fund / News) |
|---|---|---|
| Swing | 3–15 trading days | 60 / 15 / 25 |
| Positional | 1–6 months | 40 / 35 / 25 |
| Investing | 6–12+ months | 20 / 60 / 20 |

Weights are starting points; the backtester picks the final ones per tier using
walk-forward tests and logs them.

**Long-only.** Cash-market shorts can't be held overnight in India. F&O is out of
scope.

### 2. Universe and data

**Universe (rebuilt daily, point-in-time):**
- Nifty 500 + other NSE mainboard stocks passing: 20-day median turnover ≥ ₹5 cr,
  price ≥ ₹20.
- Exclude ASM/GSM surveillance stocks, T2T segment, SME platform, suspended stocks.
- My order size must be ≤ 1% of the stock's 20-day average volume.

**Data (behind a `DataProvider` interface so sources can be swapped):**
- History for backtests: NSE bhavcopy archives (official daily files) as the source of
  truth; yfinance (`.NS`) only as a convenience/cross-check.
- Daily and live data for my own use: Zerodha Kite Connect (my own account, personal
  use is within its terms) or another broker API I choose. Ask me which before
  building the adapter.
- **Data correctness is milestone-zero important** (it's the first thing I want to
  verify):
  - Cross-check every day's close for the universe between two sources; flag
    differences > 0.5%.
  - Corporate-action adjustment (splits, bonus, rights, dividends); keep raw and
    adjusted series; show the adjustment log.
  - Daily data-quality report: missing days, zero volume, > 20% moves without a
    corporate action, stale prices. If it fails, the scan doesn't run and I'm told why.
  - A "spot check" page: pick any stock and date, see raw vs adjusted prices and
    indicator values next to each other, so I can compare against my broker's chart.
- Point-in-time: index membership history including delisted stocks (no survivorship
  bias) and fundamentals keyed by announcement date (no look-ahead bias).
- Price bands/circuit limits per stock; model that a stop can fail to fill on a
  lower-circuit day and fills at the next open.
- Fundamentals: sales/EPS growth (3y, TTM), ROE, ROCE, debt/equity, interest cover,
  margin trend, operating cash flow vs profit, promoter holding and pledge trend,
  valuation (P/E, EV/EBITDA) vs the stock's own 5-year percentile and vs sector.
  Source: exchange filings or a data source I approve; for a personal tool, a manual
  CSV export from a screener site is an acceptable first step.
- Market regime and flows: Nifty 50 vs its 200-EMA, breadth (% above 200-DMA),
  India VIX, FII/DII daily provisional cash flows.
- Events: each company's board-meeting/results date from exchange announcements.
  No new entries from 3 trading days before results until the day after.
- News: exchange corporate announcements first, then a few RSS feeds. Map to tickers,
  de-duplicate, time-decay by event type.

### 3. Scoring: three brains (0–100 each, combined per tier weights)

1. **Technical:** close > 200-EMA, 20-EMA > 50-EMA, RSI(14), MACD, ADX(14) > 20,
   breakout volume > 1.5× 20-day average, distance from 52-week high, ATR(14) % of
   price, relative strength vs Nifty 500 (3 and 6 months), support/resistance from
   swing pivots.
2. **Fundamental:** quality (growth, returns on capital, balance sheet, earnings
   quality, pledge) + valuation percentile. Hard reject: pledge > 25% or rising
   sharply, negative operating cash flow 3 years running, auditor resignation or
   qualified opinion in the last 12 months.
3. **News/events:** an LLM labels each item with an event type (results, guidance,
   order win, regulatory action, promoter activity, rating change, management change,
   litigation, other) and sentiment −2…+2 with a one-line reason, as strict JSON
   validated against a schema. The LLM never produces prices, targets or stops.
   Cache labels; store model name and prompt version. I'll hand-label ~100 headlines
   as a test set; report accuracy on it.

**Threshold:** start at combined ≥ 80, then calibrate per tier on the backtest.
**Regime filter:** if Nifty 50 < 200-EMA or VIX is in its top decile, halve risk for
swing and positional and require ≥ 85.

### 4. Signal schema (every field mandatory; incomplete signals are rejected)

```json
{
  "signal_id": "uuid", "created_at": "IST", "data_as_of": "IST",
  "ticker": "NSE symbol", "setup_name": "e.g. 52w-high breakout with volume",
  "strategy_version": "id of the backtested strategy",
  "tier": "swing|positional|invest", "direction": "long",
  "why": ["3–5 plain-language reasons"],
  "entry_zone": {"low": 0, "high": 0, "valid_until": "date"},
  "stop": {"price": 0, "type": "structural|ATR", "reason": "e.g. below swing low 1,234"},
  "targets": {"t1": 0, "t2": 0, "basis": "e.g. prior high / measured move"},
  "risk_reward_t1": 0, "risk_reward_t2": 0,
  "expected_holding": {"min_days": 0, "max_days": 0},
  "shares": 0, "capital_at_risk": 0,
  "exit_plan": "book 50% at T1, stop to breakeven, trail rest by 2×ATR",
  "time_stop_days": 0,
  "invalidation": "condition that cancels the idea before or after entry",
  "event_risk": "e.g. results in 9 days",
  "conviction": 1,
  "brains_breakdown": {"technical": 0, "fundamental": 0, "news": 0, "combined": 0},
  "backtest_stats": {"trades": 0, "win_rate": 0, "avg_R": 0, "expectancy_R": 0,
                     "profit_factor": 0, "max_drawdown_pct": 0, "period": "..."}
}
```

- Reject if reward:risk to T2 < 2.0 after estimated costs and slippage.
- Reject if entry-to-stop < 1×ATR or > 12% (swing) / 20% (positional).
- Signals are immutable once created; changes create a new version. Keep all history.

### 5. Risk manager (non-negotiable; enforced in code)

- `shares = floor((capital × risk%) / (entry − stop))`, capped at 20% of capital per
  position and ≤ 1% of 20-day average volume.
- Risk per trade 0.5–2% (setting, default 1%; regime filter can halve it).
- Max open positions: 5 swing, 8 positional, 15 investing (configurable).
- Sector cap ≤ 30% of capital; correlation check (3 banks ≠ 3 separate trades).
- Portfolio heat (total open risk) ≤ 6%: warn at 5%, block new entries at 6%.
- Drawdown brake: account down 10% from peak → halve risk; 15% → pause new entries and
  show a review screen.
- Stop always defined; to breakeven at +1R; book 50% at T1; trail rest by 2×ATR(14)
  on closing basis.
- Time stop: swing exits if not +1R within 15 trading days; positional review at 60.
- Pre-open job (08:30 IST): check every open position for stop, target, invalidation,
  results date and corporate actions; send me alerts.
- Include all Indian costs in backtests, R-multiples and P&L: brokerage, STT (0.1% each
  side on delivery), exchange charges, SEBI fee, stamp duty, GST, DP charges, and
  slippage by liquidity bucket. Show an estimated post-tax view (STCG vs LTCG).

### 6. Backtesting engine (the decision-maker)

- Event-driven daily-bar engine: signal on close, fill next open (or at the entry zone
  if touched next day); gaps and circuit days handled realistically.
- Point-in-time universe (with delisted stocks) and fundamentals.
- Walk-forward over ≥ 8 years where data exists; report **only out-of-sample**
  results. Hold out the latest 12 months as a final untouched test.
- Overfitting guards: few tunable parameters, log every variant tried, apply a
  multiple-testing correction (e.g. deflated Sharpe) when choosing.
- A strategy is "live-eligible" only if, out-of-sample and after costs: expectancy
  > 0.15R, profit factor ≥ 1.3, max drawdown ≤ 20%, ≥ 100 trades, positive in at least
  2 of 3 regimes (bull, bear, sideways), and better risk-adjusted return than
  buy-and-hold Nifty 500. Win rate is reported, not gated.
- Report card per strategy: equity curve, drawdown, trades table, stats by year and
  regime, rules in plain language.
- Weekly revalidation; auto-retire a strategy whose rolling 50-trade expectancy < 0 or
  whose drawdown exceeds 1.5× its backtest max; tell me.

### 7. Proving it works with my money (the path to "profitable")

Each stage has a gate; Jeron shows which stage each strategy is in.
1. **Backtest:** passes section 6.
2. **Paper trading:** every signal auto paper-traded with the same rules for at least
   3 months and 30 trades. Gate: live expectancy within the backtest's expected range
   and > 0 after costs.
3. **Small real money:** I trade it with ~10–20% of intended capital for 3 months.
   Gate: my real results (from the journal) match paper within reason.
4. **Full capital:** only after stage 3 passes.

A dashboard compares backtest vs paper vs my real results side by side, per strategy.
If they diverge, it flags the likely cause (slippage, skipped signals, late entries).

### 8. Journal and analytics

- Auto-log every signal: taken, skipped, modified. I enter fills, or import my broker's
  tradebook CSV (Zerodha format first).
- Per setup: win rate, average R, expectancy, profit factor, holding time, drawdown,
  "followed the plan" vs "deviated".
- Weekly summary: my real edge, my mistakes (moved stop, early exit, skipped winners),
  and what strict rule-following would have made.

### 9. Interface

**Web app (Next.js + TypeScript + Tailwind), works well on my phone (responsive +
installable PWA):**
- Dashboard: today's signals, open positions with live R-multiple, portfolio heat,
  regime banner, results dates for held stocks, data-quality status.
- Stock page: candlestick chart (TradingView Lightweight Charts) with entry/stop/target
  overlays, three-brains card, fundamentals, news/event timeline, results countdown,
  the strategy that fired and its report card.
- Screener, Strategy Lab, Journal, Data spot-check page, Settings (capital, risk %,
  tiers, alerts).
- Single-user login (password + TOTP), since it holds my broker token and positions.

**Alerts:** Telegram bot first (instant, free, works on phone), email as backup.

No native mobile app for now. The PWA + Telegram covers phone use; a native app is a
"going public" decision.

### 10. Tech stack (kept small for one user)

- Backend: Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic.
- Storage: PostgreSQL (add TimescaleDB only if queries get slow). DuckDB/Parquet is
  fine for backtest research data.
- Analytics: pandas/NumPy, TA-Lib (or pandas-ta if install is a problem).
- Jobs: APScheduler: EOD scan after 18:30 IST, pre-open checks 08:30 IST, weekly
  revalidation. Idempotent jobs using the NSE holiday calendar.
- LLM: a hosted LLM API behind an interface, JSON output, caching, and a monthly cost
  cap I set.
- Run: Docker Compose on my laptop first; later a small cloud VM in Mumbai. GitHub
  Actions CI for lint, type-check and tests. Nightly database backup.

### 11. Milestones (each ends with a demo and acceptance checks)

- **M0 Foundations:** repo layout (`backend/`, `web/`), Docker Compose, CI,
  `CLAUDE.md`, DB schema, NSE trading calendar, `DataProvider` interface.
  *Accept:* `docker compose up` works; CI green.
- **M1 Data you can trust:** bhavcopy history ingestion (≥ 8 years), corporate-action
  adjustment, second-source cross-check, data-quality report, spot-check page.
  *Accept:* I spot-check 20 stock-dates against my broker and they match.
- **M2 Indicators + scanner:** indicators, universe filters, technical score, daily
  scan.
  *Accept:* indicators match a reference within tolerance; scan < 5 minutes.
- **M3 Backtester:** engine, Indian costs, walk-forward, report cards, golden tests,
  first 2–3 strategies evaluated honestly.
  *Accept:* reproducible; at least one strategy passes section 6, or a written report
  on why none does.
- **M4 Signals + risk manager + paper trading:** schema, sizing, portfolio rules,
  automatic paper trading.
  *Accept:* every section 5 rule has a test; paper trades update daily.
- **M5 Web app + Telegram alerts:** dashboard, stock page, journal basics.
  *Accept:* scan → signal → Telegram alert → journal works end to end.
- **M6 Fundamentals + news brain:** point-in-time fundamentals, results calendar, LLM
  news labels with my test set; re-backtest with all three brains.
- **M7 Exit engine + analytics:** pre-open checks, trailing and time stops, broker
  tradebook import, backtest-vs-paper-vs-real dashboard, weekly summary.

### 12. Ground rules

- No signal without a backtested strategy behind it. The backtester decides, not
  opinion.
- Fewer, higher-conviction signals beat many. Capital protection beats opportunity.
- Out-of-sample, after-cost numbers only.
- Show losers as clearly as winners. Don't hide bad results from me.
- If data is missing or stale, say so and publish nothing rather than guess.
- No automatic order placement. I place every order myself.

### 13. Later, only if going public (don't build now)

Multi-user accounts, payments (Razorpay), native mobile app, public track record,
licensed data vendor with redistribution rights, and SEBI Research Analyst
registration before offering stock calls to others. The full public-business plan
is kept in the project files (`jeron-build-prompt-v2-public.md`).
