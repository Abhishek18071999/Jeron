# Runs of 2026-11-01

The backtest runs behind `docs/backtests/fip-momentum-v1-report.md`, taken from a fresh
install's `backtest_runs` table (runs 1 to 9).

- `runs.json`: every run's metadata and full `summary` (gates, out-of-sample and holdout
  stats, by year and regime, confidence/evidence, provenance).
- `equity.json`: every run's daily equity curve, with the Nifty 500 and cash-sweep lines.
- `scripts/`: what was run, in order.
  - `pipeline.sh`: backfill 2016-01-01 onwards, lists, events, quality, the bundled
    quarterly results import.
  - `bt.sh`: the backtests (runs 1 to 7, then the combined book, run 8); `qt.sh`:
    quality-trend-v1 (run 9) after the results import.
  - `summ.py`, `conf.py`, `sc.py`: read the stored summaries; `corr.py`: daily-return
    correlations; `dsr_all.py`: the deflated Sharpe against all 67 variants tried (run
    from `backend/` with `JERON_DATABASE_URL` set).

The shell scripts use `$REPO` (the repo root) and `$SCRATCH` (a folder for logs).

To reproduce: run `pipeline.sh` then `bt.sh` and `qt.sh` on a database at the same
point. Data fingerprint `5f61059ef5e24625` for runs 1 to 7; run 8 `b72fc0656fd7d915`
and run 9 `1c81edd0691af56a` were taken while and after the quarterly results loaded.
The raw NSE data itself is not in this repository (see the report).
