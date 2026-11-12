# Prompt: check that every strategy is working on this install's data

Paste the text below into Claude Code, opened in this repository on the computer that
runs Jeron (Docker Compose up). It only reads and reports; it changes nothing.

```
Check that every strategy in this Jeron install is working correctly on its data, and
report what you find. Read CLAUDE.md first. Do not change any code, setting, strategy
status or stored row, do not tune or add strategies, and do not start paper accounts by
hand. Run commands as `docker compose exec backend python -m app.cli <command>`; use
the API (with the token from `api-token`) only to read.

1. Data. Read GET /setup and say what is done, running, or waiting on me. Count the
   quality reports by PASS, WARN and FAIL for the last 60 sessions and list any FAIL
   with its reason. Give the last session with prices, the newest quarter in
   financial_results, the last board-meeting date and the last labelled announcement.
   Flag anything stale: prices older than the last trading day, results whose newest
   quarter ended more than 200 days ago, a holiday calendar missing next year.

2. Inputs per strategy. For each key in app/backtest/strategies.py STRATEGIES, say
   which inputs it needs (prices only, results calendar, quarterly results, news
   labels) and whether this install has them up to date. If quarterly results stop at
   December 2024, say that `fundamentals-fetch --start 2025-03-31` is needed and do not
   run it without asking me (it takes about three hours).

3. Backtests. Run `backtest` with no strategy named. List every strategy as ran or
   skipped, with the reason for each skip. For those that ran, give trades, expectancy,
   profit factor, drawdown, Sharpe, the holdout, how many of the seven checks passed and
   the evidence rating, and compare each with its report in docs/backtests/. Call out
   any number that differs from the report by more than a fifth.

4. Paper trading. Read GET /paper/coverage. Every strategy must appear. List the ones
   with no active account and the reason given. For each active account give its
   start date, last updated date, open positions, closed trades and expectancy, and
   flag any account not updated to the last trading day or with no signal in 30
   sessions. Read `strategy-status` and the Strategy health labels and report any
   version marked deteriorating.

5. The daily run. Say whether the last trading day has a scan, a paper update and a
   sent daily summary, and whether the watchdog alerted in the last 30 days.

Finish with one table, a row per strategy: inputs ok, backtested, paper account,
healthy, and the one thing to do next if any column is not ok. Then list, in order,
the commands I should run, and stop. Say plainly where you could not check something.
```
