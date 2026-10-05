import Link from "next/link";

import { getJson, type PaperAccount } from "@/lib/api";

import { num, rupees, signClass } from "../backtests/format";
import { StageBadge } from "./parts";

export const dynamic = "force-dynamic";

export default async function PaperPage() {
  const accounts = await getJson<PaperAccount[]>("/paper/accounts");

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Paper trading</h1>
      <p className="mt-2 text-muted">
        Every strategy&apos;s signals, traded on paper with exactly the rules that were backtested (spec
        section 7, stage 2). A strategy that hasn&apos;t passed its backtest is traded as{" "}
        <em>research only</em>: its signals collect evidence and are never alerts to act on.
      </p>

      {!accounts.ok ? (
        <p className="mt-6 text-muted">
          {accounts.error}. Run <code>python -m app.cli paper</code>.
        </p>
      ) : accounts.data.length === 0 ? (
        <p className="mt-6 text-muted">
          No paper accounts yet. Run <code>python -m app.cli backtest</code>, then{" "}
          <code>python -m app.cli paper</code> after the daily scan.
        </p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="py-2 pr-4">Strategy</th>
                <th className="pr-4">Stage</th>
                <th className="pr-4">Since</th>
                <th className="pr-4 text-right">Equity</th>
                <th className="pr-4 text-right">Return</th>
                <th className="pr-4 text-right">Drawdown</th>
                <th className="pr-4 text-right">Heat</th>
                <th className="pr-4 text-right">Open</th>
                <th className="pr-4 text-right">Closed trades</th>
                <th className="text-right">Expectancy</th>
              </tr>
            </thead>
            <tbody>
              {accounts.data.map((a) => (
                <tr key={a.id} className="border-t border-line">
                  <td className="py-2 pr-4">
                    <Link href={`/paper/${a.id}`} className="font-medium underline">
                      {a.strategy_name}
                    </Link>
                    <div className="text-xs text-muted">
                      {a.strategy_version} ({a.params_label}), updated to {a.last_date ?? "-"}
                    </div>
                  </td>
                  <td className="pr-4">
                    <StageBadge stage={a.stage} />
                  </td>
                  <td className="pr-4">{a.start_date}</td>
                  <td className="pr-4 text-right">{rupees(a.summary.equity)}</td>
                  <td className={`pr-4 text-right ${signClass(a.summary.return_pct ?? 0)}`}>
                    {num(a.summary.return_pct, 2)}%
                  </td>
                  <td className="pr-4 text-right">{num(a.summary.drawdown_pct, 1)}%</td>
                  <td className="pr-4 text-right">{num(a.summary.heat_pct, 1)}%</td>
                  <td className="pr-4 text-right">{a.summary.open_positions ?? 0}</td>
                  <td className="pr-4 text-right">{a.summary.closed_trades?.trades ?? 0}</td>
                  <td className={`text-right ${signClass(a.summary.closed_trades?.expectancy_r ?? 0)}`}>
                    {num(a.summary.closed_trades?.expectancy_r, 3)}R
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
