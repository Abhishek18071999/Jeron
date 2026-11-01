import json, psycopg
c = psycopg.connect("postgresql://jeron:jeron@localhost/jeron")
rows = c.execute("select id, strategy_version, summary, live_eligible from backtest_runs order by id").fetchall()
for id_, v, s, le in rows:
    o, h = s["out_of_sample"], s["holdout"]
    oc, ot = o["curve"], o["trades"]
    g = {x["key"]: (x["value"], x["passed"]) for x in s["gates"]}
    ds = o.get("deflated_sharpe")
    conf = s.get("confidence", {})
    print(f"{v:22s} elig={le} n={ot['trades']} exp={ot['expectancy_r']:.3f}R pf={ot['profit_factor']:.2f} win={ot['win_rate']:.2f} "
          f"cagr={oc['cagr']*100:.1f}% dd={oc['max_drawdown_pct']:.1f}% sharpe={oc['sharpe']:.2f} | "
          f"HO n={h['trades']['trades']} exp={h['trades']['expectancy_r']:.3f}R ret={h['curve']['total_return']*100:.1f}% dd={h['curve']['max_drawdown_pct']:.1f}% | "
          f"regimes={g.get('regimes',('',))[0]} bench={g.get('benchmark',('',))[0]} failed={[k for k,(_,p) in g.items() if not p]}")
    print("   deflated:", json.dumps(ds)[:300])
    print("   rating:", json.dumps({k: conf.get(k) for k in ('rating','summary','reasons')})[:400])
    print("   by_year:", {y: (round(d.get('expectancy_r',0),2), d.get('trades')) for y, d in o['by_year'].items()} if isinstance(o['by_year'], dict) else str(o['by_year'])[:300])
    print("   yearly ret:", o.get('yearly_returns'), " bench:", o.get('benchmark_yearly_returns'))
print("bench:", json.dumps(rows[0][2]["out_of_sample"]["benchmark"])[:300])
