import Link from "next/link";

import { MoodBanner, SectorStrength } from "@/components/market";
import { ActionBadge, HeatMeter, SectorBars } from "@/components/portfolio";
import { StatusBadge } from "@/components/status-badge";
import {
  Badge,
  Card,
  EmptyState,
  LinkButton,
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
} from "@/components/ui";
import {
  type Dashboard,
  type Holding,
  type MarketMood,
  type Portfolio,
  type SignalBrief,
  fetchHealth,
  getJson,
} from "@/lib/api";

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

const ACTION_ORDER: Record<string, number> = { "sell all": 0, "sell half": 1 };

function ActionsDue({ d, p }: { d: Dashboard; p: Portfolio | null }) {
  const due = (p?.holdings ?? [])
    .filter((h) => h.problem || h.action === "sell all" || h.action === "sell half")
    .sort((a, b) => (ACTION_ORDER[a.action ?? ""] ?? 2) - (ACTION_ORDER[b.action ?? ""] ?? 2));
  const events = (p?.holdings ?? []).flatMap((h) => h.events.map((e) => ({ ticker: h.ticker, e })));
  const holding = (p?.holdings ?? []).filter((h) => h.action === "hold" && !h.problem).length;
  const stale = !!p?.stale && p.holdings.length > 0;
  const nothing = !stale && due.length === 0 && events.length === 0 && d.pending.length === 0;
  return (
    <Card
      title="Actions due"
      subtitle={p ? `Before the open on ${shortDate(p.day)}` : undefined}
      action={
        <Link href="/portfolio" className="text-muted hover:text-fg hover:underline">
          Portfolio
        </Link>
      }
    >
      <div className="space-y-3">
        {stale && p && (
          <Notice tone="warn">
            Prices for {shortDate(p.expected)} are not loaded (latest: {shortDate(p.data_as_of)}), so no exit
            actions yet. Run <code>{cli("daily")}</code>
          </Notice>
        )}
        {!stale && due.length > 0 && (
          <ul className="space-y-2.5">
            {due.map((h: Holding) => (
              <li key={h.entry_id} className="text-sm">
                <div className="flex items-center gap-2">
                  <Link href={`/journal/${h.entry_id}`} className="font-semibold hover:underline">
                    {h.ticker}
                  </Link>
                  <ActionBadge h={h} />
                  <span className="ml-auto text-xs text-muted">{h.shares} sh</span>
                </div>
                <p className="mt-0.5 text-xs text-muted">{h.problem ?? h.reason}</p>
              </li>
            ))}
          </ul>
        )}
        {events.length > 0 && (
          <ul className="space-y-1 text-xs">
            {events.map(({ ticker, e }) => (
              <li key={`${ticker}-${e}`} className="text-warn">
                <span className="font-semibold">{ticker}</span>: {e}
              </li>
            ))}
          </ul>
        )}
        {d.pending.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted">
              Record your fill or skip ({d.pending.length})
            </p>
            <ul className="space-y-2">
              {d.pending.map((s) => (
                <li key={s.signal_id} className="flex items-center gap-2 text-sm">
                  <Link href={`/stocks/${s.ticker}`} className="font-semibold hover:underline">
                    {s.ticker}
                  </Link>
                  <span className="truncate text-xs text-muted">
                    {shortDate(s.signal_date)} · buy {inr(s.entry_low, 0)}–{inr(s.entry_high, 0)}
                  </span>
                  <LinkButton href={`/journal/signal/${s.signal_id}`} variant="primary" className="ml-auto">
                    Record
                  </LinkButton>
                </li>
              ))}
            </ul>
          </div>
        )}
        {nothing && (
          <p className="text-sm text-muted">
            Nothing to do before the open.
            {holding > 0 ? ` ${holding} position${holding > 1 ? "s" : ""} on hold.` : ""}
          </p>
        )}
        {!p && <Notice tone="bad">Exit plans could not be loaded from the backend.</Notice>}
      </div>
    </Card>
  );
}

function SignalItem({ s, resultsOn }: { s: SignalBrief; resultsOn?: string }) {
  const notChecked = s.event_risk?.startsWith("Results calendar");
  return (
    <li className="border-t border-line py-2.5 first:border-t-0 first:pt-0">
      <div className="flex items-center gap-2">
        <Link href={`/stocks/${s.ticker}`} className="font-semibold hover:underline">
          {s.ticker}
        </Link>
        <ResearchBadge research={s.research_only} />
        {resultsOn && (
          <Badge tone="warn" title="A results board meeting is due: expect a gap; no entry from 3 sessions before it">
            Results {shortDate(resultsOn)}
          </Badge>
        )}
        <Link href={`/journal/signal/${s.signal_id}`} className="ml-auto text-xs text-muted hover:text-fg hover:underline">
          Open
        </Link>
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

function NewSignals({ d }: { d: Dashboard }) {
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
                <SignalItem key={s.signal_id} s={s} resultsOn={ahead[s.ticker]} />
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
        <EmptyState command={cli("tradebook FILE")}>
          No open positions. Record fills on a signal in the journal, or import your Zerodha tradebook.
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
    </Card>
  );
}

function BehindTheScenes({ d }: { d: Dashboard }) {
  const alertsOn = d.alerts.telegram || d.alerts.email;
  return (
    <Card title="Behind the scenes">
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

// `?day=YYYY-MM-DD` shows the exit plans as that session's pre-open check saw them.
export default async function Home({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day } = await searchParams;
  const dayParam = day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? `?day=${day}` : "";
  const [result, health, moodResult, portfolioResult] = await Promise.all([
    getJson<Dashboard>("/dashboard"),
    fetchHealth(),
    getJson<MarketMood>("/market/mood"),
    getJson<Portfolio>(`/portfolio${dayParam}`),
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
  const actions =
    (p && !p.stale
      ? p.holdings.filter((h) => h.problem || h.action === "sell all" || h.action === "sell half").length
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
      <MoodBanner mood={mood} />
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <ActionsDue d={d} p={p} />
        <NewSignals d={d} />
        <YourRisk p={p} />
      </div>
      <SectorStrength mood={mood} />
      <BehindTheScenes d={d} />
      <SystemLine ok={!!health} db={db} />
    </Page>
  );
}
