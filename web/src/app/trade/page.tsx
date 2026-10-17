import Link from "next/link";

import { SectionTabs, StateBadge } from "@/components/sections";
import { Notice, Page, PageHeader, shortDate } from "@/components/ui";
import { type SectionSummary, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

function count(s: SectionSummary) {
  if (s.state === "not_running") return "Nothing to buy";
  if (s.live_signals > 0) return `${s.live_signals} to buy`;
  return s.state === "live" ? "Nothing new to buy" : "Nothing to buy";
}

// Four sections, one per holding horizon; each runs its own strategies.
export default async function Trade() {
  const result = await getJson<SectionSummary[]>("/sections");
  return (
    <Page>
      <PageHeader
        title="Trade"
        subtitle="Four sections, one per holding period. Each runs its own strategies and says what to buy, when, how much and why, or plainly that there is nothing."
      />
      <SectionTabs />
      {!result.ok ? (
        <Notice tone="bad">{result.error}</Notice>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {result.data.map((s) => (
            <li key={s.key}>
              <Link
                href={`/trade/${s.key}`}
                className="block h-full rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2 sm:p-5"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-lg font-semibold">{s.name}</span>
                  <StateBadge state={s.state} />
                  <span className="ml-auto text-sm font-medium">{count(s)}</span>
                </span>
                <span className="mt-0.5 block text-xs text-muted">
                  Held {s.holding}
                  {s.max_positions !== null && ` · at most ${s.max_positions} positions`}
                  {s.as_of && ` · scan of ${shortDate(s.as_of)}`}
                </span>
                <span className="mt-2 block text-sm">{s.headline}</span>
                <span className="mt-2 block text-xs text-muted">
                  {s.strategies.length === 0
                    ? "No strategies"
                    : `${s.strategies.length} strateg${s.strategies.length === 1 ? "y" : "ies"}`}
                  {s.research_signals > 0 && ` · ${s.research_signals} research-only signals`}
                  {s.open_positions > 0 && ` · ${s.open_positions} paper positions`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">Decision support, not advice. Jeron never places orders.</p>
    </Page>
  );
}
