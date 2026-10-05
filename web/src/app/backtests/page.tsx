import Link from "next/link";

import { getJson, type BacktestRunSummary } from "@/lib/api";

import { num, pct, signClass } from "./format";

export const dynamic = "force-dynamic";

export default async function BacktestsPage() {
  const runs = await getJson<BacktestRunSummary[]>("/backtests");

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Backtests</h1>
      <p className="mt-2 text-muted">
        Each strategy&apos;s latest walk-forward test. Numbers are out-of-sample and after Indian costs;
        the last 12 months are a holdout the strategy never trained on. A strategy is live-eligible only
        if it passes every check in the spec&apos;s section 6.
      </p>

      {!runs.ok ? (
        <p className="mt-6 text-muted">
          {runs.error}. Run <code>python -m app.cli backtest</code>.
        </p>
      ) : runs.data.length === 0 ? (
        <p className="mt-6 text-muted">
          No backtests yet. Run <code>python -m app.cli backtest</code>.
        </p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="py-2 pr-4">Strategy</th>
                <th className="pr-4">Verdict</th>
                <th className="pr-4 text-right">Trades</th>
                <th className="pr-4 text-right">Win rate</th>
                <th className="pr-4 text-right">Expectancy</th>
                <th className="pr-4 text-right">Profit factor</th>
                <th className="pr-4 text-right">Max drawdown</th>
                <th className="pr-4 text-right">CAGR</th>
                <th className="text-right">Checks passed</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id} className="border-t border-line">
                  <td className="py-2 pr-4">
                    <Link href={`/backtests/${r.id}`} className="font-medium underline">
                      {r.strategy_name}
                    </Link>
                    <div className="text-xs text-muted">
                      {r.strategy_version}, out-of-sample from {r.oos_start}
                    </div>
                  </td>
                  <td className="pr-4">
                    {r.live_eligible ? (
                      <span className="rounded-full bg-accent-bg px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide text-accent">
                        LIVE-ELIGIBLE
                      </span>
                    ) : (
                      <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide text-muted">
                        NOT ELIGIBLE
                      </span>
                    )}
                  </td>
                  <td className="pr-4 text-right">{r.trades.trades}</td>
                  <td className="pr-4 text-right">{pct(r.trades.win_rate)}</td>
                  <td className={`pr-4 text-right ${signClass(r.trades.expectancy_r)}`}>
                    {num(r.trades.expectancy_r, 3)}R
                  </td>
                  <td className="pr-4 text-right">{num(r.trades.profit_factor)}</td>
                  <td className="pr-4 text-right">{num(r.curve.max_drawdown_pct, 1)}%</td>
                  <td className={`pr-4 text-right ${signClass(r.curve.cagr)}`}>{pct(r.curve.cagr)}</td>
                  <td className="text-right">
                    {r.gates.filter((g) => g.passed).length} of {r.gates.length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
