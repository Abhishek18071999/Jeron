import Link from "next/link";

import { SignalHowTo, StrategiesAtAGlance } from "@/components/strategy-guide";
import { Badge, Card, EmptyState, Help, LinkButton, Notice, Page, PageHeader, type Tone, pctText, shortDate } from "@/components/ui";
import { type CompareView, type Performance, type Ranked, type StockBrief, type Watchlist, getJson } from "@/lib/api";
import {
  INDEX_COLOR,
  MAX_COMPARE,
  STOCK_COLORS,
  type ShownRow,
  checksPassed,
  compareRows,
  differences,
  parseSymbols,
  performanceRows,
} from "@/lib/compare";
import { SECTION_RULES, strategyGuide } from "@/lib/strategy-guide";

import { type Line, PerformanceChart } from "./performance-chart";
import { ComparePicker } from "./picker";

export const dynamic = "force-dynamic";

const stanceClass = { for: "text-good", against: "text-bad", neutral: "" } as const;
const setupTone: Record<string, Tone> = {
  "in zone": "good",
  waiting: "accent",
  "above zone": "warn",
  invalidated: "bad",
  expired: "bad",
};

const compareHref = (symbols: string[]) => `/stocks/compare?symbols=${encodeURIComponent(symbols.join(","))}`;

// Phones: the label on its own line, then one column per stock. Wider: label first.
const gridCols = "grid-cols-[repeat(var(--n),minmax(0,1fr))] sm:grid-cols-[11rem_repeat(var(--n),minmax(0,1fr))]";

