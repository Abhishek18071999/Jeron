import Link from "next/link";

import {
  getJson,
  type BacktestTrade,
  type BacktestView,
  type CurveStats,
  type EquityPoint,
  type TradeStats,
} from "@/lib/api";

import { num, pct, rupees, signClass } from "../format";

export const dynamic = "force-dynamic";

const W = 900;
const H = 220;

function path(values: (number | null)[], min: number, max: number, height: number) {
  const span = max - min || 1;
  const step = values.length > 1 ? W / (values.length - 1) : W;
  let d = "";
  values.forEach((v, i) => {
    if (v === null) return;
    const x = (i * step).toFixed(1);
    const y = (height - ((v - min) / span) * height).toFixed(1);
    d += `${d === "" ? "M" : "L"}${x},${y}`;
  });
  return d;
}

function EquityChart({ points, holdoutStart }: { points: EquityPoint[]; holdoutStart: string }) {
  if (points.length < 2) return null;
  const equity = points.map((p) => p.equity);
  const bench = points.map((p) => p.benchmark);
  const all = [...equity, ...bench.filter((b): b is number => b !== null)];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const dd = points.map((p) => -p.drawdown_pct);
  const ddMin = Math.min(...dd, -1);
  const split = points.findIndex((p) => p.date >= holdoutStart);
  const splitX = split > 0 ? (split / (points.length - 1)) * W : null;
  const years = points
    .map((p, i) => ({ i, year: p.date.slice(0, 4) }))
    .filter((p, k, arr) => k === 0 || p.year !== arr[k - 1].year);
  return (
    <figure className="mt-4">
      <svg viewBox={`0 0 ${W} ${H + 110}`} className="w-full" role="img" aria-label="Equity curve">
        {splitX !== null && (
          <>
            <rect x={splitX} y={0} width={W - splitX} height={H + 90} className="fill-amber-100/60 dark:fill-amber-900/20" />
            <text x={splitX + 4} y={12} className="fill-amber-700 text-[11px] dark:fill-amber-400">
              holdout
            </text>
          </>
        )}
        <path d={path(bench, min, max, H)} className="fill-none stroke-neutral-400" strokeWidth={1.5} strokeDasharray="4 3" />
        <path d={path(equity, min, max, H)} className="fill-none stroke-green-700 dark:stroke-green-400" strokeWidth={2} />
        <g transform={`translate(0, ${H + 10})`}>
          <path d={`${path(dd, ddMin, 0, 70)}L${W},0L0,0Z`} className="fill-red-200 dark:fill-red-900/50" />
          <text x={4} y={66} className="fill-neutral-500 text-[11px]">
            drawdown (deepest {num(-ddMin, 1)}%)
          </text>
        </g>
        {years.map(({ i, year }) => (
          <text key={year} x={(i / (points.length - 1)) * W + 2} y={H + 102} className="fill-neutral-500 text-[11px]">
            {year}
          </text>
        ))}
      </svg>
      <figcaption className="text-xs text-neutral-500">
        Green: strategy equity from {rupees(points[0].equity)}. Dashed grey: Nifty 500 bought and held from the same
        day. Red: the strategy&apos;s drawdown from its peak.
      </figcaption>
    </figure>
  );
}

