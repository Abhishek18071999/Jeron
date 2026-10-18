import Link from "next/link";

import { RRuler } from "@/components/trade-picture";
import { WatchStar } from "@/components/watch-star";
import { Card, LinkButton, ResearchBadge, inr, rMultiple, shortDate } from "@/components/ui";
import { NewsCard } from "@/components/news";
import {
  type NewsView,
  type StockDeals,
  type StockFundamentals,
  type StockView,
  type Watchlist,
  getJson,
} from "@/lib/api";

import { signClass } from "../../backtests/format";
import { type Level, PriceChart } from "./chart";
import { DealsPanel } from "./deals";
import { FundamentalsPanel } from "./fundamentals";

export const dynamic = "force-dynamic";

export default async function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const [result, watch, deals, fundamentals, news] = await Promise.all([
    getJson<StockView>(`/stocks/${encodeURIComponent(symbol)}?sessions=500`),
    getJson<Watchlist>("/watchlist"),
    getJson<StockDeals>(`/stocks/${encodeURIComponent(symbol)}/deals`),
    getJson<StockFundamentals>(`/stocks/${encodeURIComponent(symbol)}/fundamentals`),
    getJson<NewsView>(`/stocks/${encodeURIComponent(symbol)}/news`),
  ]);
  if (!result.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{decodeURIComponent(symbol).toUpperCase()}</h1>
        <p className="mt-4 text-bad">{result.error}</p>
      </main>
    );
  }
  const s = result.data;
  const watched = watch.ok && watch.data.items.some((i) => i.ticker === s.symbol);
  const latest = s.signals[0];
  // An open position of mine comes first: its average entry and stop, and its signal's
  // targets. Otherwise the latest signal's zone, stop and targets.
  const held = s.journal.find((e) => e.position.status === "open" && e.position.avg_entry);
  const levels: Level[] = held
    ? [
        { price: Number(held.position.avg_entry), title: "My entry", color: "#2563eb" },
        ...(held.stop ? [{ price: Number(held.stop), title: "Stop", color: "#dc2626" }] : []),
        ...(held.signal
          ? [
              { price: Number(held.signal.t1), title: "T1", color: "#16a34a" },
              { price: Number(held.signal.t2), title: "T2", color: "#16a34a", dashed: true },
            ]
          : []),
      ]
    : latest
      ? [
          { price: Number(latest.chart.entry_high), title: "Entry high", color: "#2563eb", dashed: true },
          { price: Number(latest.chart.entry_low), title: "Entry low", color: "#2563eb", dashed: true },
          { price: Number(latest.chart.stop), title: "Stop", color: "#dc2626" },
          { price: Number(latest.chart.t1), title: "T1", color: "#16a34a" },
          { price: Number(latest.chart.t2), title: "T2", color: "#16a34a", dashed: true },
        ]
      : [];
  const last = s.candles[s.candles.length - 1];
  const scan = s.latest_scan;

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-x-2 text-xl font-semibold tracking-tight sm:text-2xl">
            {s.symbol}
            <WatchStar ticker={s.symbol} watched={watched} back={`/stocks/${s.symbol}`} />
            {s.name && <span className="text-base font-normal text-muted">{s.name}</span>}
          </h1>
          <p className="text-sm text-muted">
            {[s.series, s.sector, s.industry].filter(Boolean).join(" · ")}
            {last && ` · close ${inr(last.close)} on ${shortDate(last.time)}`}
            {scan && ` · technical score ${Number(scan.score).toFixed(1)} (rank ${scan.rank})`}
          </p>
        </div>
        <LinkButton
          href={latest ? `/plan/${s.symbol}?signal=${latest.signal.signal_id}` : `/plan/${s.symbol}`}
          variant="primary"
        >
          Plan trade
        </LinkButton>
      </div>

      <Card title="Price (split/bonus-adjusted)">
        <PriceChart candles={s.candles} levels={levels} />
        <p className="mt-2 text-xs text-muted">
          Blue: EMA 50, purple: EMA 200.
          {held
            ? " Lines: my open position's entry and stop, and its signal's targets."
            : latest
              ? ` Lines: the ${shortDate(latest.signal.signal_date)} signal's entry zone, stop and targets.`
              : " No signal for this stock yet."}
        </p>
        {held ? (
          <RRuler
            entry={held.position.avg_entry}
            stop={held.signal?.stop ?? held.stop}
            price={held.last_close}
            t1={held.signal?.t1}
            t2={held.signal?.t2}
          />
        ) : (
          latest &&
          last && (
            <RRuler
              entry={latest.signal.entry_high}
              stop={latest.signal.stop}
              price={last.close}
              t1={latest.signal.t1}
              t2={latest.signal.t2}
            />
          )
        )}
      </Card>

      {latest && (
        <Card title="Latest signal">
          <div className="space-y-2 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <ResearchBadge research={latest.signal.research_only} />
              <span className="font-medium">{latest.payload.setup_name}</span>
              <span className="text-muted">
                {latest.payload.strategy_version} · {shortDate(latest.signal.signal_date)} · conviction{" "}
                {latest.signal.conviction}/5
              </span>
            </p>
            <p>
              Buy {inr(latest.signal.entry_low)}-{inr(latest.signal.entry_high)} until{" "}
              {shortDate(latest.signal.valid_until)} · stop {inr(latest.signal.stop)} · T1 {inr(latest.signal.t1)} · T2{" "}
              {inr(latest.signal.t2)} · {latest.signal.shares} shares, {inr(latest.signal.capital_at_risk, 0)}{" "}
              at risk
            </p>
            <ul className="list-disc pl-5">
              {latest.payload.why.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <p className="text-muted">
              Brains: technical {Number(latest.payload.brains_breakdown.technical).toFixed(0)}. Event risk:{" "}
              {latest.payload.event_risk.replace(/\.$/, "")}.
            </p>
            <p className="text-muted">
              Backtest (out of sample, after costs): {latest.payload.backtest_stats.trades} trades, expectancy{" "}
              {Number(latest.payload.backtest_stats.expectancy_R).toFixed(2)}R, profit factor{" "}
              {latest.payload.backtest_stats.profit_factor ?? "n/a"}, max drawdown{" "}
              {Number(latest.payload.backtest_stats.max_drawdown_pct).toFixed(1)}% ·{" "}
              <Link href="/backtests" className="underline">
                report cards
              </Link>
            </p>
            <p className="flex flex-wrap gap-4">
              <Link href={`/plan/${s.symbol}?signal=${latest.signal.signal_id}`} className="font-medium text-accent underline">
                Plan this trade
              </Link>
              <Link href={`/journal/signal/${latest.signal.signal_id}`} className="underline">
                Record what I did
              </Link>
            </p>
          </div>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Technical score">
          {scan ? (
            <div className="space-y-2 text-sm">
              <ScoreSpark points={s.scores.map((p) => Number(p.score))} />
              <table className="w-full">
                <tbody>
                  {scan.components.map((c) => (
                    <tr key={c.key} className="border-t border-line">
                      <td className="py-1">{c.label}</td>
                      <td className="text-right">
                        {Number(c.points).toFixed(1).replace(/\.0$/, "")} / {c.max_points}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-muted">Not in a scan&apos;s universe.</p>
          )}
        </Card>
        <Card title="Signals and trades">
          <div className="space-y-3 text-sm">
            {s.signals.length === 0 && <p className="text-muted">No signals.</p>}
            {s.signals.map((x) => (
              <p key={x.signal.signal_id} className="flex flex-wrap items-center gap-2">
                <span>{shortDate(x.signal.signal_date)}</span>
                <ResearchBadge research={x.signal.research_only} />
                <span className="text-muted">{x.signal.strategy_key}</span>
                <Link href={`/journal/signal/${x.signal.signal_id}`} className="underline">
                  journal
                </Link>
              </p>
            ))}
            {s.paper_trades.map((t) => (
              <p key={`${t.account_id}-${t.entry_date}`}>
                Paper ({t.strategy_key}): {shortDate(t.entry_date)} at {inr(t.entry_price)}
                {t.exit_date ? `, out ${shortDate(t.exit_date)} (${t.exit_reason})` : ", open"}{" "}
                <span className={signClass(t.r_multiple)}>{rMultiple(t.r_multiple)}</span>
              </p>
            ))}
            {s.journal.map((e) => (
              <p key={e.id}>
                <Link href={`/journal/${e.id}`} className="underline">
                  Journal
                </Link>
                : {e.decision}, {e.position.status}{" "}
                <span className={signClass(e.position.r_multiple ?? 0)}>
                  {rMultiple(e.position.r_multiple)}
                </span>
              </p>
            ))}
          </div>
        </Card>
      </div>
      <FundamentalsPanel
        data={fundamentals.ok ? fundamentals.data : null}
        error={fundamentals.ok ? undefined : fundamentals.error}
      />
      <NewsCard
        title="News"
        news={news.ok ? news.data : null}
        empty="No company announcements stored for this stock yet."
      />
      <DealsPanel data={deals.ok ? deals.data : null} error={deals.ok ? undefined : deals.error} />
    </main>
  );
}

function ScoreSpark({ points }: { points: number[] }) {
  if (points.length < 5) return null;
  const W = 300;
  const H = 50;
  const d = points
    .map(
      (v, i) =>
        `${i ? "L" : "M"}${((i / (points.length - 1)) * W).toFixed(1)},${(H - (v / 100) * H).toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-12 w-full" role="img" aria-label="Score history">
      <path d={d} fill="none" className="stroke-accent" strokeWidth={1.5} />
    </svg>
  );
}
