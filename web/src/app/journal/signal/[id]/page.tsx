import Link from "next/link";
import { redirect } from "next/navigation";

import { Card, ErrorNote, LinkButton, ResearchBadge, inr } from "@/components/ui";
import { type SavedPlan, type SignalJournal, getJson } from "@/lib/api";

import { decideSignal } from "../../actions";
import { PlanForm, PlanSummary } from "../../forms";

export const dynamic = "force-dynamic";

export default async function SignalDecision({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const { error } = await searchParams;
  const result = await getJson<SignalJournal>(`/journal/signal/${encodeURIComponent(id)}`);
  if (!result.ok) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-8">
        <p className="text-bad">{result.error}</p>
      </main>
    );
  }
  const { signal: s, payload: p, entry } = result.data;
  if (entry && !error) redirect(`/journal/${entry.id}`);
  const plans = await getJson<SavedPlan[]>(`/plans?signal_id=${encodeURIComponent(s.signal_id)}&limit=1`);
  const plan = plans.ok ? (plans.data[0] ?? null) : null;

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold tracking-tight sm:text-2xl">
          <Link href={`/stocks/${s.ticker}`} className="underline">
            {s.ticker}
          </Link>
          <ResearchBadge research={s.research_only} />
        </h1>
        <LinkButton href={`/plan/${s.ticker}?signal=${s.signal_id}`} variant={plan || s.research_only ? "secondary" : "primary"}>
          {plan ? "Plan again" : "Plan trade"}
        </LinkButton>
      </div>
      <ErrorNote error={error} />
      <Card title="The plan">
        <div className="space-y-2 text-sm">
          <p className="text-muted">
            {p.setup_name} · {p.strategy_version} · {s.signal_date} · conviction {s.conviction}/5
          </p>
          <p>
            Buy between {inr(s.entry_low)} and {inr(s.entry_high)}, valid until {s.valid_until}
          </p>
          <p>
            Stop {inr(s.stop)} ({p.stop.reason}) · T1 {inr(s.t1)} · T2 {inr(s.t2)} · reward:risk{" "}
            {Number(p.risk_reward_t1).toFixed(1)} / {Number(p.risk_reward_t2).toFixed(1)} after costs
          </p>
          <p>
            {s.shares.toLocaleString("en-IN")} shares, {inr(s.capital_at_risk, 0)} at risk · hold{" "}
            {p.expected_holding.min_days}-{p.expected_holding.max_days} sessions
          </p>
          <ul className="list-disc pl-5">
            {p.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          <p>Exit plan: {p.exit_plan}</p>
          <p>Cancel if: {p.invalidation}</p>
          <p className="text-muted">Event risk: {p.event_risk}</p>
          {p.notes.map((n) => (
            <p key={n} className="text-muted">
              Note: {n}
            </p>
          ))}
          {s.research_only && (
            <p className="text-warn">
              Research only: this strategy has not passed the backtest bar, so this is not a trade to take.
              Recording &quot;skipped&quot; keeps the journal honest.
            </p>
          )}
        </div>
      </Card>
      {plan && <PlanSummary plan={plan} title="My plan" />}
      <Card title="What I did" subtitle={plan ? `Starts from plan #${plan.id}` : "No trade plan saved for this signal yet"}>
        <PlanForm action={decideSignal.bind(null, s.signal_id)} entry={entry} signalStop={s.stop} plan={plan} />
      </Card>
    </main>
  );
}
