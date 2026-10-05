import Link from "next/link";

import { getJson, type PaperAccountView } from "@/lib/api";

import { num, rupees, signClass } from "../../backtests/format";
import { EquityLine, SignalCard, StageBadge, TradesTable } from "../parts";

export const dynamic = "force-dynamic";

function Stat({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-lg font-semibold ${className}`}>{value}</div>
    </div>
  );
}

export default async function PaperAccountPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const view = await getJson<PaperAccountView>(`/paper/accounts/${id}`);
  if (!view.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <p>{view.error}</p>
      </main>
    );
  }
  const { account: a, open_trades, closed_trades, days, signals } = view.data;
  const s = a.summary;
  const closed = s.closed_trades;

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <Link href="/paper" className="text-sm text-muted underline">
        Paper trading
      </Link>
      <h1 className="mt-2 flex items-center gap-3 text-xl font-semibold tracking-tight sm:text-2xl">
        {a.strategy_name} <StageBadge stage={a.stage} />
      </h1>
      <p className="mt-2 text-muted">
        {a.strategy_version} with {a.params_label}, chosen by{" "}
        <Link href={`/backtests/${a.backtest_run_id}`} className="underline">
          backtest run {a.backtest_run_id}
        </Link>
        . Trading on paper since {a.start_date} with {rupees(a.capital)}; updated to {a.last_date ?? "-"}.
      </p>
      {a.stage !== "paper" ? (
        <p className="mt-2 rounded-lg border border-warn/30 bg-warn-bg p-3 text-sm">
          This strategy did not pass its backtest, so these signals are research only: they test the strategy
          forward and are not trades to take.
        </p>
      ) : null}

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Equity" value={rupees(s.equity)} />
        <Stat label="Return" value={`${num(s.return_pct, 2)}%`} className={signClass(s.return_pct ?? 0)} />
        <Stat label="Drawdown (max)" value={`${num(s.drawdown_pct, 1)}% (${num(s.max_drawdown_pct, 1)}%)`} />
        <Stat label="Portfolio heat" value={`${num(s.heat_pct, 1)}%`} />
        <Stat label="Open positions" value={`${s.open_positions ?? 0}`} />
        <Stat label="Orders for next session" value={`${s.pending_orders ?? 0}`} />
        <Stat label="Closed trades" value={`${closed?.trades ?? 0}`} />
        <Stat
          label="Expectancy (closed)"
          value={`${num(closed?.expectancy_r, 3)}R`}
          className={signClass(closed?.expectancy_r ?? 0)}
        />
      </div>

      <section className="mt-6">
        <EquityLine days={days} capital={Number(a.capital)} />
      </section>

      {s.notes?.length ? (
        <section className="mt-6">
          <h2 className="text-lg font-semibold">Notes</h2>
          <ul className="mt-2 list-disc pl-5 text-sm">
            {s.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Latest signals</h2>
        {signals.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No signals yet.</p>
        ) : (
          <div className="mt-2 space-y-2">
            {signals.map((sig) => (
              <SignalCard key={sig.signal_id} signal={sig} />
            ))}
          </div>
        )}
        {s.skipped_today && Object.keys(s.skipped_today).length ? (
          <p className="mt-2 text-sm text-muted">
            Skipped on {s.as_of}:{" "}
            {Object.entries(s.skipped_today)
              .map(([reason, n]) => `${reason} (${n})`)
              .join(", ")}
          </p>
        ) : null}
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Open positions</h2>
        {open_trades.length ? (
          <TradesTable trades={open_trades} open />
        ) : (
          <p className="text-sm text-muted">None.</p>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Closed trades</h2>
        {closed_trades.length ? (
          <TradesTable trades={[...closed_trades].reverse()} open={false} />
        ) : (
          <p className="text-sm text-muted">None yet.</p>
        )}
      </section>
    </main>
  );
}
