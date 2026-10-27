import Link from "next/link";

import { MoodBanner, SectorStrength } from "@/components/market";
import { NewsCard } from "@/components/news";
import { BriefingList } from "@/components/briefing";
import { HeatMeter, SectorBars } from "@/components/portfolio";
import { StateBadge } from "@/components/sections";
import { StatusBadge } from "@/components/status-badge";
import { EvidenceBadge, HealthText, StrategyStatusBadge } from "@/components/strategy-status";
import {
  Badge,
  Card,
  EmptyState,
  Notice,
  Page,
  PageHeader,
  ResearchBadge,
  Stat,
  cli,
  inr,
  inrSigned,
  pctText,
  shortDate,
  signTone,
  RunCommand,
} from "@/components/ui";
import {
  type Dashboard,
  type MarketMood,
  type NewsView,
  type Portfolio,
  type SectionSummary,
  type SetupView,
  type SignalBrief,
  type StrategyRow,
  type Watchlist,
  fetchHealth,
  getJson,
} from "@/lib/api";
import { briefing } from "@/lib/briefing";

export const dynamic = "force-dynamic";

const RESEARCH_SHOWN = 4;

function SystemLine({ ok, db }: { ok: boolean; db: boolean }) {
  return (
    <p className="text-xs text-muted">
      Backend: <span className={ok ? "" : "text-bad"}>{ok ? "running" : "not reachable"}</span>
      {" · "}Database:{" "}
      <span data-database={db ? "connected" : "not connected"} className={db ? "" : "text-bad"}>
        {db ? "connected" : "not connected"}
      </span>
      {" · "}Decision support, not advice. Jeron never places orders.
    </p>
  );
}

// The morning briefing: one line per thing to do before the open, ticked off as done.
function MorningBriefing({ d, p }: { d: Dashboard; p: Portfolio | null }) {
  const { items, events, headline } = briefing(d, p);
  const holding = (p?.holdings ?? []).filter((h) => h.action === "hold" && !h.problem).length;
  const stale = !!p?.stale && p.holdings.length > 0;
  return (
    <Card
      title="Morning briefing"
      subtitle={p ? `Before the open on ${shortDate(p.day)}` : undefined}
      action={
        <Link href="/portfolio" className="text-muted hover:text-fg hover:underline">
          Portfolio
        </Link>
      }
    >
      <div className="space-y-3">
        <p className="text-sm font-medium">{headline}</p>
        {stale && p && (
          <Notice tone="warn">
            Prices for {shortDate(p.expected)} are not loaded (latest: {shortDate(p.data_as_of)}), so no exit
            actions yet. <RunCommand job="daily" />
          </Notice>
        )}
        {items.length > 0 && <BriefingList day={p?.day ?? d.as_of ?? "today"} items={items} />}
        {events.length > 0 && (
          <ul className="space-y-1 text-xs">
            {events.map((e) => (
              <li key={e} className="text-warn">
                {e}
              </li>
            ))}
          </ul>
        )}
        {items.length === 0 && holding > 0 && (
          <p className="text-sm text-muted">
            {holding} position{holding > 1 ? "s" : ""} on hold: their stops stay as they are.
          </p>
        )}
        {!p && <Notice tone="bad">Exit plans could not be loaded from the backend.</Notice>}
      </div>
    </Card>
  );
}

