"""Every strategy on Yahoo daily bars (research only: survivorship-biased universe)."""
import json, pickle, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from app.backtest.market import MarketInputs, StockData, build_market
from app.backtest.strategies import STRATEGIES, COMBINED
from app.backtest.walkforward import evaluate, evaluate_combined

S = Path(sys.argv[1]); IST = timezone(timedelta(hours=5, minutes=30))
END = date(2026, 10, 30)

def load(name):
    p = S / "yh" / (name.replace("^", "_") + ".json")
    if not p.exists() or p.stat().st_size < 500: return None
    r = (json.loads(p.read_bytes()).get("chart") or {}).get("result")
    if not r: return None
    r = r[0]; q = r["indicators"]["quote"][0]
    ts = r.get("timestamp") or []
    splits = [(datetime.fromtimestamp(v["date"], IST).date(), v["numerator"] / v["denominator"])
              for v in ((r.get("events") or {}).get("splits") or {}).values()]
    divs = {datetime.fromtimestamp(v["date"], IST).date(): v["amount"]
            for v in ((r.get("events") or {}).get("dividends") or {}).values()}
    rows = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, IST).date()
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in vals) or min(vals[:4]) <= 0 or d > END: continue
        rows[d] = vals
    return rows, splits, divs

idx = {}
for n in ("^CRSLDX", "^NSEI", "^INDIAVIX"):
    x = load(n); idx[n] = {d: v[3] for d, v in x[0].items()} if x else {}
days = sorted(d for d in idx["^NSEI"] if d.weekday() < 5)
dset = set(days)
stocks, skipped = [], []
for sym in (S / "syms.txt").read_text().split():
    x = load(sym)
    if not x or len(x[0]) < 300: skipped.append(sym); continue
    rows, splits, divs = x
    ds = [d for d in sorted(rows) if d in dset]
    a = np.array([rows[d] for d in ds], dtype=float)
    # Yahoo prices are split-adjusted; raw = adjusted * later splits; factor = adj/raw.
    later = np.array([np.prod([r for sd, r in splits if sd > d]) if splits else 1.0 for d in ds])
    factor = 1.0 / later
    vol = a[:, 4]  # Yahoo volume is split-adjusted too
    stocks.append(StockData(sym, ds, a[:, 0], a[:, 1], a[:, 2], a[:, 3], vol, factor,
                            a[:, 3] * vol, np.ones(len(ds), dtype=bool),
                            {d: v for d, v in divs.items() if d in dset}))
n500 = idx["^CRSLDX"] or idx["^NSEI"]
vix = idx["^INDIAVIX"]
print(f"{len(stocks)} stocks, {len(skipped)} skipped, {len(days)} days {days[0]}..{days[-1]}, n500 {len(n500)}", flush=True)
import csv, glob, re
from app.data.events import ResultsDate
def norm(x):
    x = re.sub(r"[^a-z0-9 ]", " ", x.lower().replace("&", " and "))
    return " ".join(w for w in x.split() if w not in ("limited", "ltd", "the", "india", "co", "company", "corporation"))
names = {}
for st in stocks:
    meta = json.loads((S / "yh" / (st.symbol + ".json")).read_bytes())["chart"]["result"][0]["meta"]
    names[norm(meta.get("longName") or meta.get("shortName") or "")] = st.symbol
cal = {}
for f in sorted(glob.glob(str(S / "seed" / "nse-results-*.csv"))):
    for row in csv.DictReader(open(f, encoding="utf-8-sig")):
        sym = names.get(norm(row["COMPANY NAME"]))
        t = row.get("Exchange Dissemination Time") or ""
        if not sym or not t.strip(): continue
        try: dt = datetime.strptime(t.strip(), "%d-%b-%Y %H:%M:%S")
        except ValueError: continue
        d = dt.date() + (timedelta(days=1) if dt.hour * 60 + dt.minute >= 15 * 60 + 30 else timedelta(0))
        cal.setdefault(sym, set()).add(d)
# Board meetings are announced at least 5 working days ahead (SEBI LODR 29): known 7 days before.
results = {k: sorted((ResultsDate(d, d - timedelta(days=7)) for d in v), key=lambda r: r.meeting_date) for k, v in cal.items()}
print(f"results calendar: {len(results)} of {len(stocks)} stocks, {sum(map(len, results.values()))} dates", flush=True)
SEC = {"Nifty Auto": "^CNXAUTO", "Nifty Financial Services": "NIFTY_FIN_SERVICE.NS", "Nifty PSU Bank": "^CNXPSUBANK", "Nifty Energy": "^CNXENERGY", "Nifty FMCG": "^CNXFMCG", "Nifty IT": "^CNXIT", "Nifty Media": "^CNXMEDIA", "Nifty Metal": "^CNXMETAL", "Nifty Pharma": "^CNXPHARMA", "Nifty Realty": "^CNXREALTY"}
sectors = {}
for name, t in SEC.items():
    try: x = load(t)
    except Exception: x = None
    if x: sectors[name] = {d: v[3] for d, v in x[0].items()}
print(f"sector indices: {len(sectors)} of {len(SEC)}", flush=True)
inputs = MarketInputs(days, stocks, n500, idx["^NSEI"], vix, results=results, results_updated=days[-1], sector_indices=sectors)
m = build_market(inputs)
out = {}
todo = [(k, s, False) for k, s in STRATEGIES.items()] + [(k, c, True) for k, c in COMBINED.items()]
only = sys.argv[2:] 
for key, s, comb in todo:
    if only and key not in only: continue
    t0 = time.time()
    try:
        e = (evaluate_combined if comb else evaluate)(m, s)
    except Exception as ex:
        print(f"{key:24s} ERROR {type(ex).__name__}: {str(ex)[:120]}", flush=True); out[key] = {"error": str(ex)}; continue
    sm = e.summary; o, h = sm["out_of_sample"], sm["holdout"]
    oc, ot = o["curve"], o["trades"]
    failed = [g["key"] for g in sm["gates"] if not g["passed"]]
    out[key] = {"version": s.version, "summary": sm, "live_eligible": e.live_eligible}
    print(f"{key:24s} n={ot['trades']:4d} exp={ot['expectancy_r']:+.3f}R pf={ot['profit_factor']:.2f} "
          f"win={ot['win_rate']:.2f} cagr={oc['cagr']*100:5.1f}% dd={oc['max_drawdown_pct']:4.1f}% "
          f"sh={oc['sharpe']:.2f} | HO n={h['trades']['trades']} exp={h['trades']['expectancy_r']:+.3f}R "
          f"ret={h['curve']['total_return']*100:+.1f}% | elig={e.live_eligible} failed={failed} "
          f"rating={sm.get('confidence',{}).get('rating')} ({time.time()-t0:.0f}s)", flush=True)
(S / ("results-" + "-".join(only or ["all"]) + ".json")).write_text(json.dumps(out, default=str))
