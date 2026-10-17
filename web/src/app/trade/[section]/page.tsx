import { notFound } from "next/navigation";

import { PaperPositions, SECTION_TABS, SectionTabs, SignalCardView, StateBadge, StrategyList } from "@/components/sections";
import { Card, EmptyState, Notice, Page, PageHeader, cli, shortDate } from "@/components/ui";
import { type SectionDetail, type SectionKey, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

const KEYS = SECTION_TABS.map((t) => t.key);

export default async function Section({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!KEYS.includes(section as SectionKey)) notFound();
  const key = section as SectionKey;
  const result = await getJson<SectionDetail>(`/sections/${key}`);
  if (!result.ok) {
    return (
      <Page>
        <PageHeader title="Trade" />
        <SectionTabs active={key} />
        <Notice tone="bad">{result.error}</Notice>
      </Page>
    );
  }
  const s = result.data;
  const live = s.signals.filter((c) => !c.research_only);
  const research = s.signals.filter((c) => c.research_only);
  const tone = s.state === "live" ? "good" : s.state === "untested" ? "warn" : "neutral";
  return (
    <Page>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {s.name} <StateBadge state={s.state} />
          </span>
        }
        subtitle={`${s.about} Held ${s.holding}${s.max_positions !== null ? `, at most ${s.max_positions} positions` : ""}.`}
      />
      <SectionTabs active={key} />
      <Notice tone={tone}>{s.headline}</Notice>

      {s.state === "not_running" ? (
        <Card title="What intraday would take">
          <ul className="list-disc space-y-1.5 pl-4 text-sm">
            {s.needs.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Card>
      ) : (
        <>
          <section className="space-y-3">
            <h2 className="text-[0.95rem] font-semibold">
              What to buy{s.as_of ? ` after the scan of ${shortDate(s.as_of)}` : ""}
            </h2>
            {!s.as_of ? (
              <EmptyState command={cli("daily")}>No scan yet, so no signals.</EmptyState>
            ) : live.length > 0 ? (
              live.map((c) => <SignalCardView key={c.signal_id} c={c} />)
            ) : (
              <EmptyState>
                {s.state === "live"
                  ? "Nothing new to buy today. The live strategy's rules found no entry."
                  : "Nothing to buy: no strategy in this section has passed the backtest bar."}
              </EmptyState>
            )}
          </section>

          {research.length > 0 && (
            <details className="rounded-xl border border-line bg-surface p-4 sm:p-5">
              <summary className="cursor-pointer text-sm font-semibold">
                Research only, not trades ({research.length})
              </summary>
              <p className="mt-2 text-xs text-muted">
                From strategies that failed the backtest bar, paper-traded to gather evidence. Do not trade them.
              </p>
              <div className="mt-3 space-y-3">
                {research.map((c) => (
                  <SignalCardView key={c.signal_id} c={c} />
                ))}
              </div>
            </details>
          )}

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Card title="Strategies" subtitle="Each passes the seven backtest checks before its signals count">
              {s.strategies.length === 0 ? (
                <p className="text-sm text-muted">None yet.</p>
              ) : (
                <StrategyList strategies={s.strategies} />
              )}
            </Card>
            <PaperPositions positions={s.positions} />
          </div>
        </>
      )}
      <p className="text-xs text-muted">Decision support, not advice. Jeron never places orders.</p>
    </Page>
  );
}
