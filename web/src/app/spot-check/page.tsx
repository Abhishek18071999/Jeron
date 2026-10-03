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
      <h1 className="text-2xl font-semibold">Spot check</h1>
      <p className="mt-2 text-neutral-500">
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
            inputClassName="w-full rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
          />
        </label>
        <label className="flex flex-col text-sm">
          Date
          <input
            type="date"
            name="date"
            defaultValue={date ?? ""}
            required
            className="mt-1 rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="dividends" defaultChecked={dividends === "on"} />
          Also adjust for dividends
        </label>
        <button className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white dark:bg-neutral-100 dark:text-neutral-900">
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
                  <span className="text-neutral-500">({p.reason})</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-red-600">{picks.error}</p>
          )}
        </section>
      )}

      {spot && !spot.ok && <p className="mt-6 text-red-600">{spot.error}</p>}
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
        <p key={n} className="mt-1 text-sm text-amber-700 dark:text-amber-400">
          {n}
        </p>
      ))}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-right text-sm tabular-nums">
          <thead className="text-neutral-500">
            <tr>
              <th className="text-left">Date</th>
              <th colSpan={5} className="border-l border-neutral-200 dark:border-neutral-800">
                Raw (NSE)
              </th>
              <th className="border-l border-neutral-200 dark:border-neutral-800">Yahoo close</th>
              <th colSpan={5} className="border-l border-neutral-200 dark:border-neutral-800">
                Adjusted
              </th>
              <th colSpan={8} className="border-l border-neutral-200 dark:border-neutral-800">
                Indicators (adjusted)
              </th>
            </tr>
            <tr>
              <th />
              <th className="border-l border-neutral-200 dark:border-neutral-800">Open</th>
              <th>High</th>
              <th>Low</th>
              <th>Close</th>
              <th>Volume</th>
              <th className="border-l border-neutral-200 dark:border-neutral-800">(diff %)</th>
              <th className="border-l border-neutral-200 dark:border-neutral-800">Open</th>
              <th>High</th>
              <th>Low</th>
              <th>Close</th>
              <th>Factor</th>
              <th className="border-l border-neutral-200 dark:border-neutral-800">EMA 20</th>
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
                className={`border-t border-neutral-200 dark:border-neutral-800 ${
                  r.trade_date === spot.requested_date ? "font-semibold" : ""
                }`}
              >
                <td className="py-1 text-left whitespace-nowrap">
                  {r.trade_date}
                  {r.series !== "EQ" && <span className="ml-1 text-xs text-neutral-500">{r.series}</span>}
                </td>
                <td className="border-l border-neutral-200 dark:border-neutral-800">{r.raw.open}</td>
                <td>{r.raw.high}</td>
                <td>{r.raw.low}</td>
                <td>{r.raw.close}</td>
                <td>{r.raw.volume.toLocaleString("en-IN")}</td>
                <td
                  className={`border-l border-neutral-200 dark:border-neutral-800 ${
                    r.close_mismatch ? "text-red-600" : ""
                  }`}
                >
                  {r.second_source_close ?? "-"}
                  {r.diff_pct !== null && ` (${r.diff_pct})`}
                </td>
                <td className="border-l border-neutral-200 dark:border-neutral-800">
                  {Number(r.adjusted.open).toFixed(2)}
                </td>
                <td>{Number(r.adjusted.high).toFixed(2)}</td>
                <td>{Number(r.adjusted.low).toFixed(2)}</td>
                <td>{Number(r.adjusted.close).toFixed(2)}</td>
                <td>{Number(r.factor).toFixed(4)}</td>
                <td className="border-l border-neutral-200 dark:border-neutral-800">{fmt(r.ema20)}</td>
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
        <p className="mt-2 text-sm text-neutral-500">No corporate actions recorded.</p>
      ) : (
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-neutral-500">
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
              <tr key={i} className="border-t border-neutral-200 dark:border-neutral-800">
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
  return value ? "yes" : <span className="text-red-600">no</span>;
}
