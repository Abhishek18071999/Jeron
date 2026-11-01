import os, sys, numpy as np
sys.path.insert(0, ".")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.backtest.job import load_inputs, missing_inputs
from app.backtest.market import build_market
from app.backtest.strategies import STRATEGIES
from app.backtest.walkforward import all_trial_sharpes
from app.backtest.stats import deflated_sharpe, daily_returns, daily_rate, per_period_sharpe
import psycopg
eng = create_engine(os.environ["JERON_DATABASE_URL"])
with Session(eng) as s:
    m = build_market(load_inputs(s, None, None))
use = [st for st in STRATEGIES.values() if not missing_inputs(m, st) and st.key != "quality-trend"]
print("strategies counted:", [st.key for st in use], flush=True)
trials = all_trial_sharpes(m, use)
print("trials:", len(trials), flush=True)
c = psycopg.connect("postgresql://jeron:jeron@localhost/jeron")
for v in ("fip-momentum-v1", "momentum-v1", "rs-pullback-v1", "sector-rotation-v1", "results-drift-v1"):
    eq, ho = c.execute("select equity, holdout_start from backtest_runs where strategy_version=%s", (v,)).fetchone()
    curve = np.array([p["equity"] for p in eq if p["date"] < ho.isoformat()])
    excess = daily_returns(curve) - daily_rate(6.5)
    print(v, "deflated Sharpe vs all", len(trials), "trials:", round(deflated_sharpe(excess, trials), 4), flush=True)
