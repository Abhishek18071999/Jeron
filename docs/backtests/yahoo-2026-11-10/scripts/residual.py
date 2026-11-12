"""residual-momentum-v1 on Yahoo daily bars, beside momentum-v1, fip-momentum-v1 and
rs-pullback-v1 on the same market (research only: survivorship-biased universe).

The market is built exactly as ../../yahoo-2026-11-06/scripts/run.py builds it (that
file's code up to the strategy loop is executed here). From backend/:
  PYTHONPATH=. uv run python ../docs/backtests/yahoo-2026-11-06/scripts/fetch.py DIR/yh DIR/syms.txt
  PYTHONPATH=. uv run python ../docs/backtests/yahoo-2026-11-06/scripts/fetch_sec.py DIR/yh
  PYTHONPATH=. uv run python ../docs/backtests/yahoo-2026-11-10/scripts/residual.py DIR OUT
with syms.txt and the unzipped backend/seed results CSVs (DIR/seed) in DIR.
"""
import json, sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[2])
source = (HERE / "../../yahoo-2026-11-06/scripts/run.py").read_text()
sys.argv = [sys.argv[0], sys.argv[1]]
exec(source[: source.index("out = {}")])  # days, stocks, inputs, m

from app.backtest.job import missing_inputs  # noqa: E402
from app.backtest.stats import daily_rate, daily_returns, deflated_sharpe  # noqa: E402
from app.backtest.walkforward import all_trial_sharpes  # noqa: E402

KEYS = ["residual-momentum", "momentum", "fip-momentum", "rs-pullback"]
runs, curves = {}, {}
for key in KEYS:
    e = evaluate(m, STRATEGIES[key])
    runs[key] = {"version": e.strategy.version, "live_eligible": e.live_eligible,
                 "summary": e.summary}
    curves[e.strategy.version] = e.equity
    o, h = e.summary["out_of_sample"], e.summary["holdout"]
    print(f"{key:18s} n={o['trades']['trades']} exp={o['trades']['expectancy_r']:+.3f}R "
          f"pf={o['trades']['profit_factor']:.2f} cagr={o['curve']['cagr'] * 100:.1f}% "
          f"dd={o['curve']['max_drawdown_pct']:.1f}% sharpe={o['curve']['sharpe']:.2f} | holdout "
          f"n={h['trades']['trades']} exp={h['trades']['expectancy_r']:+.3f}R "
          f"pf={h['trades']['profit_factor']:.2f} ret={h['curve']['total_return'] * 100:+.1f}% | "
          f"eligible={e.live_eligible} rating={e.summary['confidence']['evidence']['rating']}",
          flush=True)

versions = list(curves)
dates = [p["date"] for p in curves[versions[0]]]
rets = {v: daily_returns(np.array([p["equity"] for p in curves[v]])) for v in versions}
print("daily-return correlation", versions)
print(np.round(np.corrcoef([rets[v] for v in versions]), 2))

# Deflated Sharpe against every variant of every strategy that can run on this market.
use = [st for st in STRATEGIES.values() if not missing_inputs(m, st)]
trials = all_trial_sharpes(m, use)
holdout = runs[KEYS[0]]["summary"]["periods"]["holdout"][0]
dsr = {}
for v in versions:
    curve = np.array([p["equity"] for p in curves[v] if p["date"] < holdout])
    dsr[v] = round(float(deflated_sharpe(daily_returns(curve) - daily_rate(6.5), trials)), 4)
print(f"deflated Sharpe against all {len(trials)} variants ({len(use)} strategies):", dsr)

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "results.json").write_text(json.dumps(
    {"stocks": len(stocks), "days": [str(days[0]), str(days[-1])], "runs": runs,
     "deflated_sharpe_all": {"trials": len(trials), "values": dsr}}, default=str))
(OUT / "equity.json").write_text(json.dumps(curves))
