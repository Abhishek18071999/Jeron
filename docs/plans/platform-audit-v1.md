# Platform audit v1 (2026-10-25)

An audit of `main` at `c2c8019` (PR #34 merged) against the owner's "trading intelligence
platform" brief of 2026-10-25, then the slices built on this branch. The spec
(`docs/spec.md`) stays binding where the brief and the spec differ; the differences are
listed at the end.

## What ran

- Backend: `uv run pytest -q` with a local PostgreSQL 16 (`JERON_TEST_DATABASE_URL` set):
  **556 passed** before any change. `ruff check`, `ruff format --check` and `mypy app`
  clean.
- Web: `npm ci`, `npm run lint`, `npm run typecheck`, `npm run build` all pass.
- Not run here: `docker compose up` (no Docker in the build container), and anything
  needing nseindia.com or the owner's database (blocked from the cloud container). The
  screens were not opened in a browser in this audit; they were audited from code.

## Audit by brief section

Legend: **done** (built and tested), **partial**, **missing**, **won't build** (spec
decision).

| # | Brief section | State | Evidence and gaps |
|---|---|---|---|
| 1 | Audit | done | This file. |
| 2 | Market data foundation | done, one gap | NSE bhavcopy is the source of truth, Yahoo cross-check (0.5%), raw prices kept and adjusted on read, symbol changes, delisted stocks, point-in-time Nifty 500, NSE calendar to 2026 with a missing-year warning, `Fetcher` with pacing and retries, `DataProvider` protocol, quality report (missing days, zero volume, moves without actions, stale prices, check #9). **Gap:** when the day's bhavcopy does not arrive (NSE late or down) the daily job logs it and exits, and nothing reaches the owner; the summary silently doesn't come. US markets: out of scope (spec: NSE cash only). Live/delayed labels: everything is end-of-day and the UI says "data as of". |
| 3 | Opportunity engine | done | Scan with versioned score, 11 versioned strategies, signals with every spec section 4 field (entry zone, stop and why, T1/T2, R:R after costs, invalidation, event risk, backtest stats, data_as_of), "no trade" when the gates fail or the market mood is defend. The score is labelled a score, never a probability. |
| 4 | AI research assistant | partial | The LLM labels announcements only (spec section 3). There is no question-answering assistant. A grounded one is possible if it only narrates numbers Jeron computed; see "Not built". |
| 5 | Backtesting lab | done, metric gaps | Daily-bar engine with golden trades, Indian costs and slippage buckets, gap and circuit handling, price-band exclusion, point-in-time universe, walk-forward, untouched 12-month holdout, logged variants, deflated Sharpe, section 6 gates, Nifty 500 and cash-sweep lines, by year and regime, tax view. **Gaps:** no Sortino, no losing streak, no longest drawdown or recovery time, no exposure, turnover or trades per year in the report. |
| 6 | Risk engine | partial | The engine (backtest and paper) has every section 5 rule. **Gaps in the real-money trade plan** (`app/plan/calc.py`), which is what the owner uses before a real buy: the drawdown brake (spec section 5: 10% halve, 15% pause) is not applied to the real account; the max open positions per tier (a setting) is not checked; there is no daily or weekly loss limit and no cap on new entries a week (brief section 6). |
| 7 | Portfolio | done | Holdings from the journal, open risk, heat, give-back, sector exposure, idle cash, tax notes and the LTCG exemption. Marked as journal positions, never as broker balances. Benchmark-relative real returns: not built (needs a dated equity history of the real account). |
| 8 | Scanner and watchlist | done | Daily scan, ranked list by industry, heatmap, watchlist with price alerts, scan history, blocked runs say why. Custom user-defined filters: not built (low value at one user). |
| 9 | Alerts | done, one gap | Telegram + email, one row per key so re-runs never resend, attempts and error stored (delivery log), buttons. **Gap:** no alert for a data outage (see 2). |
| 10 | Journal and coach | partial | Taken/skipped/modified, followed vs deviated, per-strategy stats, weekly mistakes (moved stop, early exit, late entry, skipped winners). **Gap:** per-strategy stats give an average R from 3 trades with no warning and no uncertainty range. |
| 11 | Paper trading | done (by replay) | Paper accounts replay the engine daily (decision 0006), so paper fills follow the same rules as the backtest; signals stored once. A manual paper order book with order states was not built: see "Not built". |
| 12 | News and fundamentals | done | NSE announcements, LLM labels with model and prompt version, test-set accuracy, results calendar and blackout, quarterly results (CSV + XBRL) keyed by filing date, fund-v1 score. RSS feeds and balance-sheet data are listed in `remaining-work` C5. |
| 13 | UX | done | Today briefing, Trade sections, stock page with Lightweight Charts, command palette, phone tab bar, light/dark via tokens, empty states with the command that fills them, PWA. |
| 14 | Speed and reliability | done | Scheduler with catch-up, market lock, autopilot, nightly `pg_dump`, health check. |
| 15 | Security | partial | Web: scrypt password + TOTP, signed session cookie, lockout after 5 failures, every route guarded, browser never calls the API. Secrets only in `.env`. **Gap:** the backend API has no authentication at all. It listens on 127.0.0.1 only, but any local process, and any web page through DNS rebinding (a hostile site whose name resolves to 127.0.0.1), can read the portfolio or write journal entries, settings and imports. |
| 16 | Code quality | done | Pure calc modules beside database services, strict mypy, ruff, decisions log. |
| 17 | Tests | done, gaps | 556 backend tests including golden trades, risk rules, TA-Lib reference, look-ahead tests. No web tests; no API authentication tests (there is no API authentication). |
| 18-20 | Order, method, done | | This plan and the PR report. |

## Ranked plan (built on this branch, in this order)

Ranked by risk reduction and decision quality for real money, then effort.

1. **API authentication (security).** A shared token between web and backend
   (`JERON_API_TOKEN`), and a Host check against DNS rebinding. Tests for both.
2. **Data outage alert (data and alerts).** When the daily job finds no new session for
   a trading day, send one "today's data has not arrived" alert (stored once by key) and
   say what was last loaded.
3. **Real-account guardrails (risk).** In the trade plan: the spec's drawdown brake on
   the real account, max open positions per tier, daily and weekly realised loss limits
   and a weekly cap on new entries (new settings, editable on Settings). Each in
   `tests/test_risk_rules.py`.
4. **Backtest report metrics.** Sortino, longest losing streak, longest drawdown and
   recovery, exposure, trades a year and turnover, as pure functions with hand-worked
   tests, on the report card.
5. **Journal sample-size honesty.** A minimum-sample warning and a 95% interval on the
   average R per strategy in the journal stats.

## Status (2026-10-25)

All five slices are built on `claude/project-thread-2ydnzm`.

| Slice | Built | Tests (all run here) |
|---|---|---|
| 1. API token + Host check | `app/api/security.py`, `apiHeaders()` in the web app, `api-token` command, Setup step, CI smoke step | `tests/test_api_security.py` (7, one walks every route in the OpenAPI schema); the CI compose job checks 401 / 200 / 400 against the real stack |
| 2. Data outage alert + retry | `app/alerts/late.py`, `daily-retry` job, `due_session()` | `test_late_data_is_told_once`, `test_data_on_time_sends_nothing`, `test_due_session`, `test_retry_only_when_the_scan_is_missing` |
| 3. Real-account guardrails | `guardrails()` in the plan, `account_state()`, 4 settings, Portfolio card | 7 rows added to `tests/test_risk_rules.py`; plan and portfolio DB tests extended |
| 4. Backtest risk profile | `risk_profile()` in `stats.py`, stored per run, report card table | `tests/test_backtest_stats.py` (4, hand-worked numbers) |
| 5. Journal sample size | 95% range of the average R, notes under 30 trades, weekly line | `tests/test_journal_sample.py` (4, hand-worked numbers) |

Backend: 582 passed (556 before), ruff and mypy clean. Web: lint, typecheck and build
pass. The Portfolio, Journal, Setup and Settings pages were opened in Chromium against a
local backend with the token on (desktop and phone width) and showed the new parts with
a test journal entry; the backtest report's new table was not seen with real data (no
run in the local database). Docker Compose was not run here; CI runs it.

