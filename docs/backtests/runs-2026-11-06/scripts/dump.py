# Writes runs.json (runs 11 onwards, without equity); run inside the scheduler container.
import json, psycopg
c = psycopg.connect("postgresql://jeron:jeron@db/jeron")
cols = [d for d in c.execute("select * from backtest_runs limit 0").description]
names = [d.name for d in cols]
rows = c.execute("select * from backtest_runs where id >= 11 order by id").fetchall()
out = [{k: v for k, v in zip(names, r) if k not in ("equity",)} for r in rows]
print(json.dumps(out, default=str, indent=1))
