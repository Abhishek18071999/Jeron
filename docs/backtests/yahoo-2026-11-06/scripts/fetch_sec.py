import sys, urllib.parse
from pathlib import Path
from app.data.http import Fetcher
out = Path(sys.argv[1]); f = Fetcher()
for t in ["^CNXAUTO", "NIFTY_FIN_SERVICE.NS", "^CNXPSUBANK", "^CNXENERGY", "^CNXFMCG", "^CNXIT", "^CNXMEDIA", "^CNXMETAL", "^CNXPHARMA", "^CNXREALTY"]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=1451606400&period2=1793145600&interval=1d"
    try: (out / (t.replace("^", "_") + ".json")).write_bytes(f.get(url))
    except Exception as e: print(t, "ERR", str(e)[:80])
