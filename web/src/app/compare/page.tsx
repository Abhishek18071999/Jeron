import Link from "next/link";

import { Card } from "@/components/ui";
import { type CompareGate, type CompareRecord, getJson, type StrategyCompare } from "@/lib/api";

import { num, pct, signClass } from "../backtests/format";

export const dynamic = "force-dynamic";

const r = (value: number | null) => (value === null ? "-" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`);

function Column({ label, rec, range }: { label: string; rec: CompareRecord | null; range?: [number, number] | null }) {
  if (!rec) return <td className="px-2 align-top text-muted">-</td>;
  return (
    <td className="px-2 align-top">
      <div className="text-xs text-muted">{label}</div>
      <div className={`font-medium ${signClass(rec.expectancy_r ?? 0)}`}>{r(rec.expectancy_r)}</div>
      <div className="text-xs text-muted">
        {rec.trades} trades, win {pct(rec.win_rate, 0)}, PF {num(rec.profit_factor)}, hold{" "}
        {num(rec.avg_sessions, 1)}
        <br />
        max drawdown {num(rec.max_drawdown, 1)}
        {rec.drawdown_unit}
        {range && (
          <>
            <br />
            expected {r(range[0])} to {r(range[1])}
          </>
        )}
      </div>
    </td>
  );
}

function GateNote({ gate }: { gate: CompareGate | null }) {
  if (!gate) return null;
  const color =
    gate.status === "passed"
      ? "text-good"
      : gate.status === "failed"
        ? "text-bad"
        : "text-muted";
  return (
    <li>
      <span className={`font-medium ${color}`}>
        {gate.name} gate: {gate.status}
      </span>{" "}
      <span className="text-muted">{gate.detail}</span>
    </li>
  );
}

export default async function ComparePage() {
  const result = await getJson<StrategyCompare[]>("/analytics/compare");
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Backtest vs paper vs real</h1>
        <p className="mt-2 text-sm text-muted">
          Spec section 7: each strategy moves from backtest to paper (3 months and 30 trades, inside the
          backtest&apos;s expected range) to small real money (my results match paper) to full capital.
          Expectancy is after costs; backtest numbers are out-of-sample only.
        </p>
      </div>
      {!result.ok ? (
        <p className="text-bad">{result.error}</p>
      ) : result.data.length === 0 ? (
        <p className="text-muted">
          No paper accounts yet. Run <code>python -m app.cli backtest</code>, then <code>paper</code>.
        </p>
      ) : (
        result.data.map((s) => (
          <Card
            key={s.account_id ?? "own"}
            title={s.strategy_version ? `${s.strategy_version} (${s.params_label})` : "My own ideas (no signal)"}
            action={<span className="text-sm font-medium">Stage: {s.stage}</span>}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  <tr>
                    <Column label="Backtest (out-of-sample)" rec={s.backtest} />
                    <Column label="Paper" rec={s.paper} range={s.paper_range} />
                    <Column label="Real (journal)" rec={s.real} range={s.real_range} />
                  </tr>
                </tbody>
              </table>
            </div>
            <ul className="mt-3 space-y-1 text-sm">
              <GateNote gate={s.paper_gate} />
              <GateNote gate={s.real_gate} />
            </ul>
            {s.divergence && (
              <div className="mt-3 text-sm">
                <div className="font-medium">Real vs paper on the same signals ({s.divergence.pairs} traded)</div>
                {s.divergence.causes.length === 0 ? (
                  <p className="text-muted">No clear cause of difference.</p>
                ) : (
                  <ul className="list-disc pl-5">
                    {s.divergence.causes.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {s.backtest_run_id && (
              <Link href={`/backtests/${s.backtest_run_id}`} className="mt-3 inline-block text-sm underline">
                Backtest report card
              </Link>
            )}
          </Card>
        ))
      )}
    </main>
  );
}
