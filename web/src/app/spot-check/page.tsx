import Link from "next/link";

import { StockSearch } from "@/components/stock-search";
import { getJson, type SamplePick, type SpotCheck } from "@/lib/api";

export const dynamic = "force-dynamic";

type Search = { symbol?: string; date?: string; dividends?: string; sample?: string };

const fmt = (value: number | null) => (value === null ? "-" : value.toFixed(2));

export default async function SpotCheckPage({ searchParams }: { searchParams: Promise<Search> }) {
  const { symbol, date, dividends, sample } = await searchParams;
  const query = new URLSearchParams();
  if (symbol && date) {
    query.set("symbol", symbol);
    query.set("date", date);
    if (dividends === "on") query.set("dividends", "true");
  }
  const [spot, picks] = await Promise.all([
    symbol && date ? getJson<SpotCheck>(`/data/spot-check?${query}`) : null,
    sample ? getJson<SamplePick[]>("/data/spot-check/sample?n=20") : null,
  ]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Spot check</h1>
      <p className="mt-2 text-muted">
        Pick a stock and a date and compare these numbers with your broker&apos;s chart. Brokers
        show prices adjusted for splits and bonuses, so compare their chart with the
        &quot;Adjusted&quot; columns and the exchange&apos;s own numbers with &quot;Raw&quot;.
      </p>

      <form className="mt-6 flex flex-wrap items-end gap-3" action="/spot-check">
        <label className="flex flex-col text-sm">
          NSE symbol
          <StockSearch
            name="symbol"
            defaultValue={symbol ?? ""}
            placeholder="RELIANCE or RIL"
            required
            className="mt-1 w-56"
            inputClassName="w-full rounded-lg border border-line-strong bg-surface px-2.5 py-1.5"
          />
        </label>
        <label className="flex flex-col text-sm">
          Date
          <input
            type="date"
            name="date"
            defaultValue={date ?? ""}
            required
            className="mt-1 rounded-lg border border-line-strong bg-surface px-2.5 py-1.5"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="dividends" defaultChecked={dividends === "on"} />
          Also adjust for dividends
        </label>
        <button className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:opacity-90">
          Show
        </button>
        <Link href="/spot-check?sample=1" className="text-sm underline">
          Give me 20 stock-dates to check
        </Link>
      </form>

      {picks && (
        <section className="mt-6">
          <h2 className="text-lg font-semibold">20 stock-dates to check</h2>
          {picks.ok ? (
            <ul className="mt-2 grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
              {picks.data.map((p) => (
                <li key={`${p.symbol}-${p.trade_date}`}>
                  <Link
                    className="underline"
                    href={`/spot-check?symbol=${encodeURIComponent(p.symbol)}&date=${p.trade_date}`}
                  >
                    {p.symbol} on {p.trade_date}
                  </Link>{" "}
                  <span className="text-muted">({p.reason})</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-bad">{picks.error}</p>
          )}
        </section>
      )}

      {spot && !spot.ok && <p className="mt-6 text-bad">{spot.error}</p>}
      {spot && spot.ok && <SpotTables spot={spot.data} />}
    </main>
  );
}

function SpotTables({ spot }: { spot: SpotCheck }) {
  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">
        {spot.symbol} around {spot.requested_date}
      </h2>
      {spot.notes.map((n) => (
        <p key={n} className="mt-1 text-sm text-warn">
          {n}
        </p>
      ))}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-right text-sm tabular-nums">
          <thead className="text-muted">
            <tr>
              <th className="text-left">Date</th>
              <th colSpan={5} className="border-l border-line">
                Raw (NSE)
              </th>
              <th className="border-l border-line">Yahoo close</th>
              <th colSpan={5} className="border-l border-line">
                Adjusted
              </th>
              <th colSpan={8} className="border-l border-line">
                Indicators (adjusted)
              </th>
            </tr>
            <tr>
              <th />
              <th className="border-l border-line">Open</th>
              <th>High</th>
              <th>Low</th>
              <th>Close</th>
              <th>Volume</th>
              <th className="border-l border-line">(diff %)</th>
              <th className="border-l border-line">Open</th>
              <th>High</th>
              <th>Low</th>
              <th>Close</th>
              <th>Factor</th>
              <th className="border-l border-line">EMA 20</th>
              <th>EMA 50</th>
              <th>EMA 200</th>
              <th>RSI 14</th>
              <th>ATR 14</th>
              <th>MACD</th>
              <th>Signal</th>
              <th>ADX 14</th>
            </tr>
          </thead>
          <tbody>
            {spot.rows.map((r) => (
              <tr
                key={r.trade_date}
                className={`border-t border-line ${
                  r.trade_date === spot.requested_date ? "font-semibold" : ""
                }`}
              >
                <td className="py-1 text-left whitespace-nowrap">
                  {r.trade_date}
                  {r.series !== "EQ" && <span className="ml-1 text-xs text-muted">{r.series}</span>}
                </td>
                <td className="border-l border-line">{r.raw.open}</td>
                <td>{r.raw.high}</td>
                <td>{r.raw.low}</td>
                <td>{r.raw.close}</td>
                <td>{r.raw.volume.toLocaleString("en-IN")}</td>
                <td
                  className={`border-l border-line ${
                    r.close_mismatch ? "text-bad" : ""
                  }`}
                >
                  {r.second_source_close ?? "-"}
                  {r.diff_pct !== null && ` (${r.diff_pct})`}
                </td>
                <td className="border-l border-line">
                  {Number(r.adjusted.open).toFixed(2)}
                </td>
                <td>{Number(r.adjusted.high).toFixed(2)}</td>
                <td>{Number(r.adjusted.low).toFixed(2)}</td>
                <td>{Number(r.adjusted.close).toFixed(2)}</td>
                <td>{Number(r.factor).toFixed(4)}</td>
                <td className="border-l border-line">{fmt(r.ema20)}</td>
                <td>{fmt(r.ema50)}</td>
                <td>{fmt(r.ema200)}</td>
                <td>{fmt(r.rsi14)}</td>
                <td>{fmt(r.atr14)}</td>
                <td>{fmt(r.macd)}</td>
                <td>{fmt(r.macd_signal)}</td>
                <td>{fmt(r.adx14)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mt-8 text-lg font-semibold">Adjustment log</h2>
      {spot.adjustments.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No corporate actions recorded.</p>
      ) : (
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th>Ex-date</th>
              <th>Source</th>
              <th>Action</th>
              <th>Price factor</th>
              <th>Applied</th>
              <th>Price move matches</th>
              <th>Second source agrees</th>
            </tr>
          </thead>
          <tbody>
            {spot.adjustments.map((a, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1 whitespace-nowrap">{a.ex_date}</td>
                <td>{a.source === "nse" ? "NSE" : a.source}</td>
                <td>{a.description}</td>
                <td>{a.factor === null ? "-" : Number(a.factor).toFixed(4)}</td>
                <td>{a.applied ? "yes" : "no"}</td>
                <td>{yesNo(a.price_confirms)}</td>
                <td>{yesNo(a.confirmed_by_second_source)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function yesNo(value: boolean | null) {
  if (value === null) return "-";
  return value ? "yes" : <span className="text-bad">no</span>;
}