function StockCard({ b, color, perf }: { b: StockBrief; color: string; perf?: Performance }) {
  const close = b.facts.find((f) => f.label === "Last close");
  const found = strategyGuide(b.strategy);
  const checks = checksPassed(b);
  return (
    <section
      className="flex w-[85%] min-w-0 shrink-0 snap-start flex-col gap-2 rounded-xl border border-line border-t-4 bg-surface p-4 only:w-full sm:w-auto"
      style={{ borderTopColor: color }}
    >
      <div className="min-w-0">
        <Link href={`/stocks/${b.symbol}`} className="text-lg font-semibold hover:underline">
          {b.symbol}
        </Link>
        {b.name && <p className="truncate text-xs text-muted">{b.name}</p>}
        {(perf?.industry || perf?.sector) && (
          <p className="truncate text-xs text-muted">{[perf.sector, perf.industry].filter(Boolean).join(" · ")}</p>
        )}
      </div>
      <p className="text-sm">
        <span className="text-xl font-semibold tracking-tight">{close?.value ?? "no price"}</span>
        {b.as_of && <span className="ml-1.5 text-xs text-muted">close {shortDate(b.as_of)}</span>}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {b.stale && <Badge tone="warn" title="The newest stored prices are older than the latest session">old data</Badge>}
        {b.setup ? (
          <Badge tone={setupTone[b.setup.state] ?? "neutral"} title={b.setup.reasons.join("; ")}>
            setup: {b.setup.state}
          </Badge>
        ) : (
          <Badge title="No strategy has signalled this stock">no signal</Badge>
        )}
        {found && <Badge tone="accent">{SECTION_RULES[found.guide.section].label}</Badge>}
      </div>
      {found && (
        <p className="text-xs">
          <span className="text-muted">Signal: </span>
          <a href={`#how-${b.symbol}`} className="underline">
            {found.guide.name}
          </a>
          {b.research_only ? " (research only)" : " (live)"}
        </p>
      )}
      <p className="text-sm">
        <span className="text-good">{b.supporting.length} for</span>
        <span className="text-muted"> · </span>
        <span className="text-bad">{b.against.length} against</span>
        <span className="text-muted"> · </span>
        {checks.passed} of {checks.total} checks pass
      </p>
      {checks.failed.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted">
          {checks.failed.map((c) => (
            <li key={c}>
              <span className="text-bad">✗</span> {c}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <LinkButton href={`/stocks/${b.symbol}`} variant="secondary">
          Stock page
        </LinkButton>
        <LinkButton href={`/plan/${b.symbol}`} variant="ghost">
          Trade plan
        </LinkButton>
      </div>
    </section>
  );
}

function Cell({ row, i }: { row: ShownRow; i: number }) {
  const f = row.cells[i];
  if (!f) return <span className="text-muted">—</span>;
  const lead = row.leads.includes(i);
  return (
    <span className={`${stanceClass[f.stance]} ${row.small ? "text-xs" : ""}`}>
      {row.asHeadline ? `${f.label}${f.as_of ? `, ${shortDate(f.as_of)}` : ""}` : f.value}
      {lead && <LeadMark text={`${row.lead === "higher" ? "▲" : "▼"} ${row.leadText ?? (row.lead === "higher" ? "highest" : "lowest")}`} />}
    </span>
  );
}

function LeadMark({ text }: { text: string }) {
  return (
    <span className="ml-1 whitespace-nowrap rounded bg-accent-bg px-1 text-[0.65rem] font-semibold uppercase tracking-wide text-accent">
      {text}
    </span>
  );
}

function PerformanceCard({ briefs, perf }: { briefs: StockBrief[]; perf: Performance[] }) {
  const stocks = briefs.map((b) => perf.find((p) => p.symbol === b.symbol)).filter((p): p is Performance => !!p);
  const index = perf.find((p) => !briefs.some((b) => b.symbol === p.symbol));
  const lines: Line[] = [
    ...stocks.map((p, i) => ({ p, color: STOCK_COLORS[i % STOCK_COLORS.length] })),
    ...(index ? [{ p: index, color: INDEX_COLOR, dashed: true }] : []),
  ].filter((l) => l.p.series.length > 1);
  const first = lines[0]?.p.series[0]?.time;
  const n = stocks.length + (index ? 1 : 0);
  return (
    <Card
      title="Price performance"
      subtitle={`Adjusted closes rebased to 100${first ? ` on ${shortDate(first)}` : ""}, the first day all have prices: 130 means up 30% since then. Past returns, not a forecast.`}
    >
      {lines.length > 0 && <PerformanceChart lines={lines} />}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {lines.map((l) => (
          <span key={l.p.symbol} className="inline-flex items-center gap-1.5">
            <span className={`inline-block h-0.5 w-4 ${l.dashed ? "border-t border-dashed" : ""}`} style={l.dashed ? { borderColor: l.color } : { background: l.color }} />
            {l.p.symbol}
          </span>
        ))}
      </div>
      <div style={{ "--n": n } as React.CSSProperties} className="mt-4 text-sm">
        <div className={`grid ${gridCols} items-end gap-x-3 border-b border-line-strong pb-1.5`}>
          <span className="col-span-full font-semibold sm:col-span-1">Returns and risk</span>
          {stocks.map((p, i) => (
            <span key={p.symbol} className="truncate text-xs font-semibold" style={{ color: STOCK_COLORS[i % STOCK_COLORS.length] }}>
              {p.symbol}
            </span>
          ))}
          {index && <span className="truncate text-xs font-semibold text-muted">{index.symbol}</span>}
        </div>
        {performanceRows(stocks, index).map(({ row, values, index: iv, leads }) => (
          <div key={row.label} className={`grid ${gridCols} gap-x-3 gap-y-0.5 border-b border-line py-2`}>
            <span className="col-span-full text-muted sm:col-span-1">
              {row.label}
              <Help title={row.label} text={row.help} />
            </span>
            {values.map((v, i) => (
              <span key={stocks[i].symbol} className={row.signed && v !== null ? (v > 0 ? "text-good" : v < 0 ? "text-bad" : "") : ""}>
                {v === null ? <span className="text-muted">—</span> : pctText(v, 1, row.signed)}
                {leads.includes(i) && <LeadMark text={`${row.lead === "higher" ? "▲" : "▼"} ${row.leadText}`} />}
              </span>
            ))}
            {index && <span className="text-muted">{iv === null ? "—" : pctText(iv, 1, row.signed)}</span>}
          </div>
        ))}
      </div>
    </Card>
  );
}

function CompareGrid({ briefs }: { briefs: StockBrief[] }) {
  const groups = compareRows(briefs);
  return (
    <div style={{ "--n": briefs.length } as React.CSSProperties} className="text-sm">
      {groups.map((g) => (
        <div key={g.title} className="mt-4 first:mt-0">
          <div className={`grid ${gridCols} items-end gap-x-3 border-b border-line-strong pb-1.5`}>
            <h3 className="col-span-full font-semibold sm:col-span-1">{g.title}</h3>
            {briefs.map((b, i) => (
              <span key={b.symbol} className="truncate text-xs font-semibold" style={{ color: STOCK_COLORS[i % STOCK_COLORS.length] }}>
                {b.symbol}
              </span>
            ))}
          </div>
          {g.rows.map((row) => (
            <div key={row.label} className={`grid ${gridCols} gap-x-3 gap-y-0.5 border-b border-line py-2`}>
              <span className="col-span-full text-muted sm:col-span-1">
                {row.label}
                <Help title={row.label} text={row.help} />
              </span>
              {briefs.map((b, i) => (
                <span key={b.symbol} className="min-w-0 break-words">
                  <Cell row={row} i={i} />
                </span>
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ symbols?: string }> }) {
  const { symbols = "" } = await searchParams;
  const wanted = parseSymbols(symbols, MAX_COMPARE);
  const [result, rankedResult, watchResult] = await Promise.all([
    wanted.length ? getJson<CompareView>(`/stocks/compare?symbols=${encodeURIComponent(wanted.join(","))}`) : null,
    wanted.length ? null : getJson<Ranked>("/stocks/ranked?sort=score&limit=3"),
    wanted.length ? null : getJson<Watchlist>("/watchlist"),
  ]);
  const briefs = result?.ok ? result.data.briefs : [];
  const notFound = result?.ok ? result.data.not_found : [];
  const perf = result?.ok ? (result.data.performance ?? []) : [];
  const names = Object.fromEntries(briefs.map((b) => [b.symbol, b.name]));
  const top = rankedResult?.ok ? rankedResult.data.items.map((s) => s.symbol).slice(0, MAX_COMPARE) : [];
  const watched = watchResult?.ok ? watchResult.data.items.map((w) => w.ticker).slice(0, MAX_COMPARE) : [];
  const mood = briefs[0]?.facts.find((f) => f.topic === "market");
  const diffs = briefs.length > 1 ? differences(briefs) : [];
  const signalled = briefs.filter((b) => b.strategy);

  return (
    <Page>
      <PageHeader
        title="Compare stocks"
        subtitle="Up to three stocks side by side, from Jeron's own numbers. Green counts for a long trade under Jeron's rules, red against. Nothing here is a forecast or a recommendation."
        action={
          <a href="#strategies" className="text-sm underline">
            How the strategies work
          </a>
        }
      />
      <ComparePicker symbols={briefs.map((b) => b.symbol)} names={names} />
      {result && !result.ok && <Notice tone="bad">{result.error}</Notice>}
      {notFound.length > 0 && (
        <Notice tone="warn">
          No stock with prices matches {notFound.map((s) => `"${s}"`).join(", ")}. Pick from the suggestions as you type.
        </Notice>
      )}

      {!wanted.length && (
        <Card title="Start a comparison">
          <div className="space-y-3 text-sm">
            <p>
              Add two or three stocks above, by symbol, company name, short name or old symbol, or press Compare on any stock&apos;s
              page. Each stock gets a column; rows with a clear direction mark the highest or lowest, and a summary lists where Jeron&apos;s
              rules read them differently.
            </p>
            {(top.length > 1 || watched.length > 1) && (
              <div className="flex flex-wrap gap-2">
                {top.length > 1 && (
                  <LinkButton href={compareHref(top)} variant="secondary">
                    Top of the latest scan: {top.join(", ")}
                  </LinkButton>
                )}
                {watched.length > 1 && (
                  <LinkButton href={compareHref(watched)} variant="secondary">
                    Your watchlist: {watched.join(", ")}
                  </LinkButton>
                )}
              </div>
            )}
          </div>
        </Card>
      )}

      {briefs.length > 0 && (
        <>
          {briefs.length === 1 && <Notice>Add one or two more stocks to see them side by side.</Notice>}
          {mood && (
            <p className="text-sm">
              <span className="text-muted">Market mood, the same for every stock: </span>
              <span className={stanceClass[mood.stance]}>{mood.value}</span>
            </p>
          )}
          {briefs.some((b) => b.stale) && (
            <Notice tone="warn">
              Some prices are older than the latest session: read each column as of its own date.
            </Notice>
          )}
          {/* Phones: the cards side by side in a row that swipes; wider: a grid. */}
          <div
            className={`-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:overflow-visible sm:px-0 sm:pb-0 ${briefs.length === 2 ? "sm:grid-cols-2" : briefs.length === 3 ? "sm:grid-cols-2 lg:grid-cols-3" : ""}`}
          >
            {briefs.map((b, i) => (
              <StockCard key={b.symbol} b={b} color={STOCK_COLORS[i % STOCK_COLORS.length]} perf={perf.find((p) => p.symbol === b.symbol)} />
            ))}
          </div>

          {perf.some((p) => p.series.length > 1) && <PerformanceCard briefs={briefs} perf={perf} />}

          {diffs.length > 0 && (
            <Card title="Where they differ" subtitle="Rows where Jeron's rules count one stock for a long trade and another against.">
              <ul className="space-y-1 text-sm">
                {diffs.map((d) => (
                  <li key={d.label}>
                    <span className="font-medium">{d.label}: </span>
                    <span className="text-good">for {d.forSymbols.join(", ")}</span>
                    <span className="text-muted">; </span>
                    <span className="text-bad">against {d.againstSymbols.join(", ")}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card
            title="Side by side"
            subtitle="Tap ? for what a row means. ▲ or ▼ marks the number Jeron's rules treat as stronger on that row; it is not a pick."
          >
            <CompareGrid briefs={briefs} />
            <p className="mt-3 text-xs text-muted">
              Counting green and red is a summary, not a score: one hard reject or a results blackout can matter more than several
              green lines. Open a stock for every fact&apos;s source and date.
            </p>
          </Card>

          <Card
            title="How to use the signals"
            subtitle="What each strategy looks for, when it works, and the steps from signal to exit."
          >
            {signalled.length ? (
              <div className={`grid gap-5 ${signalled.length > 1 ? "lg:grid-cols-2" : ""}`}>
                {signalled.map((b) => (
                  <div key={b.symbol} id={`how-${b.symbol}`} className="min-w-0 scroll-mt-20">
                    <h3 className="mb-1 font-semibold">{b.symbol}</h3>
                    <SignalHowTo brief={b} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">
                None of these has a signal: no backtested strategy has a reason to buy them now. A strong score alone isn&apos;t a
                signal; the strategies below say what each one waits for.
              </p>
            )}
          </Card>
        </>
      )}

      <section id="strategies" className="scroll-mt-20">
        <Card
          title="The strategies at a glance"
          subtitle="Every strategy Jeron paper-trades. Each signal says whether its strategy is live (passed all seven backtest checks) or research only."
          action={
            <Link href="/learn" className="underline">
              Learn
            </Link>
          }
        >
          <details open={!wanted.length || (briefs.length > 0 && signalled.length === 0)}>
            <summary className="mb-2 cursor-pointer text-sm font-medium">Show all strategies</summary>
            <StrategiesAtAGlance />
            <p className="mt-3 text-sm">
              Every trade runs the same way after the entry:{" "}
              <Link href="/learn/signals-and-exits" className="underline">
                from signal to exit
              </Link>
              . How a strategy earns live signals:{" "}
              <Link href="/learn/how-jeron-tests" className="underline">
                how Jeron tests
              </Link>
              .
            </p>
          </details>
        </Card>
      </section>
      {!wanted.length && !top.length && !watched.length && (
        <EmptyState>No scan yet, so there is nothing to suggest. Search for any stock with prices above.</EmptyState>
      )}
    </Page>
  );
}
