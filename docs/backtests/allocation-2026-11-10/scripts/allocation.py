"""Allocation study on the stored runs of 2026-11-01 (no new backtest, no new signal).

Reads ../../runs-2026-11-01/equity.json: each run's daily equity, its cash-sweep line and
Nifty 500. Run from this folder: python3 allocation.py

1. Idle cash is recovered from the cash-sweep line (stats.cash_sweep_curve run backwards).
2. A fixed share of idle cash in the index: the return/drawdown trade-off.
3. The same, only while Nifty 500 closed the last month above its 200-session average
   (Faber 2007), 0.1% of the amount moved per switch. Once on the stored benchmark alone,
   once with the average's history from Yahoo's Nifty 500 closes (../nifty500-yahoo.csv).
4. An equal split of capital between strategies, rebalanced daily (no costs: an upper bound).
5. Paired block bootstrap of the Sharpe difference between the split and fip-momentum-v1.
"""

import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUNS = {r["strategy_version"]: r["equity"] for r in json.loads(
    (HERE / "../../runs-2026-11-01/equity.json").read_text())}
YEAR = 250
RATE = 1.065 ** (1 / YEAR) - 1
HOLDOUT = "2025-10-31"
PASSING = ["fip-momentum-v1", "momentum-v1", "rs-pullback-v1"]


def col(version, name):
    return np.array([p[name] for p in RUNS[version]], dtype=float)


DATES = [p["date"] for p in RUNS[PASSING[0]]]
BENCH = col(PASSING[0], "benchmark")
R_IDX = BENCH[1:] / BENCH[:-1] - 1
H = DATES.index(HOLDOUT)


def sharpe(r):
    return float((r - 0.065 / YEAR).mean() / r.std() * np.sqrt(YEAR))


def stats(eq):
    eq = np.asarray(eq, dtype=float)
    r = np.diff(eq) / eq[:-1]
    cagr = (eq[-1] / eq[0]) ** (YEAR / len(r)) - 1
    dd = (1 - eq / np.maximum.accumulate(eq)).max()
    return f"CAGR {cagr * 100:5.1f}%  Sharpe {sharpe(r):4.2f}  max DD {dd * 100:4.1f}%"


def idle_cash(version):
    """Cash at each close, from extra[t] = extra[t-1](1+r) + cash[t-1](r - rate)."""
    eq, sweep = col(version, "equity"), col(version, "sweep")
    extra = sweep - eq
    cash = (extra[1:] - extra[:-1] * (1 + R_IDX)) / (R_IDX - RATE)
    share = np.clip(cash / eq[:-1], 0, 1)
    steady = np.abs(R_IDX - RATE) > 0.002  # the division is unstable on flat index days
    last = float(np.median(share[steady]))
    for i in range(len(share)):
        if steady[i]:
            last = share[i]
        else:
            share[i] = last
    return share * eq[:-1]


def month_end_trend(n=200):
    """True from the close of a month's last session when the index is above its
    n-session average; None before the average exists."""
    out, state = [], None
    for i in range(len(BENCH)):
        last_of_month = i + 1 < len(BENCH) and DATES[i][:7] != DATES[i + 1][:7]
        if last_of_month and i >= n - 1:
            state = bool(BENCH[i] > BENCH[i - n + 1 : i + 1].mean())
        out.append(state)
    return out


def swept(version, share=1.0, gate=None, start=0, cost=0.001):
    eq, cash = col(version, "equity"), idle_cash(version)
    extra, out, switches = 0.0, [eq[start]], 0
    for i in range(start, len(R_IDX)):
        on = True if gate is None else bool(gate[i])
        if gate is not None and i > start and gate[i] != gate[i - 1]:
            switches += 1
            extra -= (share * cash[i] + max(extra, 0.0)) * cost
        if on:
            extra = extra * (1 + R_IDX[i]) + share * cash[i] * (R_IDX[i] - RATE)
        else:
            extra *= 1 + RATE
        out.append(eq[i + 1] + extra)
    return np.array(out), switches


def split(versions, column="equity"):
    r = np.mean([np.diff(col(v, column)) / col(v, column)[:-1] for v in versions], axis=0)
    return np.concatenate([[1.0], np.cumprod(1 + r)])


def by_year(eq):
    years = sorted({d[:4] for d in DATES})
    out = []
    for y in years:
        idx = [i for i, d in enumerate(DATES) if d[:4] == y]
        first = max(idx[0] - 1, 0)
        out.append(f"{y} {100 * (eq[idx[-1]] / eq[first] - 1):+.1f}%")
    return "  ".join(out)


