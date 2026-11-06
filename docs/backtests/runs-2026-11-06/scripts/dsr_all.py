# Deflated Sharpe of every stored run against every variant tried (each strategy's whole
# grid, quality-trend excluded as in 2026-11-01). Run from backend/ with
# JERON_DATABASE_URL set: PYTHONPATH=. uv run python ../docs/backtests/runs-2026-11-06/scripts/dsr_all.py
import os, sys
import numpy as np
import psycopg

sys.path.insert(0, ".")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.backtest.job import load_inputs, missing_inputs
from app.backtest.market import build_market
from app.backtest.strategies import STRATEGIES
from app.backtest.walkforward import all_trial_sharpes
from app.backtest.stats import deflated_sharpe, daily_returns, daily_rate

url = os.environ["JERON_DATABASE_URL"]
with Session(create_engine(url)) as s:
    m = build_market(load_inputs(s, None, None))
use = [st for st in STRATEGIES.values() if not missing_inputs(m, st) and st.key != "quality-trend"]
print("strategies counted:", [st.key for st in use], flush=True)
trials = all_trial_sharpes(m, use)
print("trials:", len(trials), flush=True)

c = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))
for id_, v, eq, ho in c.execute(
    "select id, strategy_version, equity, holdout_start from backtest_runs order by id"
).fetchall():
    curve = np.array([p["equity"] for p in eq if p["date"] < ho.isoformat()])
    excess = daily_returns(curve) - daily_rate(6.5)
    print(f"run {id_} {v}: deflated Sharpe vs all {len(trials)} trials:",
          round(deflated_sharpe(excess, trials), 4), flush=True)
