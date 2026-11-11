# Fetches NSE's "Integrated Filing- Financials" lists (quarters from March 2025), one
# JSON file per quarter and page, with the project's Fetcher (about one request a second).
import json, sys
from pathlib import Path
from app.data.http import Fetcher

out = Path(sys.argv[1]); f = Fetcher(); SIZE = 500
for q in sys.argv[2:]:
    page = 1
    while True:
        p = out / f"{q}-{page:03d}.json"
        if not p.exists():
            p.write_bytes(f.get("https://www.nseindia.com/api/integrated-filing-results",
                {"index": "equities", "type": "Integrated Filing- Financials",
                 "period_ended": q, "page": str(page), "size": str(SIZE)}))
        d = json.loads(p.read_bytes())
        print(q, page, len(d["data"]), d.get("totalCount"), flush=True)
        if len(d["data"]) < SIZE or page * SIZE >= int(d.get("totalCount") or 0):
            break
        page += 1
