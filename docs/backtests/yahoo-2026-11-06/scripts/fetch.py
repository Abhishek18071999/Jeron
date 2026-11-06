import json, sys, time, urllib.parse
from pathlib import Path
from app.data.http import Fetcher
out = Path(sys.argv[1]); syms = Path(sys.argv[2]).read_text().split()
f = Fetcher()
p1, p2 = 1451606400, 1761868800  # 2016-01-01 .. 2025-10-31
p2 = 1761868800 + 86400 * 2  # through end of Oct 2025 +; extend below
p2 = 1793145600  # 2026-10-28 approx; Yahoo clips to today
for s in ["^CRSLDX", "^NSEI", "^INDIAVIX"] + syms:
    path = out / (s.replace("^", "_") + ".json")
    if path.exists(): continue
    t = s if s.startswith("^") else s + ".NS"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1={p1}&period2={p2}&interval=1d&events=div,splits"
    try:
        path.write_bytes(f.get(url))
    except Exception as e:
        print(s, "ERR", str(e)[:80], flush=True)
