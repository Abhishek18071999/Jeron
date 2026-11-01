import json, psycopg
c = psycopg.connect("postgresql://jeron:jeron@localhost/jeron")
for v in ("fip-momentum-v1","momentum-v1","rs-pullback-v1"):
    cf = c.execute("select summary from backtest_runs where strategy_version=%s", (v,)).fetchone()[0]["confidence"]
    print("==", v)
    for ch in cf["evidence"]["checks"]: print("  ", ch["label"], "|", ch["value"], "|", ch["passed"])
    print("   rating:", cf["evidence"].get("rating"))
    print("   scenarios:", json.dumps(cf["scenarios"])[:700])
    print("   concentration:", json.dumps(cf["concentration"])[:300])
