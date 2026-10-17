// The fundamental brain: the score, what it is made of, and the quarters behind it
// (NSE's XBRL filings, as known on each filing date).
import Link from "next/link";

import { Badge, Card, EmptyState, Help, Stat, Table, Td, Th, pctText, shortDate, signTone } from "@/components/ui";
import type { StockFundamentals } from "@/lib/api";

import { crore } from "./deals";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : pctText(v * 100, 1, true));
const plain = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? "-" : v.toLocaleString("en-IN", { maximumFractionDigits: digits });

export function FundamentalsPanel({ data, error }: { data: StockFundamentals | null; error?: string }) {
  if (!data) {
    return (
      <Card title="Fundamentals">
        <EmptyState>
          {error === "No results loaded for this stock" || !error ? (
            <>
              No quarterly results loaded for this stock yet. Jeron imports its bundled results lists by itself, and
              newer ones you upload on <Link href="/setup" className="underline">Setup</Link>; that page shows
              progress.
            </>
          ) : (
            error
          )}
        </EmptyState>
      </Card>
    );
  }
  const f = data.facts;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Fundamentals
          <Help text="From the quarterly results NSE published, as known on each filing date. Quality: growth, profitable quarters, margins, interest cover (70 points). Valuation: P/E against the stock's own last five years (30 points)." />
        </span>
      }
      subtitle={`Score ${data.version}, as of ${shortDate(data.as_of)}`}
      action={data.rejected ? <Badge tone="bad">Rejected</Badge> : undefined}
    >
      {data.rejected && <p className="mb-3 text-sm text-bad">{data.rejected}</p>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Score" value={data.score === null ? "-" : `${data.score} / 100`} />
        <Stat label="Sales growth (12 m)" value={pct(f.sales_growth)} />
        <Stat label="EPS growth (12 m)" value={pct(f.eps_growth)} />
        <Stat label="P/E" value={plain(f.pe)} />
        <Stat label="Quality" value={`${data.quality} / 70`} />
        <Stat label="Valuation" value={`${data.valuation} / 30`} />
        <Stat label="Net margin" value={f.margin === null || f.margin === undefined ? "-" : pctText(f.margin * 100, 1)} />
        <Stat label="Sales growth (3 y, a year)" value={pct(f.sales_cagr_3y)} />
      </div>
      {data.notes.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs text-muted">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <div className="mt-4 overflow-x-auto">
        <Table>
          <thead>
            <tr>
              <Th>Quarter</Th>
              <Th num>Revenue</Th>
              <Th num>Profit</Th>
              <Th num>EPS</Th>
              <Th num>Filed</Th>
            </tr>
          </thead>
          <tbody>
            {data.quarters.map((q) => (
              <tr key={`${q.period_end}-${q.filed}`}>
                <Td>
                  {shortDate(q.period_end)}
                  {!q.consolidated && <span className="ml-1 text-xs text-muted">standalone</span>}
                </Td>
                <Td num>{crore(q.revenue)}</Td>
                <Td num className={signTone(q.net_profit)}>
                  {crore(q.net_profit)}
                </Td>
                <Td num>{plain(q.eps, 2)}</Td>
                <Td num>{shortDate(q.filed)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </Card>
  );
}
