import Link from "next/link";

import { Card, ErrorNote, ResearchBadge, inr, rMultiple } from "@/components/ui";
import { type JournalEntry, type SavedPlan, getJson } from "@/lib/api";

import { signClass } from "../../backtests/format";
import { addFill, deleteFill, updateEntry } from "../actions";
import { FillForm, PlanForm, PlanSummary } from "../forms";

export const dynamic = "force-dynamic";

export default async function EntryPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const { error } = await searchParams;
  const result = await getJson<JournalEntry>(`/journal/${encodeURIComponent(id)}`);
  if (!result.ok) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-8">
        <p className="text-bad">{result.error}</p>
      </main>
    );
  }
  const e = result.data;
  const p = e.position;
  const planResult = e.plan_id ? await getJson<SavedPlan>(`/plans/${e.plan_id}`) : null;
  const plan = planResult?.ok ? planResult.data : null;
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
      <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold tracking-tight sm:text-2xl">
        <Link href={`/stocks/${e.ticker}`} className="underline">
          {e.ticker}
        </Link>
        {e.signal && <ResearchBadge research={e.signal.research_only} />}
        <span className="text-base font-normal text-muted">
          {e.strategy_key ?? "own idea"} · {e.decision} · {p.status}
        </span>
      </h1>
      <ErrorNote error={error} />

      {plan && <PlanSummary plan={plan} />}
      <Card title="Position">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted">Held</dt>
            <dd>
              {p.held} of {p.bought} bought
            </dd>
          </div>
          <div>
            <dt className="text-muted">Average entry</dt>
            <dd>{inr(p.avg_entry)}</dd>
          </div>
          <div>
            <dt className="text-muted">Stop {e.own_stop ? "(mine)" : "(signal's)"}</dt>
            <dd>{inr(e.stop)}</dd>
          </div>
          <div>
            <dt className="text-muted">Realised P&amp;L (after charges)</dt>
            <dd className={signClass(p.realised_pnl)}>{inr(p.realised_pnl)}</dd>
          </div>
          <div>
            <dt className="text-muted">
              Open P&amp;L{e.last_close_date ? ` at the ${e.last_close_date} close` : ""}
            </dt>
            <dd className={signClass(p.open_pnl ?? 0)}>{inr(p.open_pnl)}</dd>
          </div>
          <div>
            <dt className="text-muted">R multiple</dt>
            <dd className={signClass(p.r_multiple ?? 0)}>{rMultiple(p.r_multiple)}</dd>
          </div>
        </dl>
        {e.signal && (
          <p className="mt-3 text-sm text-muted">
            Signal {e.signal.signal_date}: buy {inr(e.signal.entry_low)}-{inr(e.signal.entry_high)}, stop{" "}
            {inr(e.signal.stop)}, T1 {inr(e.signal.t1)}, {e.signal.shares} shares ·{" "}
            <Link href={`/stocks/${e.ticker}`} className="underline">
              chart
            </Link>
          </p>
        )}
      </Card>

      <Card title="Fills">
        {e.fills.length > 0 && (
          <table className="mb-4 w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="py-1">Date</th>
                <th>Side</th>
                <th className="text-right">Shares</th>
                <th className="text-right">Price</th>
                <th className="text-right">Charges</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {e.fills.map((f) => (
                <tr key={f.id} className="border-t border-line">
                  <td className="py-1">{f.trade_date}</td>
                  <td>{f.side}</td>
                  <td className="text-right">{f.shares}</td>
                  <td className="text-right">{inr(f.price)}</td>
                  <td className="text-right">
                    {inr(f.charges)}
                    {f.charges_estimated && <span className="text-xs text-muted"> est.</span>}
                  </td>
                  <td className="text-right">
                    <form action={deleteFill.bind(null, e.id, f.id)}>
                      <button className="text-xs text-bad underline">delete</button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <FillForm action={addFill.bind(null, e.id)} today={today} plan={e.fills.length === 0 ? plan : null} />
      </Card>

      <Card title="Decision and notes">
        <PlanForm action={updateEntry.bind(null, e.id)} entry={e} signalStop={e.signal?.stop} plan={plan} />
      </Card>
    </main>
  );
}