function StatsTable({ rows }: { rows: { label: string; trades: TradeStats; curve: CurveStats | null }[] }) {
  return (
    <table className="mt-3 w-full text-sm">
      <thead className="text-left text-neutral-500">
        <tr>
          <th className="py-1 pr-3"></th>
          <th className="pr-3 text-right">Trades</th>
          <th className="pr-3 text-right">Win rate</th>
          <th className="pr-3 text-right">Avg win / loss</th>
          <th className="pr-3 text-right">Expectancy</th>
          <th className="pr-3 text-right">Profit factor</th>
          <th className="pr-3 text-right">Net P&amp;L</th>
          <th className="pr-3 text-right">CAGR</th>
          <th className="pr-3 text-right">Max DD</th>
          <th className="text-right">Sharpe</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ label, trades: t, curve: c }) => (
          <tr key={label} className="border-t border-neutral-200 dark:border-neutral-800">
            <td className="py-1 pr-3">{label}</td>
            <td className="pr-3 text-right">{t.trades}</td>
            <td className="pr-3 text-right">{pct(t.win_rate)}</td>
            <td className="pr-3 text-right">
              {num(t.avg_win_r)}R / {num(t.avg_loss_r)}R
            </td>
            <td className={`pr-3 text-right ${signClass(t.expectancy_r)}`}>{num(t.expectancy_r, 3)}R</td>
            <td className="pr-3 text-right">{num(t.profit_factor)}</td>
            <td className={`pr-3 text-right ${signClass(t.net_pnl)}`}>{rupees(t.net_pnl)}</td>
            <td className="pr-3 text-right">{c ? pct(c.cagr) : "-"}</td>
            <td className="pr-3 text-right">{c ? `${num(c.max_drawdown_pct, 1)}%` : "-"}</td>
            <td className="text-right">{c ? num(c.sharpe) : "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Counts({ title, counts }: { title: string; counts: Record<string, number> }) {
  return (
    <div>
      <h3 className="font-medium">{title}</h3>
      <table className="mt-1 text-sm">
        <tbody>
          {Object.entries(counts).map(([k, v]) => (
            <tr key={k}>
              <td className="pr-4">{k}</td>
              <td className="text-right">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ trades }: { trades: BacktestTrade[] }) {
  return (
    <div className="mt-3 max-h-[36rem] overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-white text-left text-neutral-500 dark:bg-neutral-950">
          <tr>
            <th className="py-1 pr-2">#</th>
            <th className="pr-2">Stock</th>
            <th className="pr-2">Entry</th>
            <th className="pr-2">Exit</th>
            <th className="pr-2 text-right">Shares</th>
            <th className="pr-2 text-right">Buy</th>
            <th className="pr-2 text-right">Stop</th>
            <th className="pr-2 text-right">Sell (avg)</th>
            <th className="pr-2">Exit reason</th>
            <th className="pr-2 text-right">Costs</th>
            <th className="pr-2 text-right">Net P&amp;L</th>
            <th className="pr-2 text-right">R</th>
            <th className="pr-2">Regime</th>
            <th>Set</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.seq} className="border-t border-neutral-100 dark:border-neutral-900">
              <td className="py-0.5 pr-2 text-neutral-500">{t.seq}</td>
              <td className="pr-2">
                <Link href={`/spot-check?symbol=${encodeURIComponent(t.symbol)}&date=${t.entry_date}`} className="underline">
                  {t.symbol}
                </Link>
              </td>
              <td className="pr-2">{t.entry_date}</td>
              <td className="pr-2">{t.exit_date}</td>
              <td className="pr-2 text-right">{t.shares}</td>
              <td className="pr-2 text-right">{num(t.entry_price)}</td>
              <td className="pr-2 text-right">{num(t.stop_price)}</td>
              <td className="pr-2 text-right">{num(t.exit_price)}</td>
              <td className="pr-2">{t.exit_reason}</td>
              <td className="pr-2 text-right">{rupees(t.charges)}</td>
              <td className={`pr-2 text-right ${signClass(t.net_pnl)}`}>{rupees(t.net_pnl)}</td>
              <td className={`pr-2 text-right font-medium ${signClass(t.r_multiple)}`}>{num(t.r_multiple)}</td>
              <td className="pr-2">{t.regime}</td>
              <td>{t.segment === "holdout" ? "holdout" : "test"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function BacktestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [view, trades] = await Promise.all([
    getJson<BacktestView>(`/backtests/${id}`),
    getJson<BacktestTrade[]>(`/backtests/${id}/trades`),
  ]);
  if (!view.ok) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8">
        <p className="text-neutral-600 dark:text-neutral-400">{view.error}</p>
      </main>
    );
  }
  const { run, summary, equity, variants } = view.data;
  const oos = summary.out_of_sample;
  const years = Object.keys(oos.yearly_returns);
  const sortedTrades = trades.ok ? trades.data : [];
  const worst = [...sortedTrades].sort((a, b) => Number(a.r_multiple) - Number(b.r_multiple)).slice(0, 5);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <Link href="/backtests" className="text-sm text-neutral-500 underline">
        All backtests
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">{run.strategy_name}</h1>
      <p className="mt-1 text-sm text-neutral-500">
        {run.strategy_version} ({run.tier}). Run {run.id} of {view.data.runs_of_strategy} for this strategy, on{" "}
        {run.created_at.slice(0, 10)}. Data {summary.periods.data[0]} to {summary.periods.data[1]} (fingerprint{" "}
        {run.fingerprint}). Tested {summary.periods.out_of_sample[0]} to {summary.periods.out_of_sample[1]}; holdout{" "}
        {summary.periods.holdout[0]} to {summary.periods.holdout[1]}.
      </p>

      <section
        className={`mt-6 rounded-lg border px-4 py-3 ${
          run.live_eligible ? "border-green-300 dark:border-green-800" : "border-red-300 dark:border-red-800"
        }`}
      >
        <p className={`font-semibold ${run.live_eligible ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}`}>
          {run.live_eligible
            ? "Live-eligible: passes every check, out of sample and after costs."
            : "Not live-eligible: it fails at least one check below. Jeron will not issue signals from it."}
        </p>
        <ul className="mt-2 text-sm">
          {summary.gates.map((g) => (
            <li key={g.key}>
              <span className={g.passed ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}>
                {g.passed ? "✓" : "✗"}
              </span>{" "}
              {g.label}: <span className="font-medium">{g.value}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-neutral-500">
          Deflated Sharpe ratio {num(oos.deflated_sharpe, 3)} after {oos.variants_tried} variants tried (0.95 or more
          means the result is unlikely to be luck from trying several settings).
        </p>
      </section>

      <h2 className="mt-8 text-lg font-semibold">Results</h2>
      <StatsTable
        rows={[
          { label: "Walk-forward test", trades: oos.trades, curve: oos.curve },
          { label: "Final 12-month holdout", trades: summary.holdout.trades, curve: summary.holdout.curve },
        ]}
      />
      <p className="mt-2 text-sm text-neutral-500">
        Nifty 500 over the test period: CAGR {pct(oos.benchmark.cagr)}, max drawdown{" "}
        {num(oos.benchmark.max_drawdown_pct, 1)}%, Sharpe {num(oos.benchmark.sharpe)}. Over the holdout: CAGR{" "}
        {pct(summary.holdout.benchmark.cagr)}, Sharpe {num(summary.holdout.benchmark.sharpe)}.
      </p>
      <EquityChart points={equity} holdoutStart={summary.periods.holdout[0]} />

      <div className="mt-8 grid gap-8 md:grid-cols-2">
        <div>
          <h2 className="text-lg font-semibold">By year (test period)</h2>
          <table className="mt-2 w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr>
                <th className="py-1 pr-3">Year</th>
                <th className="pr-3 text-right">Trades</th>
                <th className="pr-3 text-right">Expectancy</th>
                <th className="pr-3 text-right">Return</th>
                <th className="text-right">Nifty 500</th>
              </tr>
            </thead>
            <tbody>
              {years.map((y) => (
                <tr key={y} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-1 pr-3">{y}</td>
                  <td className="pr-3 text-right">{oos.by_year[y]?.trades ?? 0}</td>
                  <td className={`pr-3 text-right ${signClass(oos.by_year[y]?.expectancy_r ?? 0)}`}>
                    {num(oos.by_year[y]?.expectancy_r ?? 0, 3)}R
                  </td>
                  <td className={`pr-3 text-right ${signClass(oos.yearly_returns[y])}`}>{pct(oos.yearly_returns[y])}</td>
                  <td className="text-right">{pct(oos.benchmark_yearly_returns[y])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h2 className="text-lg font-semibold">By market regime (test period)</h2>
          <table className="mt-2 w-full text-sm">
            <thead className="text-left text-neutral-500">
              <tr>
                <th className="py-1 pr-3">Regime at signal</th>
                <th className="pr-3 text-right">Trades</th>
                <th className="pr-3 text-right">Win rate</th>
                <th className="pr-3 text-right">Expectancy</th>
                <th className="text-right">Profit factor</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(oos.by_regime).map(([k, t]) => (
                <tr key={k} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-1 pr-3">{k}</td>
                  <td className="pr-3 text-right">{t.trades}</td>
                  <td className="pr-3 text-right">{pct(t.win_rate)}</td>
                  <td className={`pr-3 text-right ${signClass(t.expectancy_r)}`}>{num(t.expectancy_r, 3)}R</td>
                  <td className="text-right">{num(t.profit_factor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-neutral-500">
            Bull: Nifty 500 above its 200-day EMA and the EMA rising over 20 sessions. Bear: below and falling.
            Sideways: anything else.
          </p>
        </div>
      </div>

      <div className="mt-8 grid gap-8 md:grid-cols-3">
        <Counts title="How trades ended" counts={summary.exit_reasons} />
        <Counts title="Signals not taken" counts={summary.skipped_entries} />
        <div>
          <h3 className="font-medium">Estimated tax (test period)</h3>
          <p className="mt-1 text-sm">
            Pre-tax {rupees(oos.tax.pre_tax_pnl)}
            {oos.tax.interest !== undefined && <> (including {rupees(oos.tax.interest)} interest on idle cash)</>}, tax about {rupees(oos.tax.estimated_tax)}, post-tax{" "}
            <span className={signClass(oos.tax.post_tax_pnl)}>{rupees(oos.tax.post_tax_pnl)}</span>.
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            STCG 15% (20% from 23 July 2024), LTCG 10%/12.5% above the exemption, dividends and interest on idle cash at a 30% slab; surcharge
            and cess left out.
          </p>
        </div>
      </div>

      {worst.length > 0 && (
        <>
          <h2 className="mt-8 text-lg font-semibold">Worst trades</h2>
          <TradesTable trades={worst} />
        </>
      )}

      <h2 className="mt-8 text-lg font-semibold">Rules in plain language</h2>
      <ul className="mt-2 list-disc pl-6 text-sm">
        {summary.rules.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>

      <h2 className="mt-8 text-lg font-semibold">Walk-forward settings</h2>
      <p className="mt-1 text-sm text-neutral-500">
        Each window traded the setting with the best training Sharpe ratio (at least 30 training trades) on everything
        before it. Every setting tried is listed.
      </p>
      <ul className="mt-2 text-sm">
        {summary.schedule.map((s) => (
          <li key={s.from}>
            From {s.from}: {s.variant}
          </li>
        ))}
      </ul>
      <details className="mt-2">
        <summary className="cursor-pointer text-sm text-neutral-500">All {variants.length} variant results</summary>
        <table className="mt-2 text-xs">
          <thead className="text-left text-neutral-500">
            <tr>
              <th className="pr-3">Window</th>
              <th className="pr-3">Setting</th>
              <th className="pr-3">Trained on</th>
              <th className="pr-3 text-right">Trades</th>
              <th className="pr-3 text-right">Expectancy</th>
              <th className="pr-3 text-right">Sharpe</th>
              <th>Chosen</th>
            </tr>
          </thead>
          <tbody>
            {variants.map((v, i) => (
              <tr key={i} className={v.chosen ? "font-semibold" : ""}>
                <td className="pr-3">{v.window}</td>
                <td className="pr-3">{v.label}</td>
                <td className="pr-3">
                  {v.train_start} to {v.train_end}
                </td>
                <td className="pr-3 text-right">{v.trades}</td>
                <td className="pr-3 text-right">{num(v.expectancy_r, 3)}R</td>
                <td className="pr-3 text-right">{num(v.sharpe)}</td>
                <td>{v.chosen ? "yes" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {summary.notes.length > 0 && (
        <>
          <h2 className="mt-8 text-lg font-semibold">Caveats</h2>
          <ul className="mt-2 list-disc pl-6 text-sm text-amber-700 dark:text-amber-400">
            {summary.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}

      <h2 className="mt-8 text-lg font-semibold">All trades ({sortedTrades.length})</h2>
      <p className="text-sm text-neutral-500">
        Prices are adjusted for splits and bonuses; shares are as bought. Losses in red.
      </p>
      <TradesTable trades={sortedTrades} />
    </main>
  );
}
