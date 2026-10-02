import Link from "next/link";

import { getJson, type BacktestRunSummary } from "@/lib/api";

import { num, pct, signClass } from "./format";

export const dynamic = "force-dynamic";

export default async function BacktestsPage() {
  const runs = await getJson<BacktestRunSummary[]>("/backtests");

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Backtests</h1>
      <p className="mt-2 text-neutral-500">
        Each strategy&apos;s latest walk-forward test. Numbers are out-of-sample and after Indian costs;
        the last 12 months are a holdout the strategy never trained on. A strategy is live-eligible only
        if it passes every check in the spec&apos;s section 6.
      </p>

      {!runs.ok ? (
        <p className="mt-6 text-neutral-600 dark:text-neutral-400">
          {runs.error}. Run <code>python -m app.cli backtest</code>.
        </p>
      ) : runs.data.length === 0 ? (
        <p className="mt-6 text-neutral-600 dark:text-neutral-400">
          No backtests yet. Run <code>python -m app.cli backtest</code>.
        </p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-neutral-500">
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
                <tr key={r.id} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-2 pr-4">
                    <Link href={`/backtests/${r.id}`} className="font-medium underline">
                      {r.strategy_name}
                    </Link>
                    <div className="text-xs text-neutral-500">
                      {r.strategy_version}, out-of-sample from {r.oos_start}
                    </div>
                  </td>
                  <td className="pr-4">
                    {r.live_eligible ? (
                      <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-800 dark:bg-green-900/40 dark:text-green-300">
                        LIVE-ELIGIBLE
                      </span>
                    ) : (
                      <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-900/40 dark:text-red-300">
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
