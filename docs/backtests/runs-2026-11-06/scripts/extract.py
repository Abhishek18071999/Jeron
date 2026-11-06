# Prints every stored run's gates, holdout and evidence checks. From backend/:
# JERON_DATABASE_URL=... uv run python ../docs/backtests/runs-2026-11-06/scripts/extract.py
import json, os, psycopg

c = psycopg.connect(os.environ.get("JERON_DATABASE_URL", "postgresql://jeron:jeron@localhost/jeron").replace("+psycopg", ""))
rows = c.execute(
    "select id, strategy_version, summary, live_eligible, holdout_start, created_at "
    "from backtest_runs order by id"
).fetchall()
out = []
for id_, v, s, le, hs, ca in rows:
    o, h = s["out_of_sample"], s["holdout"]
    oc, ot = o["curve"], o["trades"]
    gates = [(x["key"], x.get("label"), x["value"], x["passed"]) for x in s["gates"]]
    conf = s.get("confidence", {}) or {}
    ev = conf.get("evidence", {}) or {}
    prov = s.get("provenance", {}) or {}
    print(f"== run {id_} {v} elig={le} ho_start={hs} at={ca:%Y-%m-%d %H:%M} fp={prov.get('data_fingerprint')}")
    print(f"   n={ot['trades']} exp={ot['expectancy_r']:.3f}R pf={ot['profit_factor']:.2f} win={ot['win_rate']:.2f} "
          f"cagr={oc['cagr']*100:.1f}% dd={oc['max_drawdown_pct']:.1f}% sharpe={oc['sharpe']:.2f}")
    hc = h.get("curve", {})
    print(f"   HO n={h['trades']['trades']} exp={h['trades']['expectancy_r']:.3f}R ret={hc.get('total_return',0)*100:.1f}% "
          f"dd={hc.get('max_drawdown_pct',0):.1f}% bench={json.dumps(h.get('benchmark'))[:160]}")
    for k, lab, val, p in gates:
        print(f"   [{'pass' if p else 'FAIL'}] {k}: {val}")
    print("   deflated:", json.dumps(o.get("deflated_sharpe"))[:200])
    print("   rating:", ev.get("rating"), "|", json.dumps(ev.get("reasons") or ev.get("summary"))[:300])
    for ch in ev.get("checks", []):
        print("     ", ch.get("label"), "|", ch.get("value"), "|", ch.get("passed"))
    by = o.get("by_year")
    if isinstance(by, dict):
        print("   by_year:", {y: (round(d.get("expectancy_r", 0), 2), d.get("trades")) for y, d in by.items()})
    rg = o.get("by_regime")
    if rg:
        print("   by_regime:", json.dumps(rg)[:300])
if rows:
    print("bench (test):", json.dumps(rows[-1][2]["out_of_sample"].get("benchmark"))[:300])