No migration: the new settings live in `setting_changes` like the others, and the new
report numbers are inside each run's stored summary.

## Not built, and why

- **Live order placement / broker execution.** Spec section 12: "No automatic order
  placement. I place every order myself." Changing that needs the owner's explicit
  approval and a chosen broker (remaining-work A5, C5).
- **A free-form AI chat that answers trading questions.** Spec section 3 and
  remaining-work E: the LLM never produces prices, targets or stops, and an LLM choosing
  trades was decided against. A narrow "explain this stock" that only re-words Jeron's
  own computed facts, with sources, is compatible; it is the best next slice once the
  owner confirms it (it spends LLM budget).
- **A manual paper order book (market/limit orders, partial fills, cancellations).**
  Paper trading by replay (decision 0006) already tests the rules without the owner's
  discretion, which is what the stage-2 gate needs. A sandbox order book is a separate
  practice feature; not built now.
- **US markets, intraday, multi-user.** Out of scope in the spec (intraday waits for a
  data source the owner approves, A5).

## Spec vs brief

The brief asks for live trading, an AI assistant and multi-user grade authorization. The
spec, which the owner wrote and which needs his approval to change, rules out automatic
orders and multi-user, and limits the LLM to labelling news. This branch follows the
spec and lists those items above for the owner to decide.
