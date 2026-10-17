import Link from "next/link";

import { Badge, Card, LinkButton, ResearchBadge, type Tone, inr, rMultiple, shortDate, signTone } from "@/components/ui";
import type { SectionKey, SectionPosition, SectionState, SectionStrategy, SignalCard } from "@/lib/api";

// The four sections (docs/plans/sections-v1.md), one per holding horizon.
export const SECTION_TABS: { key: SectionKey; label: string }[] = [
  { key: "swing", label: "Swing" },
  { key: "intraday", label: "Intraday" },
  { key: "positional", label: "Positional" },
  { key: "invest", label: "Long-term" },
];

const STATE: Record<SectionState, { tone: Tone; label: string }> = {
  live: { tone: "good", label: "Live" },
  research: { tone: "neutral", label: "Research only" },
  untested: { tone: "warn", label: "Not tested yet" },
  not_running: { tone: "neutral", label: "Not running" },
};

export function StateBadge({ state }: { state: SectionState }) {
  const s = STATE[state];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function SectionTabs({ active }: { active?: SectionKey }) {
  return (
    <nav aria-label="Sections" className="-mx-4 overflow-x-auto px-4">
      <ul className="flex gap-1.5">
        {SECTION_TABS.map((t) => (
          <li key={t.key}>
            <Link
              href={`/trade/${t.key}`}
              aria-current={t.key === active ? "page" : undefined}
              className={`block whitespace-nowrap rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                t.key === active
                  ? "border-accent bg-accent-bg text-accent"
                  : "border-line text-muted hover:border-line-strong hover:text-fg"
              }`}
            >
              {t.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Part({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[6.5rem_1fr] sm:gap-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

// One signal as what to buy, when, how much and why.
export function SignalCardView({ c }: { c: SignalCard }) {
  return (
    <article className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <header className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
        <Link href={`/stocks/${c.ticker}`} className="text-lg font-semibold hover:underline">
          {c.ticker}
        </Link>
        <ResearchBadge research={c.research_only} />
        <Badge>conviction {c.conviction}/5</Badge>
        <span className="text-xs text-muted">
          {c.strategy_key} · signal of {shortDate(c.signal_date)}
        </span>
        <span className="ml-auto flex items-center gap-3 text-sm">
          <Link href={`/journal/signal/${c.signal_id}`} className="text-muted hover:text-fg hover:underline">
            Record
          </Link>
          {!c.research_only && (
            <LinkButton href={`/plan/${c.ticker}?signal=${c.signal_id}`} variant="primary">
              Plan
            </LinkButton>
          )}
        </span>
      </header>
      <dl className="space-y-2.5">
        <Part label="What">{c.what}</Part>
        <Part label="When">
          {c.when}
          <span className="mt-0.5 block text-xs text-muted">Cancel if: {c.cancel_if}</span>
        </Part>
        <Part label="How much">
          {c.how_much}
          <span className="mt-0.5 block text-xs text-muted">
            Entry {inr(c.entry_low)}–{inr(c.entry_high)} · stop {inr(c.stop)} · T1 {inr(c.t1)} · T2 {inr(c.t2)}
          </span>
        </Part>
        <Part label="Why">
          <ul className="list-disc space-y-0.5 pl-4">
            {c.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Part>
        <Part label="Then">
          {c.exit_plan}. Hold {c.holding}.
          <span className="mt-0.5 block text-xs text-muted">Event risk: {c.event_risk}</span>
        </Part>
        <Part label="Record">
          <span className="text-muted">{c.backtest}</span>
        </Part>
        {c.notes.length > 0 && (
          <Part label="Notes">
            <ul className="space-y-0.5 text-warn">
              {c.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </Part>
        )}
      </dl>
    </article>
  );
}

export function StrategyList({ strategies }: { strategies: SectionStrategy[] }) {
  return (
    <ul className="space-y-3">
      {strategies.map((s) => (
        <li key={s.key} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{s.version}</span>
            <Badge tone={s.passed && s.account_status !== "retired" ? "good" : "neutral"}>{s.stage}</Badge>
            {s.run_id !== null && (
              <Link href={`/backtests/${s.run_id}`} className="ml-auto text-xs text-muted hover:text-fg hover:underline">
                Report card
              </Link>
            )}
          </div>
          <p className="mt-0.5 text-sm text-muted">{s.summary}</p>
          {s.backtested && (
            <p className="mt-0.5 text-xs text-muted">
              Backtest: {s.gates_passed} of {s.gates_total} checks passed
              {s.oos_trades !== null && `, ${s.oos_trades} trades at ${Number(s.oos_expectancy_r ?? 0).toFixed(2)}R`}
              {s.failed_gates.length > 0 && `; failed: ${s.failed_gates.join(", ")}`}
            </p>
          )}
          {s.account_id !== null && (
            <p className="mt-0.5 text-xs text-muted">
              <Link href={`/paper/${s.account_id}`} className="hover:text-fg hover:underline">
                Paper account
              </Link>
              : {s.paper_closed_trades} closed trades, {s.paper_open_positions} open
              {s.paper_return_pct !== null && (
                <>
                  , <span className={signTone(s.paper_return_pct)}>{Number(s.paper_return_pct).toFixed(2)}%</span>
                </>
              )}
              {s.retired_reason && ` · retired: ${s.retired_reason}`}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function PaperPositions({ positions }: { positions: SectionPosition[] }) {
  return (
    <Card title="Paper positions" subtitle="What the section's paper accounts hold now">
      {positions.length === 0 ? (
        <p className="text-sm text-muted">None open.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {positions.map((p) => (
            <li key={`${p.account_id}-${p.ticker}-${p.entry_date}`} className="flex flex-wrap items-center gap-x-2">
              <Link href={`/stocks/${p.ticker}`} className="font-semibold hover:underline">
                {p.ticker}
              </Link>
              <ResearchBadge research={p.research_only} />
              <span className="text-xs text-muted">
                {p.strategy_key} · since {shortDate(p.entry_date)} · {p.shares_held} sh at {inr(p.entry_price)}
                {p.current_stop && ` · stop ${inr(p.current_stop)}`}
              </span>
              <span className={`ml-auto ${signTone(p.r_multiple)}`}>{rMultiple(p.r_multiple)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
