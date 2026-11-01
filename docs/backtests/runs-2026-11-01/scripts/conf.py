import json, psycopg, numpy as np
c = psycopg.connect("postgresql://jeron:jeron@localhost/jeron")
rows = {v: (s, e) for v, s, e in c.execute("select strategy_version, summary, equity from backtest_runs where id<=7 order by id")}
s = rows["fip-momentum-v1"][0]
print("variants_tried:", json.dumps(s["out_of_sample"]["variants_tried"])[:300])
print("confidence keys:", list(s["confidence"].keys()))
for v in ("fip-momentum-v1","momentum-v1","rs-pullback-v1"):
    cf = rows[v][0]["confidence"]
    print(v, json.dumps({k: cf[k] for k in cf if k in ("evidence","rating","label","strength","verdict","overall")})[:600])
print("holdout bench:", json.dumps(s["holdout"].get("benchmark"))[:200])
e = rows["fip-momentum-v1"][1]
print("equity type:", type(e), (list(e.keys()) if isinstance(e, dict) else e[:2]))
