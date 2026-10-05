import Link from "next/link";

import {
  Badge,
  Card,
  ErrorNote,
  LinkButton,
  Notice,
  Page,
  PageHeader,
  ResearchBadge,
  type Tone,
  cli,
  inr,
  shortDate,
} from "@/components/ui";
import { WatchStar } from "@/components/watch-star";
import { type PlanView, type SavedPlan, type Watchlist, getJson } from "@/lib/api";

import { savePlan } from "../actions";
import { PlanForm } from "./plan-form";

export const dynamic = "force-dynamic";

type Search = { signal?: string; entry?: string; stop?: string; tier?: string; saved?: string; error?: string };

const moodTone: Record<string, Tone> = { attack: "accent", normal: "neutral", defend: "warn" };

function SavedPlans({ plans, saved }: { plans: SavedPlan[]; saved?: string }) {
  if (plans.length === 0) {
    return <p className="text-sm text-muted">No plans saved for this stock yet. Tick the checklist and save one.</p>;
  }
  return (
    <ul className="space-y-2.5 text-sm">
      {plans.map((p) => (
        <li key={p.id} className={`rounded-lg border px-3 py-2 ${String(p.id) === saved ? "border-accent/40 bg-accent-bg" : "border-line"}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">Plan #{p.id}</span>
            <span className="text-xs text-muted">{new Date(p.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" })}</span>
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {p.shares.toLocaleString("en-IN")} sh · entry {inr(p.entry)} · stop {inr(p.stop)} · T2 {inr(p.target2)} · risk{" "}
            {inr(p.risk_amount, 0)} · {p.tier}
            {p.supersedes_id ? ` · replaces #${p.supersedes_id}` : ""}
          </p>
          {p.reason && <p className="mt-0.5 text-xs">{p.reason}</p>}
        </li>
      ))}
    </ul>
  );
}

export default async function PlanPage({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<Search>;
}) {
  const { symbol: raw } = await params;
  const sp = await searchParams;
  const symbol = decodeURIComponent(raw).toUpperCase();
  const query = new URLSearchParams();
  if (sp.signal) query.set("signal_id", sp.signal);
  if (sp.entry && Number(sp.entry) > 0) query.set("entry", sp.entry);
  if (sp.stop && Number(sp.stop) > 0) query.set("stop", sp.stop);
  if (sp.tier === "swing" || sp.tier === "positional") query.set("tier", sp.tier);
  const [result, watch] = await Promise.all([
    getJson<PlanView>(`/plan/${encodeURIComponent(symbol)}?${query}`),
    getJson<Watchlist>("/watchlist"),
  ]);
  if (!result.ok) {
    return (
      <Page width="narrow">
        <PageHeader title={`Plan a trade: ${symbol}`} />
        <Notice tone="bad">{result.error}</Notice>
        <p className="text-sm text-muted">
          Search for the stock with Ctrl+K, or run <code>{cli("daily")}</code> if prices are missing.
        </p>
      </Page>
    );
  }
  const v = result.data;
  const s = v.stock;
  const watched = watch.ok && watch.data.items.some((i) => i.ticker === s.symbol);
  const savedPlan = sp.saved ? v.saved.find((p) => String(p.id) === sp.saved) : undefined;
  const journalHref = v.signal
    ? `/journal/signal/${v.signal.signal_id}`
    : savedPlan
      ? `/journal?plan=${savedPlan.id}#add`
      : "/journal";
  const plan = v.plan;
  const initial = {
    entry: sp.entry ?? (plan?.entry ? String(Number(plan.entry)) : (v.defaults.entry ?? "")),
    stop: sp.stop ?? (plan?.stop ? String(Number(plan.stop)) : (v.defaults.stop ?? "")),
    tier: plan?.tier ?? v.defaults.tier,
    reason: v.defaults.reason,
  };

  return (
    <Page>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            Plan a trade:{" "}
            <Link href={`/stocks/${s.symbol}`} className="hover:underline">
              {s.symbol}
            </Link>
            <WatchStar ticker={s.symbol} watched={watched} back={`/plan/${s.symbol}`} />
          </span>
        }
        subtitle={[
          s.name,
          s.sector,
          s.last_close ? `close ${inr(s.last_close)} on ${shortDate(s.last_date)}` : "no prices",
          s.score ? `score ${Number(s.score).toFixed(0)} (#${s.rank})` : "not in the latest scan",
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <ErrorNote error={sp.error} />
      {savedPlan && (
        <Notice tone="accent">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>
              <span className="font-medium">Plan #{savedPlan.id} saved:</span> buy {savedPlan.shares.toLocaleString("en-IN")} at{" "}
              {inr(savedPlan.entry)}, stop {inr(savedPlan.stop)}. Record the fill in the journal today.
            </span>
            <LinkButton href={journalHref} variant="primary">
              Record in journal
            </LinkButton>
          </div>
        </Notice>
      )}
      {v.signal && (
        <Notice>
          <span className="flex flex-wrap items-center gap-2">
            <ResearchBadge research={v.signal.research_only} />
            From the {shortDate(v.signal.signal_date)} signal ({v.signal.strategy_key}): buy {inr(v.signal.entry_low)}–
            {inr(v.signal.entry_high)}, stop {inr(v.signal.stop)}, {v.signal.shares} sh.
            <Link href={`/journal/signal/${v.signal.signal_id}`} className="text-muted underline hover:text-fg">
              Signal
            </Link>
          </span>
        </Notice>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Card title="Your plan" subtitle="Numbers update as you type; sizing is the engine's" className="lg:col-span-2">
          {!s.last_close ? (
            <Notice tone="warn">
              No prices stored for {s.symbol}. Run <code>{cli("daily")}</code>
            </Notice>
          ) : (
            <PlanForm
              key={`${s.symbol}-${sp.signal ?? ""}-${sp.saved ?? ""}`}
              symbol={s.symbol}
              signalId={v.signal?.signal_id ?? null}
              initial={initial}
              stopHint={v.defaults.stop_hint}
              plan={plan}
              checklist={v.checklist}
              action={savePlan.bind(null, s.symbol)}
            />
          )}
        </Card>
        <div className="space-y-4">
          <Card title="Market mood">
            {v.mood ? (
              <div className="space-y-1.5 text-sm">
                <p className="flex items-center gap-2">
                  <Badge tone={moodTone[v.mood.mode]}>{v.mood.mode}</Badge>
                  <span className="text-xs text-muted">risk per trade ×{v.mood.risk_multiplier}</span>
                </p>
                <p>{v.mood.reason}</p>
              </div>
            ) : (
              <p className="text-sm text-muted">
                Unknown: no completed scan. Run <code>{cli("daily")}</code>
              </p>
            )}
          </Card>
          <Card title="Events ahead">
            <div className="space-y-1.5 text-sm">
              {v.events.results_date ? (
                <p className={v.events.blackout ? "font-medium text-bad" : "text-warn"}>
                  Results board meeting {shortDate(v.events.results_date)}
                  {v.events.blackout ? ": inside the blackout, no new entry" : ""}
                </p>
              ) : null}
              <p className={v.events.blackout === null ? "text-warn" : "text-muted"}>{v.events.results_line}</p>
              {v.events.blackout === null && (
                <p className="text-xs text-muted">
                  Load the calendar: <code>{cli("events")}</code>
                </p>
              )}
              {v.events.ex_dates.map((e) => (
                <p key={e} className="text-warn">
                  {e}
                </p>
              ))}
              {v.events.ex_dates.length === 0 && <p className="text-xs text-muted">No ex-dates in the next 30 days.</p>}
            </div>
          </Card>
          <Card title="Saved plans" subtitle="Never changed; a new plan replaces the last">
            <SavedPlans plans={v.saved} saved={sp.saved} />
          </Card>
        </div>
      </div>
    </Page>
  );
}
