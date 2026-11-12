# Writes runs.json (every stored run without its equity) and equity.json (daily equity,
# cash-sweep line and Nifty 500 per run), then prints the correlation of daily returns.
# From backend/: JERON_DATABASE_URL=... uv run python ../docs/backtests/nse-2026-11-11/scripts/export.py
import json, os, sys
from pathlib import Path

import numpy as np
import psycopg

out = Path(__file__).resolve().parent.parent
c = psycopg.connect(os.environ["JERON_DATABASE_URL"].replace("+psycopg", ""))
names = [d.name for d in c.execute("select * from backtest_runs limit 0").description]
rows = [dict(zip(names, r)) for r in c.execute("select * from backtest_runs order by id")]
equity = {r["strategy_version"]: r["equity"] for r in rows}
(out / "equity.json").write_text(json.dumps(equity, default=str))
(out / "runs.json").write_text(
    json.dumps([{k: v for k, v in r.items() if k != "equity"} for r in rows], default=str, indent=1)
)
print("point keys:", sorted(rows[0]["equity"][0]), "points:", len(rows[0]["equity"]))
rets = {}
for v, eq in equity.items():
    e = np.array([float(p["equity"]) for p in eq])
    rets[v] = e[1:] / e[:-1] - 1
vs = list(rets)
print("correlation of daily returns, whole stored curve")
for a in vs:
    print(f"{a:26s}", " ".join(f"{np.corrcoef(rets[a], rets[b])[0, 1]:5.2f}" for b in vs))
