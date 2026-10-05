import Link from "next/link";

import { getJson, type ScanResult, type ScanRunSummary, type ScanView } from "@/lib/api";

export const dynamic = "force-dynamic";

type Search = { date?: string; min?: string; open?: string };

const num = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined ? "-" : value.toFixed(digits);
const pct = (value: number | null | undefined) =>
  value === null || value === undefined ? "-" : `${(value * 100).toFixed(1)}%`;

function ScoreBar({ result }: { result: ScanResult }) {
  return (
    <div className="flex h-2 w-32 overflow-hidden rounded bg-surface-2">
      {result.components.map((c) => (
        <div
          key={c.key}
          title={`${c.label}: ${c.points} of ${c.max_points}`}
          className={c.points > 0 ? "bg-fg/60" : ""}
          style={{ width: `${c.points}%` }}
        />
      ))}
    </div>
  );
}

function Breakdown({ result }: { result: ScanResult }) {
  const i = result.indicators;
  return (
    <div className="grid gap-4 py-3 md:grid-cols-2">
      <table className="text-sm">
        <tbody>
          {result.components.map((c) => (
            <tr key={c.key}>
              <td className="pr-3">{c.label}</td>
              <td className="pr-3 text-right text-muted">{num(c.value, 2)}</td>
              <td className={`text-right ${c.points > 0 ? "text-good" : ""}`}>
                {c.points} / {c.max_points}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="grid grid-cols-2 gap-x-4 text-sm">
        <dt className="text-muted">EMA 20 / 50 / 200</dt>
        <dd>
          {num(i.ema20)} / {num(i.ema50)} / {num(i.ema200)}
        </dd>
        <dt className="text-muted">MACD / signal</dt>
        <dd>
          {num(i.macd, 2)} / {num(i.macd_signal, 2)}
        </dd>
        <dt className="text-muted">ADX / +DI / -DI</dt>
        <dd>
          {num(i.adx14)} / {num(i.plus_di)} / {num(i.minus_di)}
        </dd>
        <dt className="text-muted">ATR 14</dt>
        <dd>
          {num(i.atr14, 2)} ({num(i.atr_pct)}%)
        </dd>
        <dt className="text-muted">52-week high</dt>
        <dd>
          {num(i.high_52w, 2)} ({num(i.below_52w_high_pct)}% below)
        </dd>
        <dt className="text-muted">Return 3m / 6m</dt>
        <dd>
          {pct(i.return_3m)} / {pct(i.return_6m)}
        </dd>
        <dt className="text-muted">Support / resistance</dt>
        <dd>
          {num(i.support, 2)} / {num(i.resistance, 2)}
        </dd>
        <dt className="text-muted">Avg volume (20 days)</dt>
        <dd>{i.avg_volume20 === null ? "-" : Math.round(i.avg_volume20).toLocaleString("en-IN")}</dd>
        <dt className="text-muted">History used</dt>
        <dd>{i.sessions} sessions</dd>
      </dl>
    </div>
  );
}

function RunBanner({ view }: { view: ScanView }) {
  const { run, details } = view;
  if (run.status === "blocked") {
    return (
      <section className="mt-6 rounded-xl border border-bad/40 bg-bad-bg px-4 py-3">
        <p className="font-semibold text-bad">
          The scan for {run.trade_date} did not run.
        </p>
        <ul className="mt-2 list-disc pl-6 text-sm">
          {run.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </section>
    );
  }
  return (
    <section className="mt-6 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
      <p>
        <span className="font-semibold">{run.trade_date}</span>: {run.universe_size} stocks in the
        universe out of {details.candidates ?? "?"} that traded recently. Scan took{" "}
        {run.duration_seconds ?? "?"} s. Score {run.score_version}. GSM list as of {details.security_list_date ?? "-"}; ASM
        list as of {details.asm_list_date ?? "never imported"}.
      </p>
      {details.exclusions && (
        <details className="mt-2">
          <summary className="cursor-pointer text-muted">Why stocks were left out</summary>
          <table className="mt-2">
            <tbody>
              {details.exclusions.map((e) => (
                <tr key={e.rule}>
                  <td className="pr-4">{e.label}</td>
                  <td className="pr-4 text-right">{e.count}</td>
                  <td className="text-muted">{e.symbols.slice(0, 15).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {details.notes && details.notes.length > 0 && (
        <ul className="mt-2 list-disc pl-6 text-warn">
          {details.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default async function ScannerPage({ searchParams }: { searchParams: Promise<Search> }) {
  const { date, min, open } = await searchParams;
  const minScore = Number(min ?? "0") || 0;
  const path = date ? `/scan/${date}` : "/scan/latest";
  const [view, runs] = await Promise.all([
    getJson<ScanView>(`${path}?limit=500&min_score=${minScore}`),
    getJson<ScanRunSummary[]>("/scan/runs?limit=30"),
  ]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Scanner</h1>
      <p className="mt-2 text-muted">
        Technical score (0 to 100) for every stock in the day&apos;s universe. This is the technical
        brain only, with starting weights the backtester will test; it is a list to research, not a
        list of trades.
      </p>

      <form className="mt-6 flex flex-wrap items-end gap-3 text-sm" action="/scanner">
        <label className="flex flex-col">
          Day
          <select
            name="date"
            defaultValue={date ?? ""}
            className="rounded-lg border border-line-strong bg-surface px-2.5 py-1.5"
          >
            <option value="">Latest</option>
            {runs.ok &&
              runs.data.map((r) => (
                <option key={r.id} value={r.trade_date}>
                  {r.trade_date}
                  {r.status === "blocked" ? " (blocked)" : ""}
                </option>
              ))}
          </select>
        </label>
        <label className="flex flex-col">
          Minimum score
          <input
            name="min"
            type="number"
            min={0}
            max={100}
            defaultValue={min ?? "0"}
            className="w-24 rounded-lg border border-line-strong bg-surface px-2.5 py-1.5"
          />
        </label>
        <button className="rounded-lg bg-accent px-3 py-1.5 font-medium text-accent-fg hover:opacity-90">
          Show
        </button>
      </form>

      {!view.ok ? (
        <p className="mt-6 text-muted">
          {view.error}. Run <code>python -m app.cli scan</code> after the daily data update.
        </p>
      ) : (
        <>
          <RunBanner view={view.data} />
          {view.data.run.status === "ok" && (
            <>
              <p className="mt-6 text-sm text-muted">
                {view.data.total_results} stocks
                {minScore > 0 ? ` scoring at least ${minScore}` : ""}
                {view.data.total_results > view.data.results.length
                  ? `, showing the top ${view.data.results.length}`
                  : ""}
                . Click a stock for its breakdown.
              </p>
              <div className="overflow-x-auto">
                <table className="mt-2 w-full text-sm">
                  <thead className="text-left text-muted">
                    <tr>
                      <th className="py-1">#</th>
                      <th>Stock</th>
                      <th className="text-right">Score</th>
                      <th />
                      <th className="text-right">Close</th>
                      <th className="text-right">RSI</th>
                      <th className="text-right">ADX</th>
                      <th className="text-right">Vol x</th>
                      <th className="text-right">Off 52w high</th>
                      <th className="text-right">RS 3m</th>
                      <th className="text-right">RS 6m</th>
                      <th>Sector</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.data.results.map((r) => {
                      const i = r.indicators;
                      const isOpen = open === r.symbol;
                      const params = new URLSearchParams({
                        ...(date ? { date } : {}),
                        ...(min ? { min } : {}),
                        ...(isOpen ? {} : { open: r.symbol }),
                      });
                      return [
                        <tr key={r.symbol} className="border-t border-line">
                          <td className="py-1 text-muted">{r.rank}</td>
                          <td className="whitespace-nowrap">
                            <Link className="underline" href={`/scanner?${params}`} scroll={false}>
                              {r.symbol}
                            </Link>
                            {r.in_nifty500 && (
                              <span className="ml-1 text-xs text-muted">N500</span>
                            )}
                          </td>
                          <td className="text-right font-semibold">{r.score}</td>
                          <td className="pl-2">
                            <ScoreBar result={r} />
                          </td>
                          <td className="text-right">{Number(r.close).toFixed(2)}</td>
                          <td className="text-right">{num(i.rsi14)}</td>
                          <td className="text-right">{num(i.adx14)}</td>
                          <td className="text-right">{num(i.volume_ratio)}</td>
                          <td className="text-right">{num(i.below_52w_high_pct)}%</td>
                          <td className="text-right">{pct(i.rs_3m)}</td>
                          <td className="text-right">{pct(i.rs_6m)}</td>
                          <td className="pl-2 text-muted">{r.sector ?? ""}</td>
                        </tr>,
                        isOpen && (
                          <tr key={`${r.symbol}-detail`}>
                            <td />
                            <td colSpan={11}>
                              <Breakdown result={r} />
                              <Link
                                className="text-sm underline"
                                href={`/spot-check?symbol=${r.symbol}&date=${view.data.run.trade_date}`}
                              >
                                Spot-check {r.symbol} on {view.data.run.trade_date}
                              </Link>
                            </td>
                          </tr>
                        ),
                      ];
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}