function SignalItem({ s, resultsOn, strategy }: { s: SignalBrief; resultsOn?: string; strategy?: StrategyRow }) {
  const notChecked = s.event_risk?.startsWith("Results calendar");
  return (
    <li className="border-t border-line py-2.5 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Link href={`/stocks/${s.ticker}`} className="font-semibold hover:underline">
          {s.ticker}
        </Link>
        <ResearchBadge research={s.research_only} />
        {strategy && !s.research_only && (
          <>
            <StrategyStatusBadge status={strategy.status.status} title={strategy.status.reason} />
            <EvidenceBadge rating={strategy.evidence?.rating} title={strategy.evidence?.summary} />
          </>
        )}
        {resultsOn && (
          <Badge tone="warn" title="A results board meeting is due: expect a gap; no entry from 3 sessions before it">
            Results {shortDate(resultsOn)}
          </Badge>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-3 text-xs">
          <Link href={`/journal/signal/${s.signal_id}`} className="text-muted hover:text-fg hover:underline">
            Open
          </Link>
          <Link href={`/plan/${s.ticker}?signal=${s.signal_id}`} className="font-medium text-accent hover:underline">
            Plan
          </Link>
        </span>
      </div>
      <p className="mt-0.5 text-xs text-muted">
        Entry <span className="text-fg">{inr(s.entry_low)}–{inr(s.entry_high)}</span> · Stop{" "}
        <span className="text-fg">{inr(s.stop)}</span> · <span className="text-fg">{s.shares}</span> sh · risk{" "}
        {inr(s.capital_at_risk, 0)}
      </p>
      {notChecked && !resultsOn && <p className="mt-0.5 text-xs text-warn">{s.event_risk}</p>}
    </li>
  );
}

function NewSignals({ d, strategies }: { d: Dashboard; strategies: StrategyRow[] }) {
  const byKey = new Map(strategies.map((s) => [s.key, s]));
  const live = d.signals.filter((s) => !s.research_only);
  const research = d.signals.filter((s) => s.research_only);
  const ahead = d.results_ahead ?? {};
  return (
    <Card
      title="New signals"
      subtitle={d.as_of ? `From the scan of ${shortDate(d.as_of)}` : undefined}
      action={
        <Link href="/journal" className="text-muted hover:text-fg hover:underline">
          Journal
        </Link>
      }
    >
      {!d.as_of ? (
        <EmptyState command={cli("daily")}>No scan yet, so no signals.</EmptyState>
      ) : d.signals.length === 0 ? (
        <EmptyState command={cli("paper")}>No signals for {shortDate(d.as_of)}. Paper trading turns scans into signals.</EmptyState>
      ) : (
        <div className="space-y-3">
          {live.length > 0 ? (
            <ul>
              {live.map((s) => (
                <SignalItem key={s.signal_id} s={s} resultsOn={ahead[s.ticker]} strategy={byKey.get(s.strategy_key)} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              No live signals: no strategy has passed the backtest bar yet, so these are research only.
            </p>
          )}
          {research.length > 0 && (
            <div>
              <ul className="opacity-90">
                {research.slice(0, RESEARCH_SHOWN).map((s) => (
                  <SignalItem key={s.signal_id} s={s} resultsOn={ahead[s.ticker]} />
                ))}
              </ul>
              {research.length > RESEARCH_SHOWN && (
                <Link href="/journal?research=1" className="mt-1 block text-xs text-muted hover:text-fg hover:underline">
                  {research.length - RESEARCH_SHOWN} more research-only signals
                </Link>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function YourRisk({ p }: { p: Portfolio | null }) {
  if (!p) {
    return (
      <Card title="Your risk">
        <EmptyState>Portfolio could not be loaded from the backend.</EmptyState>
      </Card>
    );
  }
  const t = p.totals;
  return (
    <Card
      title="Your risk"
      subtitle={`Open positions in the journal, capital ${inr(t.capital, 0)}`}
      action={
        <Link href="/portfolio" className="text-muted hover:text-fg hover:underline">
          Details
        </Link>
      }
    >
      {t.positions === 0 ? (
        <EmptyState>
          No open positions. Record fills on a signal in the journal, or upload your Zerodha tradebook on the
          Journal or Setup page.
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Stat
              label="If every stop is hit"
              value={inrSigned(-Number(t.give_back))}
              help="What you would give back from today's close if every position hit its current stop."
              sub={`${t.positions} open trade${t.positions > 1 ? "s" : ""}`}
            />
            <Stat
              label="Open P&L"
              value={<span className={signTone(t.pnl)}>{inrSigned(t.pnl)}</span>}
              help="Realised and open profit or loss of the open positions, after charges."
              sub={`open risk ${inr(t.open_risk, 0)}`}
            />
          </div>
          <HeatMeter totals={t} />
          {t.sectors.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs text-muted">Top sectors (cap {pctText(t.sector_cap_pct, 0)} of capital)</p>
              <SectorBars totals={t} limit={3} />
            </div>
          )}
          {t.warnings.map((w) => (
            <Notice key={w} tone="warn">
              {w}
            </Notice>
          ))}
        </div>
      )}
      {t.cash_action && (
        <div className="mt-4">
          <Notice>{t.cash_action}</Notice>
        </div>
      )}
    </Card>
  );
}

// The four sections at a glance: what each has to buy today.
function SectionsStrip({ sections }: { sections: SectionSummary[] | null }) {
  if (!sections) return null;
  return (
    <section aria-label="Sections" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {sections.map((s) => (
        <Link
          key={s.key}
          href={`/trade/${s.key}`}
          className="rounded-xl border border-line bg-surface px-3 py-2.5 transition-colors hover:border-line-strong hover:bg-surface-2"
        >
          <span className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold">{s.name}</span>
            <StateBadge state={s.state} />
          </span>
          <span className="mt-0.5 block text-xs text-muted">
            {s.live_signals > 0 ? (
              <span className="font-medium text-fg">{s.live_signals} to buy</span>
            ) : (
              "Nothing to buy"
            )}
            {s.research_signals > 0 && ` · ${s.research_signals} research`}
          </span>
        </Link>
      ))}
    </section>
  );
}

// A slim line: watchlist stocks whose alert price the latest session reached.
function WatchHits({ w }: { w: Watchlist | null }) {
  if (!w) return null;
  const hits = w.items.filter((i) => i.hit);
  return (
    <section className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm sm:px-5">
      <Link href="/watchlist" className="font-semibold hover:underline">
        Watchlist
      </Link>
      {w.items.length === 0 ? (
        <span className="text-muted">Empty. Star a stock on its page to watch it and set an alert price.</span>
      ) : hits.length === 0 ? (
        <span className="text-muted">
          {w.items.length} watched; none reached its alert price on {shortDate(w.day)}.
        </span>
      ) : (
        <>
          <span className="text-muted">Alert price reached on {shortDate(w.day)}:</span>
          <ul className="flex flex-wrap gap-2">
            {hits.map((h) => (
              <li key={h.ticker}>
                <Link
                  href={`/plan/${h.ticker}`}
                  title={h.note || `Plan a trade in ${h.ticker}`}
                  className="inline-flex items-center gap-1.5 rounded-full bg-accent-bg px-2.5 py-0.5 text-xs font-medium text-accent hover:underline"
                >
                  {h.ticker} {h.alert_direction === "above" ? "↑" : "↓"} {inr(h.alert_price, 0)}
                  <span className="text-fg/70">close {inr(h.last_close, 0)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

// Strategy health: each paper-traded strategy's status, how strong its backtest
// evidence is, and whether paper still looks like the backtest (decision 0018).
function StrategyHealthCard({ strategies }: { strategies: StrategyRow[] | null }) {
  if (!strategies) return null;
  const shown = strategies.filter((s) => s.account_id !== null || s.status.status !== "research");
  return (
    <Card
      title="Strategy health"
      subtitle="Paper results against what the backtest says to expect for that many trades"
      action={
        <Link href="/research" className="text-muted hover:text-fg hover:underline">
          Research
        </Link>
      }
    >
      {shown.length === 0 ? (
        <EmptyState command={cli("paper")}>No strategy is paper trading yet.</EmptyState>
      ) : (
        <ul className="space-y-3 text-sm">
          {shown.map((s) => (
            <li key={s.version} className="border-t border-line pt-3 first:border-t-0 first:pt-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                {s.run_id ? (
                  <Link href={`/backtests/${s.run_id}`} className="font-semibold hover:underline">
                    {s.version}
                  </Link>
                ) : (
                  <span className="font-semibold">{s.version}</span>
                )}
                <StrategyStatusBadge status={s.status.status} title={s.status.reason} />
                <EvidenceBadge rating={s.evidence?.rating} title={s.evidence?.summary} />
                <span className="ml-auto text-xs">
                  Paper: <HealthText health={s.health} />
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted">
                {s.status.reason}
                {s.status.since && <> Since {shortDate(s.status.since)}.</>}
              </p>
              {s.health && s.health.verdict !== "too early" && <p className="mt-0.5 text-xs">{s.health.detail}</p>}
              {s.health?.flags.map((f) => (
                <p key={f.key} className="mt-0.5 text-xs text-warn">
                  {f.text}
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-muted">
        Passing the backtest gates never puts a strategy on real money: only you can move it to small capital, with{" "}
        <code>strategy-status</code>, once paper and the evidence allow it.
      </p>
    </Card>
  );
}

// The four answers before anything else: market, risk, candidates, data.
function DecisionStrip({
  d,
  p,
  mood,
  live,
}: {
  d: Dashboard;
  p: Portfolio | null;
  mood: MarketMood | null;
  live: number;
}) {
  const quality = d.quality?.status;
  const stale = !!p?.stale && !!quality; // behind the expected session (nothing loaded yet: no status)
  const dataTone = stale || quality === "fail" ? "bad" : quality === "warn" ? "warn" : quality ? "good" : "neutral";
  const heat = p ? Number(p.totals.heat_pct) : null;
  return (
    <section aria-label="Today at a glance" className="grid grid-cols-2 gap-3 rounded-xl border border-line bg-surface px-4 py-3 sm:grid-cols-4 sm:px-5">
      <Stat
        label="Market regime"
        value={mood ? mood.mode : "-"}
        tone={mood?.mode === "defend" ? "bad" : mood?.mode === "attack" ? "good" : "neutral"}
        sub={mood ? `risk x${mood.risk_multiplier}` : "not loaded"}
      />
      <Stat
        label="Portfolio heat"
        value={heat === null ? "-" : pctText(heat, 1)}
        tone={p && heat !== null && heat > Number(p.totals.heat_warn_pct) ? "warn" : "neutral"}
        sub={p ? `limit ${pctText(p.totals.heat_block_pct, 0)}` : "not loaded"}
        help="Open risk (entry to stop on every position) as a share of capital."
      />
      <Stat label="New candidates" value={live} sub={d.as_of ? `scan of ${shortDate(d.as_of)}` : "no scan yet"} />
      <Stat
        label="Data status"
        value={stale ? "stale" : quality === "fail" ? "failed" : quality === "warn" ? "warnings" : quality ? "verified" : "-"}
        tone={dataTone}
        sub={d.quality ? `checked ${shortDate(d.quality.trade_date)}` : "no report yet"}
      />
    </section>
  );
}

function BehindTheScenes({ d }: { d: Dashboard }) {
  const alertsOn = d.alerts.telegram || d.alerts.email;
  return (
    <Card title="System health">
      <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-xs text-muted">Data quality</dt>
          <dd className="mt-1">
            {d.quality ? (
              <span className="flex items-center gap-2">
                <StatusBadge status={d.quality.status} />
                <Link href={`/data/quality/${d.quality.trade_date}`} className="hover:underline">
                  {shortDate(d.quality.trade_date)}
                </Link>
              </span>
            ) : (
              <span className="text-muted">No report yet</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Scan</dt>
          <dd className="mt-1">
            {d.scan ? (
              d.scan.status === "ok" ? (
                <Link href="/scanner" className="hover:underline">
                  {d.scan.universe_size.toLocaleString("en-IN")} stocks scored
                </Link>
              ) : (
                <span className="text-bad">Blocked: {d.scan.reasons[0]}</span>
              )
            ) : (
              <span className="text-muted">No scan yet</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Alerts</dt>
          <dd className="mt-1">
            {alertsOn
              ? `On: ${[d.alerts.telegram && "Telegram", d.alerts.email && "email"].filter(Boolean).join(" + ")}`
              : <span className="text-muted">Not set up (see .env.example)</span>}
            {d.last_summary && (
              <span className="block text-xs text-muted">
                Last summary {shortDate(d.last_summary.trade_date)}: {d.last_summary.status}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Paper accounts</dt>
          <dd className="mt-1">
            {d.accounts.length === 0 ? (
              <span className="text-muted">None yet</span>
            ) : (
              <ul className="space-y-0.5">
                {d.accounts.map((a) => (
                  <li key={a.id} className="flex justify-between gap-2">
                    <Link href={`/paper/${a.id}`} className="truncate hover:underline">
                      {a.strategy_key}
                    </Link>
                    <span className={signTone(a.return_pct)}>{pctText(a.return_pct, 1, true)}</span>
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

// Shown until Jeron has set itself up, and when something needs me.
function SetupBanner({ setup }: { setup: SetupView | null }) {
  if (!setup) return null;
  const you = setup.steps.filter((s) => s.state === "you");
  const working = setup.steps.filter((s) => s.state === "working" || s.state === "waiting");
  if (!you.length && !working.length) return null;
  return (
    <Notice tone={you.length ? "warn" : "accent"}>
      {working.length > 0 && <>Jeron is setting itself up ({working.map((s) => s.title.toLowerCase()).join(", ")}). </>}
      {you.length > 0 && <>Needs you: {you.map((s) => s.title.toLowerCase()).join(", ")}. </>}
      <Link href="/setup" className="font-medium underline">
        See Setup
      </Link>
    </Notice>
  );
}

// `?day=YYYY-MM-DD` shows the exit plans as that session's pre-open check saw them.
export default async function Home({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const dayParam = day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
  const [
    result,
    health,
    moodResult,
    portfolioResult,
    watchResult,
    sectionsResult,
    newsResult,
    setupResult,
    strategiesResult,
  ] = await Promise.all([
    getJson<Dashboard>("/dashboard"),
    fetchHealth(),
    getJson<MarketMood>("/market/mood"),
    getJson<Portfolio>(`/portfolio${dayParam}`),
    getJson<Watchlist>("/watchlist"),
    getJson<SectionSummary[]>("/sections"),
    getJson<NewsView>("/news/latest"),
    getJson<SetupView>("/setup"),
    getJson<StrategyRow[]>("/strategies"),
  ]);
  const db = health?.database === "ok";
  if (!result.ok) {
    return (
      <Page>
        <PageHeader title="Today" />
        <Notice tone="bad">{result.error}</Notice>
        <SystemLine ok={!!health} db={db} />
      </Page>
    );
  }
  const d = result.data;
  const mood = moodResult.ok ? moodResult.data : null;
  const p = portfolioResult.ok ? portfolioResult.data : null;
  const strategies = strategiesResult.ok ? strategiesResult.data : null;
  const actions =
    (p && !p.stale
      ? p.holdings.filter(
          (h) =>
            h.problem ||
            h.action === "sell all" ||
            h.action === "sell half" ||
            (h.action === "hold" && h.stop_raised_from),
        ).length
      : 0) + d.pending.length;
  const live = d.signals.filter((s) => !s.research_only).length;
  const research = d.signals.length - live;
  const headline = [
    actions === 0 ? "Nothing due" : `${actions} action${actions > 1 ? "s" : ""} due`,
    `${live} new signal${live === 1 ? "" : "s"}${research ? ` (+${research} research only)` : ""}`,
    mood ? `market: ${mood.mode}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Page>
      <PageHeader
        title="Today"
        subtitle={
          <>
            <span className="font-medium text-fg">{headline}</span>
            {d.as_of && <span> · closes to {shortDate(d.as_of)}</span>}
          </>
        }
      />
      <SetupBanner setup={setupResult.ok ? setupResult.data : null} />
      <DecisionStrip d={d} p={p} mood={mood} live={live} />
      <MoodBanner mood={mood} />
      <SectionsStrip sections={sectionsResult.ok ? sectionsResult.data : null} />
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <MorningBriefing d={d} p={p} />
        <NewSignals d={d} strategies={strategies ?? []} />
        <YourRisk p={p} />
      </div>
      <StrategyHealthCard strategies={strategies} />
      <WatchHits w={watchResult.ok ? watchResult.data : null} />
      <NewsCard
        title="Latest company news"
        news={newsResult.ok ? newsResult.data : null}
        showSymbol
        empty="No company announcements in the last week."
      />
      <SectorStrength mood={mood} />
      <BehindTheScenes d={d} />
      <SystemLine ok={!!health} db={db} />
    </Page>
  );
}
