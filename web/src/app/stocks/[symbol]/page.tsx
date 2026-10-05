import Link from "next/link";

import { Card, ResearchBadge, inr, rMultiple } from "@/components/ui";
import { type StockView, getJson } from "@/lib/api";

import { signClass } from "../../backtests/format";
import { type Level, PriceChart } from "./chart";

export const dynamic = "force-dynamic";

export default async function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const result = await getJson<StockView>(`/stocks/${encodeURIComponent(symbol)}?sessions=500`);
  if (!result.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{decodeURIComponent(symbol).toUpperCase()}</h1>
        <p className="mt-4 text-bad">{result.error}</p>
      </main>
    );
  }
  const s = result.data;
  const latest = s.signals[0];
  const levels: Level[] = latest
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
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          {s.symbol}
          {s.name && <span className="ml-2 text-base font-normal text-muted">{s.name}</span>}
        </h1>
        <p className="text-sm text-muted">
          {[s.series, s.sector, s.industry].filter(Boolean).join(" · ")}
          {last && ` · close ${inr(last.close)} on ${last.time}`}
          {scan && ` · technical score ${Number(scan.score).toFixed(1)} (rank ${scan.rank})`}
        </p>
      </div>

      <Card title="Price (split/bonus-adjusted)">
        <PriceChart candles={s.candles} levels={levels} />
        <p className="mt-2 text-xs text-muted">
          Blue: EMA 50, purple: EMA 200.
          {latest
            ? ` Lines: the ${latest.signal.signal_date} signal's entry zone, stop and targets.`
            : " No signal for this stock yet."}
        </p>
      </Card>

      {latest && (
        <Card title="Latest signal">
          <div className="space-y-2 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <ResearchBadge research={latest.signal.research_only} />
              <span className="font-medium">{latest.payload.setup_name}</span>
              <span className="text-muted">
                {latest.payload.strategy_version} · {latest.signal.signal_date} · conviction{" "}
                {latest.signal.conviction}/5
              </span>
            </p>
            <p>
              Buy {inr(latest.signal.entry_low)}-{inr(latest.signal.entry_high)} until{" "}
              {latest.signal.valid_until} · stop {inr(latest.signal.stop)} · T1 {inr(latest.signal.t1)} · T2{" "}
              {inr(latest.signal.t2)} · {latest.signal.shares} shares, {inr(latest.signal.capital_at_risk, 0)}{" "}
              at risk
            </p>
            <ul className="list-disc pl-5">
              {latest.payload.why.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <p className="text-muted">
              Brains: technical {Number(latest.payload.brains_breakdown.technical).toFixed(0)}, fundamental
              and news arrive in M6. Event risk: {latest.payload.event_risk.replace(/\.$/, "")}.
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
            <Link href={`/journal/signal/${latest.signal.signal_id}`} className="underline">
              Record what I did
            </Link>
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
                <span>{x.signal.signal_date}</span>
                <ResearchBadge research={x.signal.research_only} />
                <span className="text-muted">{x.signal.strategy_key}</span>
                <Link href={`/journal/signal/${x.signal.signal_id}`} className="underline">
                  journal
                </Link>
              </p>
            ))}
            {s.paper_trades.map((t) => (
              <p key={`${t.account_id}-${t.entry_date}`}>
                Paper ({t.strategy_key}): {t.entry_date} at {inr(t.entry_price)}
                {t.exit_date ? `, out ${t.exit_date} (${t.exit_reason})` : ", open"}{" "}
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
      <p className="text-xs text-muted">Fundamentals, news and the results countdown arrive with M6.</p>
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
