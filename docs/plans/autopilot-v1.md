# Autopilot v1: Jeron sets itself up

Asked: "make everything work; if something is required, do it yourself". On a fresh
evening the owner hit four walls: file imports failed because the container can't see
files on the PC, no news showed anywhere, strategies needing missing data stopped the
whole `backtest` run, and every empty screen said to run a command.

## What changes

- **Autopilot** (`backend/app/autopilot.py`), run by the scheduler on start and every
  minute. Market lane, one step per tick, under the lock the scheduler's jobs also take:
  1. no prices: `backfill` (from 2016);
  2. no scan yet: `daily`;
  3. PR bundles stored whose announcements were never read: `events` for that span
     (from the cache; each span once);
  4. a news key is set: `news-label --start <30 days ago>`, once a day;
  5. a strategy version with no backtest run (or quality-trend after new results, once
     the imports queue is empty): `backtest --strategy ...`, each set of inputs once;
  6. after new backtests: `paper`.
  Imports lane: every `.csv`, `.json` or `.zip` in `imports/` (bind-mounted at
  `/imports`, or uploaded on the Setup page) is recognised by its columns and imported
  with its CLI command, then moved to `done/` or `failed/` with its output. When no
  results are loaded, the bundled 2016-2024 results lists (`backend/seed/`, the CSVs the
  owner already downloaded) are queued once. An import stopped by a restart is queued
  again.
- `run_backtests` skips a strategy whose inputs aren't loaded and says which, instead of
  raising.
- Announcements and board meetings are stored independently from a PR bundle (one bad
  file no longer loses the other).
- **News is shown**: stock page and Today, with the free subject label when no LLM key is
  set (`/stocks/{symbol}/news`, `/news/latest`).
- **Setup page** (`/setup`): each part's state (done, working, starts by itself, needs
  you), what the autopilot is doing with its log, uploads, and each strategy's backtest
  and paper state. Today shows a banner until setup is done.
- **Learn** (`/learn`): lessons on basics, technicals, fundamentals, every strategy and
  process, with worked examples and short quizzes.

## Still the owner's

API keys and the Telegram token live in `.env` (secrets never go through the web app),
and NSE's Financial Results list for quarters after December 2024 has to be saved from
nseindia.com, which blocks automated downloads; the Setup page says how for each.
