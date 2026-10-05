import type { MarketMood } from "@/lib/api";

import { Badge, Card, EmptyState, Help, Table, Td, Th, type Tone, cli, pctText, shortDate } from "./ui";

const modeTone: Record<MarketMood["mode"], Tone> = { attack: "accent", normal: "neutral", defend: "warn" };

const modeHelp: Record<MarketMood["mode"], string> = {
  attack: "Regime filter off, most stocks above their 200-day EMA and more new highs than lows: take every valid signal at full risk.",
  normal: "Regime filter off but breadth is mixed: full risk per trade, be selective.",
  defend: "The engine's regime filter is on: risk per trade is halved for every new signal.",
};

const num = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export function MoodBanner({ mood }: { mood: MarketMood | null }) {
  if (!mood) {
    return (
      <EmptyState command={cli("daily")}>
        Market mood unknown: no completed scan yet. The daily job downloads prices and scans.
      </EmptyState>
    );
  }
  const b = mood.breadth;
  const r = mood.regime;
  const gap = r?.nifty50 && r.nifty50_ema200 ? (r.nifty50 / r.nifty50_ema200 - 1) * 100 : null;
  return (
    <section
      className={`rounded-xl border px-4 py-3 sm:px-5 ${
        mood.mode === "defend"
          ? "border-warn/40 bg-warn-bg"
          : mood.mode === "attack"
            ? "border-accent/40 bg-accent-bg"
            : "border-line bg-surface"
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Badge tone={modeTone[mood.mode]} title={modeHelp[mood.mode]}>
          {mood.mode}
        </Badge>
        <p className="order-last w-full text-sm font-medium sm:order-none sm:w-auto sm:min-w-0 sm:flex-1">{mood.reason}</p>
        <span className="ml-auto text-xs text-muted sm:ml-0" title={mood.rule}>
          Risk per trade ×{mood.risk_multiplier}
          <Help text={`How the mode is set: ${mood.rule}`} />
        </span>
      </div>
      <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        <div title="Share of the scan universe closing above its own 200-day EMA: how many stocks are in long-term uptrends.">
          <dt className="inline">Above 200-day EMA </dt>
          <dd className="inline font-medium text-fg">
            {pctText(b.pct_above_ema200, 0)} of {num(b.stocks)}
          </dd>
          {b.nifty500_pct_above_ema200 !== null && <dd className="inline"> (Nifty 500: {pctText(b.nifty500_pct_above_ema200, 0)})</dd>}
        </div>
        <div title="Stocks whose high today beat every high of the past year, against stocks whose low broke every low of the past year.">
          <dt className="inline">52-week highs / lows </dt>
          <dd className="inline font-medium text-fg">
            {b.new_highs} / {b.new_lows}
          </dd>
        </div>
        {r && (
          <div title="The engine halves risk per trade while Nifty 50 closes below its 200-day EMA.">
            <dt className="inline">Nifty 50 </dt>
            <dd className="inline font-medium text-fg">{num(r.nifty50)}</dd>
            {gap !== null && (
              <dd className="inline">
                {" "}
                ({gap >= 0 ? "+" : ""}
                {gap.toFixed(1)}% vs 200-day EMA)
              </dd>
            )}
          </div>
        )}
        {r?.vix !== null && r?.vix !== undefined && (
          <div title="India VIX, the market's expected volatility. The engine halves risk when it is in the top 10% of the last five years.">
            <dt className="inline">India VIX </dt>
            <dd className="inline font-medium text-fg">{num(r.vix, 1)}</dd>
            {r.vix_top_decile !== null && <dd className="inline"> (top 10% from {num(r.vix_top_decile, 1)})</dd>}
          </div>
        )}
        <div>
          <dt className="inline">Scan </dt>
          <dd className="inline">{shortDate(mood.day)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function SectorStrength({ mood }: { mood: MarketMood | null }) {
  const rows = mood?.sectors ?? [];
  const max = Math.max(0.0001, ...rows.map((s) => Math.abs(s.median_return_6m ?? 0)));
  return (
    <Card
      title="Sector strength"
      subtitle="Median 6-month return of the stocks in each NSE industry, strongest first"
    >
      {rows.length === 0 ? (
        <EmptyState command={`${cli("lists")} && ${cli("scan")}`}>
          No sectors yet: industries come from the Nifty 500 list, returns from the scan.
        </EmptyState>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Industry</Th>
              <Th num help="Stocks of this industry in the scan universe">
                Stocks
              </Th>
              <Th className="w-[45%]" help="Median return over the last 126 sessions (about 6 months), adjusted for splits and bonuses">
                6-month median
              </Th>
              <Th num className="hidden sm:table-cell" help="Share of the industry's stocks closing above their 200-day EMA">
                Above EMA
              </Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const ret = s.median_return_6m;
              const width = ret === null ? 0 : (Math.abs(ret) / max) * 100;
              return (
                <tr key={s.sector} className={s.stocks < 3 ? "text-muted" : ""} title={s.stocks < 3 ? "Fewer than 3 stocks: a thin sample" : undefined}>
                  <Td className="max-w-[9rem] truncate sm:max-w-none">{s.sector}</Td>
                  <Td num className="text-muted">
                    {s.stocks}
                  </Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <span className={`w-14 shrink-0 text-right ${ret === null ? "text-muted" : ret >= 0 ? "text-good" : "text-bad"}`}>
                        {ret === null ? "-" : pctText(ret * 100, 1, true)}
                      </span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                        <span
                          className={`block h-full rounded-full ${ret !== null && ret < 0 ? "bg-bad" : "bg-good"}`}
                          style={{ width: `${width}%` }}
                        />
                      </span>
                    </div>
                  </Td>
                  <Td num className="hidden text-muted sm:table-cell">
                    {pctText(s.pct_above_ema200, 0)}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
