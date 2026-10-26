# Jeron: notes for coding agents

Read `docs/spec.md` first. It is the brief, including how to work (section 0):
plan each milestone in `docs/plans/M<n>.md`, one branch and PR per milestone, tests
are part of done, never commit secrets.

## Layout

- `backend/` Python 3.12, FastAPI, SQLAlchemy 2, Alembic, managed with `uv`.
  - `app/models.py` schema. Prices are stored raw per source; adjusted series are
    derived. Point-in-time tables (index membership, delisting dates) are never
    overwritten.
  - `app/data/provider.py` the `DataProvider` protocol every data source implements.
  - `app/data/` market data: `nse.py` (bhavcopy + PR bundle), `nse_lists.py` (index
    closes, security list, Nifty 500 list, symbol changes), `yahoo.py` (second
    source), `adjust.py` (corporate-action factors), `crosscheck.py`, `quality.py`
    (check #9 holds a stock that fell over 15% with no split or bonus: its signals are
    sent HELD and its exits go to CHECK BY HAND),
    `search.py` (stock search: names, initials, old symbols, short names in
    `stock_aliases.csv`), `events.py` (board meetings from the PR bundle's `bm` file,
    results blackout, event risk), `news.py` (company announcements from the `an` file),
    `deals.py` (bulk and block deals, insider trades; stock page information, not a signal,
    see `docs/decisions/0011`),
    `store.py` (database access), `pipeline.py` (jobs). Pure modules have no database
    imports; domain enums live in `app/enums.py` for that reason.
  - `app/indicators.py` indicators (pure functions, checked against TA-Lib in
    `tests/test_indicators_reference.py`; TA-Lib is a dev dependency only).
  - `app/scan/` the daily scan: `universe.py` (rules), `score.py` (technical score,
    versioned as `SCORE_VERSION`), `job.py` (database job). Changing points or rules
    means a new score version.
  - `app/backtest/` the backtester: `market.py` (aligned arrays, the scan's universe
    and score for every day), `features.py`, `engine.py` (daily-bar simulation),
    `costs.py` (Indian charges, slippage, tax estimate), `strategies.py` (versioned; the `-events` versions add M6's results blackout and news
    filter; `trend-breakout` and `rs-pullback` are the v2 research, see
    `docs/backtests/strategies-v2-report.md`; `results-drift` and `sector-rotation` are
    the v3 research, both research only, see `docs/backtests/strategies-v3-report.md`;
    their inputs, the results reaction and the measured sector, are built in `market.py`;
    `COMBINED_BOOK` trades rs-pullback-v1 and results-drift-v1 in one account through
    the engine's `Book`s, run only by `backtest --strategy combined-book`, see
    `docs/plans/combined-book-v1.md`; `momentum-v1` (invest tier, monthly 12-1 momentum
    leaders on `Market.mom_rank`, pre-registered in `docs/plans/momentum-v1.md`),
    `walkforward.py` (folds, holdout, gates), `stats.py` (also the Nifty 500 cash-sweep
    line reported beside the gates, M8 part 2, and `risk_profile`: Sortino, streaks, time
    under water, exposure, turnover; reporting only), `job.py` (database). A strategy may set
    `single_regime` (Gate 5 judged in its own regimes) only if registered from 2026-10-18.
    Changing a strategy's rules means a new strategy version; runs are never
    overwritten. The engine is also the risk manager (spec section 5); the sector cap,
    correlation check and position-limit override are opt-in `PortfolioRules`, used by
    paper trading only.
  - `app/news/` the news brain: `labels.py` (subject rules, the LLM's JSON schema and
    prompt, news score, test-set accuracy; pure), `claude.py` (Anthropic API labeller,
    batches; tests use a fake client, never the API), `deepseek.py` (DeepSeek's chat API in
    JSON mode) `ollama.py` (Ollama Cloud) and `gemini.py`
    (Gemini's OpenAI-compatible API), the alternative labellers, and `job.py` (database). Labels are
    stored once per model and `PROMPT_VERSION`; changing the prompt means a new version.
  - `app/fundamentals/` the fundamental brain (decision 0013): `score.py` (TTM, growth,
    P/E against own history, `FUND_SCORE_VERSION`; pure) and `job.py` (load filings from
    NSE's Financial Results CSVs and XBRL, point-in-time `quarters_known`, the stock page).
    `app/data/fundamentals.py` parses the CSV and the XBRL (pure).
  - `app/signals/` the spec section 4 signal: `schema.py` (Pydantic, every field
    required) and `build.py` (engine order -> signal).
  - `app/paper/job.py` paper trading: one account per strategy version, replayed by the
    engine each day; new orders become signals, stored once and never changed. Signals of
    strategies that failed section 6 are research only. See `docs/decisions/0006`.
  - `app/alerts/` alerts: `format.py` (signal message, daily summary; pure),
    `channels.py` (Telegram Bot API, SMTP email backup), `job.py` (what is due; every
    alert stored once in `alerts`, so re-runs never send twice), `buttons.py` (the
    signal alert's Telegram buttons; pure) and `bot.py` (reads the presses every minute:
    skip with a reason, "I bought it" and the fill typed back; each update stored once in
    `bot_updates`; `docs/plans/ui-v2.md`). Research-only signals
    are only in the summary unless `JERON_ALERT_RESEARCH_SIGNALS` is on.
  - `app/journal/` the journal: `calc.py` (positions from fills, stats with a 95% range
    of the average R and a note under 30 closed trades; pure) and
    `service.py` (database). Every signal without an entry is pending. `tradebook.py`
    reads Zerodha's tradebook CSV (pure); `importer.py` turns it into fills, stored with
    the broker's trade id so a re-import adds nothing.
  - `app/exits/` exits for my real positions: `rules.py` (the engine's section 5 exit
    rules on one position; pure, checked against the engine) and `job.py` (the pre-open
    check: action per open position, results and ex-dates ahead, stale-data guard;
    `broker_stop`, the GTT stop to keep at the broker, flagged when the last close raised it).
  - `app/analytics/` `compare.py` (backtest vs paper vs real: gates, expected ranges,
    stages, causes of divergence, the 20-trade early warning; pure), `service.py` (database) and `weekly.py` (weekly
    summary and revalidation, which retires failing strategies' paper accounts).
  - `app/sections/` the four sections (swing, intraday, positional, long-term;
    `docs/plans/sections-v1.md`, decision 0014): `calc.py` (what each holds, its state,
    a signal as what/when/how much/why; pure) and `service.py`. Served at `/sections`.
    Long-term is the invest tier (`Tier.INVEST`, wider target and trail in `TIERS`) with
    `quality-trend-v1`, the first strategy on `Market.fund_score` (point-in-time fund-v1)
    and the first with its own exit rule. Intraday is "not running": no intraday data.
  - `app/explain/` explain a stock (decision 0016, `docs/plans/explain-v1.md`):
    `facts.py` (every line a fact with source, date and kind; the brief: why in the scan,
    for, against, what cancels, level scenarios, checklist, unknowns, the setup check;
    pure, no LLM), `narrate.py` (the optional LLM wording: prompt `explain-v1`, the
    checks that every number is in the cited facts and nothing reads as advice or a
    forecast; pure), `writers.py` (the news provider's transport; tests use a fake) and
    `service.py` (database; narrations stored in `explanations`, spend in `llm_usage` as
    `explain:<model>` against the news cap). Served at `/stocks/{symbol}/explain`,
    `/stocks/{symbol}/explain/narrate` and `/stocks/compare`.
  - `app/market/` the market mood (decision 0009): `mood.py` (breadth above the 200-day
    EMA, 52-week highs/lows, the engine's regime filter, attack/normal/defend, sector
    strength; pure) and `service.py` (database). Served at `/market/mood`.
  - `app/portfolio/` my real portfolio: `calc.py` (open risk, heat, give-back, sector
    exposure vs settings, idle cash to park in a liquid fund or, with
    `JERON_IDLE_CASH_IN_INDEX`, an index fund; tax timing notes with the rupee tax of selling
    now vs after the 12-month mark; the financial year's ₹1.25 lakh long-term exemption used,
    from journal sales matched first in, first out; `account_state`: equity, peak and
    drawdown, realised today and this week, entries this week; pure), `equity.py` (the
    account's daily equity from the journal against the Nifty 500; its peak is the
    guardrails' peak; pure) and `service.py` (journal positions + the pre-open exit plan).
    Served at `/portfolio` (with `account`, the Guardrails card) and `/portfolio/equity`.
  - `app/plan/` trade plans (decision 0010): `calc.py` (the engine's `position_size` and
    `reward_risk`, spec section 4 checks, heat and sector after the buy, the 5-item
    checklist, the small-trade warning when fixed charges pass 0.1R
    (`costs.small_trade_warning`, also on signal alerts and Trade cards); the real
    account's guardrails (`guardrails`: spec section 5's drawdown brake and max positions
    per tier, always hard; daily/weekly realised loss limits and a weekly entries cap from
    settings, hard unless `JERON_RISK_LIMITS_BLOCK` is off; decision 0015); pure) and
    `service.py` (database). `GET /plan/{symbol}`, `POST /plans`;
    plans are never changed (a new one supersedes), journal entries carry `plan_id`.
  - `app/watchlist/` `calc.py` (alert hits, alert keys; pure) and `service.py`; served at
    `/watchlist`. The alerts job sends one alert per item and price (`watch:` keys).
  - `app/settings_store.py` settings changed on the Settings page (`setting_changes`,
    latest per key wins over `.env`); risk code reads `effective_settings(session)`, not
    `get_settings()`. `app/auth.py` makes the web login's scrypt hash and TOTP secret
    (`auth-setup`). The news labeller records spend in `llm_usage` and stops at the
    monthly cap (decision 0012).
  - `app/scheduler.py` APScheduler: `preopen` 08:30 IST, `daily` 19:00 IST on trading
    days, `daily-retry` 21:30 IST (only when the session has no scan yet), `weekly` after
    the last session of the week; `catch_up` on start runs what was
    missed while the computer was off; the autopilot every minute. Runs as the
    `scheduler` service.
  - `app/autopilot.py` sets an install up without commands (`docs/plans/autopilot-v1.md`):
    history, the first daily run, announcements from stored PR bundles, the news
    backlog, a backtest of every untested strategy version, then `paper` (the market
    lane, shared with the scheduler's jobs through `market_lock`); and imports files
    dropped in `imports/` or uploaded (`PUT /imports/{name}`), recognised by their
    columns, filed under `imports/done` or `imports/failed` with a log. Queues
    `backend/seed/nse-results-2016-2026.zip` once when no results are loaded. Each step
    is a CLI command in its own process. `GET /setup` (`app/api/setup.py`) says what is
    done, running, or needs the owner.
  - `app/api/` routes; `security.py` (the Host check against DNS rebinding and the
    `JERON_API_TOKEN` bearer token on every route but `/health`; the web app sends it,
    `web/src/lib/api.ts` `apiHeaders`; `tests/test_api_security.py` walks every route);
    `market.py` serves `/market/mood`, `portfolio.py` `/portfolio`;
    `analytics.py` serves `/analytics/compare` and `/analytics/weekly`;
    `stocks.py` `/stocks/ranked` (the latest scan, by industry), `plan.py`, `watchlist.py`;
    `deals.py` `/stocks/{symbol}/deals`; `news.py` `/stocks/{symbol}/news` and `/news/latest`
    (subject-rule labels on read when no LLM label); `fundamentals.py` `/stocks/{symbol}/fundamentals`;
    `dashboard.py` serves `/dashboard`, `/stocks/search` (symbol or
    company name, for the search box), `/stocks/{symbol}`, `/alerts`.
  - `app/cli.py` jobs: `backfill`, `lists`, `crosscheck`, `quality`, `scan`,
    `asm-import`, `daily`, `holidays`, `backtest`, `paper`, `alerts`, `telegram`,
    `events` (board-meeting and announcement history from the PR bundles),
    `events-import` (a board-meeting CSV saved from nseindia.com), `deals` (the day's bulk and
    block deals; `daily` runs it too), `deals-import FILE` (bulk/block deals or insider
    trades saved from nseindia.com), `api-token` (the web app's token for the API),
    `fundamentals-import FILE...` (quarterly results from
    Financial Results CSVs saved from nseindia.com), `news-label`,
    `news-testset`, `news-eval` (news labels, see `app/news/`), `preopen`, `weekly`,
    `tradebook FILE`, `auth-setup` (the web login's secrets).
  - `app/calendar/` NSE trading calendar; holidays live in `nse_holidays.csv`. From
    November, a missing next year is warned on `/setup` and in the pre-open check, and
    `tests/test_calendar.py` fails from 1 January of a year not in the file.
  - `alembic/versions/` migrations. Generate with autogenerate, then review.
- `backup/backup.sh` the nightly `pg_dump` run by the `backup` service; a dump is kept only if
  `pg_restore` reads it, and once a week (`backup.sh verify`) the newest is restored into a
  scratch database, the result in `restore-check.txt`. `backend/app/backups.py` reads that
  folder (`JERON_BACKUPS_MOUNT`) for Setup and the pre-open check (`docs/plans/hardening-v1.md`).
- `web/` Next.js 16 (App Router, TypeScript, Tailwind 4). Navigation: Today (`/`),
  Trade (`/trade`, one tab per section: `/trade/swing`, `/trade/intraday`,
  `/trade/positional`, `/trade/invest`; `src/components/sections.tsx`), Stocks (sector
  heatmap and ranked list; `/watchlist` and `/plan/[symbol]` sit under it), Portfolio, Journal, Research (`/research` hub for scanner, backtests, paper,
  compare, data, spot check, setup), Learn (`/learn`, lessons in `src/lib/learn/`, one
  file per track, assembled in `src/lib/lessons.ts`; their Jeron numbers mirror the backend;
  `/learn/glossary`); `/stocks/compare` puts up to three stocks' briefs side by side (picked with the same
  search box, `src/app/stocks/compare/picker.tsx`; rows, leads and differences in
  `src/lib/compare.ts`; `docs/plans/compare-v2.md`); `src/lib/strategy-guide.ts` says how
  to use each strategy's signal (mirrors `strategies.py`, shown on Compare and the stock
  page, `src/components/strategy-guide.tsx`), and
  every stock page has the "Explain this stock" card (`src/app/stocks/[symbol]/brief.tsx`);
  phones get a bottom tab bar (`src/components/nav.tsx`).
  `/setup` shows the autopilot and takes uploads (`src/app/setup/actions.ts`).
  Ctrl+K opens the command palette (`src/components/command-palette.tsx`); the trade
  plan form recalculates through the read-only `/api/plan` route handler.
  Login (password + TOTP, decision 0012): `src/proxy.ts` guards every route,
  `src/lib/auth.ts`, `src/app/login/`; `/settings` changes risk and alert settings.
  Today opens with the morning briefing (`src/lib/briefing.ts`, ticks in
  `src/components/briefing.tsx`); `src/components/trade-picture.tsx` is the R ruler;
  `src/components/explain.tsx` the tap-to-explain sheet and the copyable command (hidden
  on phones). `Table stack` turns rows into cards on phones (`docs/plans/ui-v2.md`).
  Colours are tokens in `src/app/globals.css` (`text-muted`, `border-line`, `text-good`,
  `text-bad`, `bg-accent`...); shared parts in `src/components/ui.tsx` (Card, Stat, Badge,
  Button, Table, EmptyState with the command that fills it). Server components call the
  backend at `JERON_API_URL`; journal writes go through server actions
  (`src/app/journal/actions.ts`), so the browser never calls the API. The stock chart
  uses TradingView Lightweight Charts (client component). Installable PWA
  (`src/app/manifest.ts`).

## Commands

Backend (from `backend/`):
- `uv sync` install
- `uv run pytest -q` tests; database tests run when `JERON_TEST_DATABASE_URL` is set
  (e.g. `postgresql+psycopg://jeron:jeron@localhost:5432/jeron_test`)
- `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
- `uv run alembic revision --autogenerate -m "..."`, `uv run alembic upgrade head`
- `uv run uvicorn app.main:app --reload` (needs `JERON_DATABASE_URL`)

Web (from `web/`):
- `npm ci`, `npm run dev`, `npm run lint`, `npm run typecheck`, `npm test` (Node's test
  runner on `src/lib/*.test.ts`), `npm run build`

Everything: `docker compose up --build` from the repo root.

## Conventions

- Money and prices are `Decimal` / `Numeric`, never float, in stored data.
- Times are IST for market logic; store timestamps with time zone.
- Raw prices are never changed. Adjusted prices are computed on read from NSE
  corporate actions (`source = "nse"`); see `docs/decisions/0003`.
- Indicators run on split/bonus-adjusted prices; the scan refuses to run (and stores a
  blocked run saying why) when the day's quality report FAILs or inputs are missing.
- NSE's archive answers bursts with 403 "Access Denied"; keep requests at about one
  per second and retry (the `Fetcher` does this).
- Backtests report out-of-sample, after-cost numbers only; `tests/test_backtest_engine.py`
  holds golden trades. Keep them passing when touching the engine. `engine-v3` (M8)
  skips a buy that opens above the entry zone and stocks in a 2% or 5% price band;
  paper accounts opened earlier keep `engine-v2`'s rules (`zone_touch_fill`).
- Settings come from env vars prefixed `JERON_` (`app/config.py`), including the risk
  settings (capital, risk %, position limits, sector cap) and the alert secrets (Telegram
  token, SMTP password), which live only in `.env`. Every spec section 5 rule has
  a test listed in `tests/test_risk_rules.py`.
- Every API route needs the API token when `JERON_API_TOKEN` is set (`app/api/security.py`);
  `/health` is the only open path. Server-side web code calls the backend through
  `apiHeaders()`, never a bare `fetch`.
- The trade plan is where the real account's risk rules live: a new limit goes in
  `app/plan/calc.py` `guardrails` with a row in `tests/test_risk_rules.py`.
- CI (`.github/workflows/ci.yml`) runs backend checks, web checks, a dependency audit
  (`pip-audit`, `npm audit`), and a Docker Compose
  smoke test. Keep it green.