print(f"Period {DATES[0]} to {DATES[-1]}, {len(DATES)} sessions; holdout from {HOLDOUT}")
print(f"Nifty 500            {stats(BENCH)}")
print("\n1. Idle cash (share of equity, mean)")
for v in PASSING:
    print(f"  {v:18s} {np.mean(idle_cash(v) / col(v, 'equity')[:-1]):.2f}")

print("\n2. A fixed share of idle cash in Nifty 500, whole period")
for v in PASSING:
    for s in (0, 0.25, 0.5, 0.75, 1.0):
        curve, _ = swept(v, s)
        print(f"  {v:18s} share {s:4.2f}  {stats(curve)}  holdout "
              f"{100 * (curve[-1] / curve[H] - 1):+5.1f}%")

print("\n3. Trend gate (month-end, 200-session average)")
gate = month_end_trend()
start = next(i for i, g in enumerate(gate) if g is not None)
print(f"  a. stored benchmark only, from {DATES[start]} (after the March 2020 fall)")
print(f"  Nifty 500          {stats(BENCH[start:])}")
for v in PASSING:
    always, _ = swept(v, 1.0, None, start)
    gated, n = swept(v, 1.0, gate, start)
    print(f"  {v:18s} alone   {stats(col(v, 'equity')[start:])}")
    print(f"  {'':18s} always  {stats(always)}")
    print(f"  {'':18s} gated   {stats(gated)}  ({n} switches)")

# Yahoo's Nifty 500 closes from 2016 (../nifty500-yahoo.csv) give the average its history,
# so the whole period, March 2020 included, can be tested.
rows = [x.split(",") for x in (HERE / "../nifty500-yahoo.csv").read_text().split()[1:]]
ydates, yclose = [r[0] for r in rows], np.array([float(r[1]) for r in rows])
known, state = {}, None
for i, d in enumerate(ydates):
    last_of_month = i + 1 < len(ydates) and ydates[i + 1][:7] != d[:7]
    if last_of_month and i >= 199:
        state = bool(yclose[i] > yclose[i - 199 : i + 1].mean())
    known[d] = state
full, prev = [], None
for d in DATES:
    prev = known.get(d, prev)
    full.append(bool(prev))
flips = [DATES[i] for i in range(1, len(full)) if full[i] != full[i - 1]]
print(f"  b. average from Yahoo's closes since {ydates[0]}: whole period")
print(f"  in the index at the start: {full[0]}; switches on {', '.join(flips)}")
for v in PASSING:
    always, _ = swept(v, 1.0)
    half, _ = swept(v, 0.5)
    gated, n = swept(v, 1.0, full)
    gated_half, _ = swept(v, 0.5, full)
    print(f"  {v:18s} alone        {stats(col(v, 'equity'))}")
    print(f"  {'':18s} always       {stats(always)}")
    print(f"  {'':18s} half, always {stats(half)}")
    print(f"  {'':18s} gated        {stats(gated)}  holdout "
          f"{100 * (gated[-1] / gated[H] - 1):+5.1f}%  ({n} switches)")
    print(f"  {'':18s} half, gated  {stats(gated_half)}")

print("\n4. Capital split equally between strategies")
combos = [["fip-momentum-v1"], ["fip-momentum-v1", "rs-pullback-v1"],
          ["fip-momentum-v1", "momentum-v1"], PASSING]
for c in combos:
    curve = split(c)
    print(f"  {' + '.join(c):52s} {stats(curve)}  holdout "
          f"{100 * (curve[-1] / curve[H] - 1):+5.1f}%")
    print(f"      {by_year(curve)}")
print(f"  Nifty 500 by year: {by_year(BENCH)}")
names = PASSING
rets = [np.diff(col(v, "equity")) / col(v, "equity")[:-1] for v in names]
print("  daily-return correlation", names)
print(np.round(np.corrcoef(rets), 2))

print("\n5. Is the split's Sharpe really above fip-momentum-v1's? Paired block bootstrap")
rng = np.random.default_rng(20261110)
a = np.diff(split(PASSING)) / split(PASSING)[:-1]
b = rets[0]
n, block = len(a), 20
diffs = []
for _ in range(5000):
    starts = rng.integers(0, n - block, size=n // block + 1)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
    diffs.append(sharpe(a[idx]) - sharpe(b[idx]))
diffs = np.array(diffs)
print(f"  Sharpe difference {sharpe(a) - sharpe(b):+.2f}; 95% range "
      f"{np.percentile(diffs, 2.5):+.2f} to {np.percentile(diffs, 97.5):+.2f}; "
      f"above zero in {100 * (diffs > 0).mean():.0f}% of resamples")
