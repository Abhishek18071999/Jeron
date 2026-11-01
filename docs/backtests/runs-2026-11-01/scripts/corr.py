import json, psycopg, numpy as np
c = psycopg.connect("postgresql://jeron:jeron@localhost/jeron")
eq = {v: e for v, e in c.execute("select strategy_version, equity from backtest_runs where id<=7")}
def rets(v):
    d = {p["date"]: p["equity"] for p in eq[v]}
    return d
ks = ["fip-momentum-v1","momentum-v1","rs-pullback-v1","results-drift-v1"]
series = {k: rets(k) for k in ks}
dates = sorted(set.intersection(*[set(s) for s in series.values()]))
M = np.array([[series[k][d] for d in dates] for k in ks])
R = np.diff(M, axis=1)/M[:, :-1]
print(dates[0], dates[-1], len(dates))
print(ks); print(np.round(np.corrcoef(R), 2))
for v in ("fip-momentum-v1","momentum-v1","rs-pullback-v1"):
    s = c.execute("select summary from backtest_runs where strategy_version=%s", (v,)).fetchone()[0]
    print(v, "level:", json.dumps(s["confidence"]["level"])[:300])
