import Link from "next/link";
import { redirect } from "next/navigation";

import {
  Card,
  ErrorNote,
  ResearchBadge,
  SignalRow,
  buttonClass,
  inputClass,
  inr,
  rMultiple,
} from "@/components/ui";
import { StockSearch } from "@/components/stock-search";
import { type JournalEntry, type JournalView, type SavedPlan, getJson } from "@/lib/api";

import { signClass } from "../backtests/format";
import { addManual, importTradebook } from "./actions";

export const dynamic = "force-dynamic";

function EntryTable({ entries, open }: { entries: JournalEntry[]; open: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 pr-3">Stock</th>
            <th className="pr-3">Strategy</th>
            <th className="pr-3">Decision</th>
            <th className="pr-3 text-right">Shares</th>
            <th className="pr-3 text-right">Avg entry</th>
            <th className="pr-3 text-right">{open ? "Close" : "Avg exit"}</th>
            <th className="pr-3 text-right">P&amp;L</th>
            <th className="pr-3 text-right">R</th>
            <th>Plan</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className="border-t border-line">
              <td className="py-1 pr-3">
                <Link href={`/journal/${e.id}`} className="font-medium underline">
                  {e.ticker}
                </Link>
              </td>
              <td className="pr-3">{e.strategy_key ?? "own idea"}</td>
              <td className="pr-3">{e.decision}</td>
              <td className="pr-3 text-right">{open ? e.position.held : e.position.bought}</td>
              <td className="pr-3 text-right">{inr(e.position.avg_entry)}</td>
              <td className="pr-3 text-right">{inr(open ? e.last_close : e.position.avg_exit)}</td>
              <td className={`pr-3 text-right ${signClass(e.position.realised_pnl)}`}>
                {inr(
                  open
                    ? Number(e.position.realised_pnl) + Number(e.position.open_pnl ?? 0)
                    : e.position.realised_pnl,
                  0,
                )}
              </td>
              <td className={`pr-3 text-right ${signClass(e.position.r_multiple ?? 0)}`}>
                {rMultiple(e.position.r_multiple)}
              </td>
              <td>{e.followed_plan === null ? "-" : e.followed_plan ? "followed" : "deviated"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const fmt = (v: string | null, digits = 2) => (v === null ? "-" : Number(v).toFixed(digits));

export default async function Journal({
  searchParams,
}: {
  searchParams: Promise<{ signal?: string; error?: string | string[]; research?: string; imported?: string; plan?: string }>;
}) {
  const { signal, error, research, imported, plan: planParam } = await searchParams;
  if (signal) redirect(`/journal/signal/${encodeURIComponent(signal)}`);
  const showResearch = research === "1";
  const result = await getJson<JournalView>(`/journal?research=${showResearch}`);
  if (!result.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Journal</h1>
        <p className="mt-4 text-bad">{result.error}</p>
      </main>
    );
  }
  const j = result.data;
  const planResult = planParam && /^\d+$/.test(planParam) ? await getJson<SavedPlan>(`/plans/${planParam}`) : null;
  const plan = planResult?.ok ? planResult.data : null;
  const weekly = await getJson<{ week_start: string; day: string; text: string }>("/analytics/weekly");
  const open = j.entries.filter((e) => e.position.status === "open");
  const closed = j.entries.filter((e) => e.position.status === "closed");
  const other = j.entries.filter((e) => e.position.status === "no fills");

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Journal</h1>
      {imported && (
        <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm">
          Tradebook: {imported}.
        </p>
      )}
      <ErrorNote error={error} />

      <Card
        title={`Signals waiting for a decision (${j.pending.length})`}
        action={
          <Link href={showResearch ? "/journal" : "/journal?research=1"} className="text-sm underline">
            {showResearch ? "Hide research-only" : "Show research-only"}
          </Link>
        }
      >
        {j.pending.length === 0 ? (
          <p className="text-sm text-muted">Nothing pending from the last 30 days.</p>
        ) : (
          <ul>
            {j.pending.map((s) => (
              <SignalRow key={s.signal_id} s={s} />
            ))}
          </ul>
        )}
      </Card>

      <Card title={`Open (${open.length})`}>
        {open.length ? <EntryTable entries={open} open /> : <p className="text-sm text-muted">None.</p>}
      </Card>
      <Card title={`Closed (${closed.length})`}>
        {closed.length ? (
          <EntryTable entries={closed} open={false} />
        ) : (
          <p className="text-sm text-muted">None yet.</p>
        )}
      </Card>
      {other.length > 0 && (
        <Card title="Decided, no fills">
          <ul className="text-sm">
            {other.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-2 py-1">
                <Link href={`/journal/${e.id}`} className="font-medium underline">
                  {e.ticker}
                </Link>
                {e.signal && <ResearchBadge research={e.signal.research_only} />}
                <span>{e.decision}</span>
                <span className="text-muted">{e.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="By strategy">
        {j.stats.length === 0 ? (
          <p className="text-sm text-muted">No signals yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted">
                <tr>
                  <th className="py-1 pr-3">Strategy</th>
                  <th className="pr-3 text-right">Signals</th>
                  <th className="pr-3 text-right">Pending</th>
                  <th className="pr-3 text-right">Taken / modified / skipped</th>
                  <th className="pr-3 text-right">Closed</th>
                  <th className="pr-3 text-right">Win rate</th>
                  <th className="pr-3 text-right">Expectancy</th>
                  <th className="pr-3 text-right">Profit factor</th>
                  <th className="pr-3 text-right">Net P&amp;L</th>
                  <th className="text-right">Followed / deviated (avg R)</th>
                </tr>
              </thead>
              <tbody>
                {j.stats.map((s) => (
                  <tr
                    key={s.strategy_key ?? "own"}
                    className="border-t border-line"
                  >
                    <td className="py-1 pr-3">{s.strategy_key ?? "own ideas"}</td>
                    <td className="pr-3 text-right">{s.signals}</td>
                    <td className="pr-3 text-right">{s.pending}</td>
                    <td className="pr-3 text-right">
                      {s.taken} / {s.modified} / {s.skipped}
                    </td>
                    <td className="pr-3 text-right">{s.closed}</td>
                    <td className="pr-3 text-right">
                      {s.win_rate === null ? "-" : `${(Number(s.win_rate) * 100).toFixed(0)}%`}
                    </td>
                    <td className="pr-3 text-right">{s.avg_r === null ? "-" : rMultiple(s.avg_r)}</td>
                    <td className="pr-3 text-right">{fmt(s.profit_factor)}</td>
                    <td className={`pr-3 text-right ${signClass(s.net_pnl)}`}>{inr(s.net_pnl, 0)}</td>
                    <td className="text-right">
                      {s.followed} ({s.followed_avg_r === null ? "-" : rMultiple(s.followed_avg_r)}) /{" "}
                      {s.deviated} ({s.deviated_avg_r === null ? "-" : rMultiple(s.deviated_avg_r)})
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-muted">
          Expectancy is the average R of closed trades.
        </p>
      </Card>

      {weekly.ok && (
        <Card title="This week so far">
          <pre className="whitespace-pre-wrap font-sans text-sm">{weekly.data.text}</pre>
        </Card>
      )}

      <Card title="Import my Zerodha tradebook">
        <form action={importTradebook} className="flex flex-wrap items-center gap-3 text-sm">
          <input name="file" type="file" accept=".csv,text/csv" required className="text-sm" />
          <button className={buttonClass}>Import</button>
        </form>
        <p className="mt-2 text-xs text-muted">
          Console &gt; Reports &gt; Tradebook, segment Equity, download CSV. Each trade becomes a fill on the
          matching signal or open position; importing the same file again adds nothing. Charges are estimated
          at delivery rates and marked &ldquo;est.&rdquo;.
        </p>
      </Card>

      <section id="add" className="scroll-mt-20">
        <Card
          title="Add a trade I took without a signal"
          subtitle={plan ? `From trade plan #${plan.id}: ${plan.shares} ${plan.ticker} at ${inr(plan.entry)}, stop ${inr(plan.stop)}` : undefined}
        >
          <form action={addManual} className="grid gap-3 text-sm sm:grid-cols-4">
            {plan && <input type="hidden" name="plan_id" value={plan.id} />}
            <StockSearch
              name="ticker"
              placeholder="Stock, e.g. RIL"
              required
              defaultValue={plan?.ticker ?? ""}
              inputClassName={`${inputClass} w-full`}
            />
            <input
              name="stop"
              placeholder="Stop ₹"
              inputMode="decimal"
              defaultValue={plan ? String(Number(plan.stop)) : ""}
              className={inputClass}
            />
            <input name="reason" placeholder="Why" defaultValue={plan?.reason ?? ""} className={inputClass} />
            <div>
              <button className={buttonClass}>Add</button>
            </div>
          </form>
        </Card>
      </section>
    </main>
  );
}
