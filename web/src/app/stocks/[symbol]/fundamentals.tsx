// The fundamental brain: the score, what it is made of, and the quarters behind it
// (NSE's XBRL filings, as known on each filing date).
import Link from "next/link";

import { Badge, Card, EmptyState, Help, Stat, Table, Td, Th, pctText, shortDate, signTone } from "@/components/ui";
import type { FundHealth, StockFundamentals } from "@/lib/api";

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
        <Stat label="Interest cover" value={f.interest_cover === null || f.interest_cover === undefined ? "-" : `${plain(f.interest_cover)}x`} />
      </div>
      {data.notes.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs text-muted">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {data.health && <BalanceSheet health={data.health} />}
      <div className="mt-4 overflow-x-auto">
        <Table stack>
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
                <Td label="Quarter">
                  {shortDate(q.period_end)}
                  {!q.consolidated && <span className="ml-1 text-xs text-muted">standalone</span>}
                </Td>
                <Td label="Revenue" num>{crore(q.revenue)}</Td>
                <Td label="Profit" num className={signTone(q.net_profit)}>
                  {crore(q.net_profit)}
                </Td>
                <Td label="EPS" num>{plain(q.eps, 2)}</Td>
                <Td label="Filed" num>{shortDate(q.filed)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </Card>
  );
}

const times = (v: number | null) => (v === null ? "-" : `${plain(v)}x`);
const ratio = (v: number | null) => (v === null ? "-" : plain(v, 2));

// fundamentals-v2: the latest balance sheet and three years of cash flow, shown beside the
// score but not in it.
function BalanceSheet({ health: h }: { health: FundHealth }) {
  return (
    <div className="mt-4 border-t border-line pt-3">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        Balance sheet and cash
        <Help text="From the half-yearly and annual results (September and March quarters), which carry the balance sheet and the cash-flow statement. ROE: the last four quarters' profit over shareholders' equity. ROCE: profit before tax and interest over equity plus borrowings. EV/EBITDA: market value plus debt minus cash, over profit before interest, tax, depreciation and amortisation. Shown, not part of the score." />
      </h3>
      <p className="mb-2 text-xs text-muted">
        {h.balance_sheet_as_of ? `Balance sheet of ${shortDate(h.balance_sheet_as_of)}` : "No recent balance sheet"}
      </p>
      {h.warnings.length > 0 && (
        <ul className="mb-2 space-y-0.5 text-sm text-bad">
          {h.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="ROE" value={pct(h.roe)} />
        <Stat label="ROCE" value={pct(h.roce)} />
        <Stat label="Debt / equity" value={ratio(h.debt_equity)} />
        <Stat label="EV / EBITDA" value={times(h.ev_ebitda)} />
        <Stat label="Equity" value={crore(h.equity)} />
        <Stat label="Borrowings" value={crore(h.debt)} />
        <Stat label="Cash" value={crore(h.cash)} />
      </div>
      {h.cash_flow.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <Table stack>
            <thead>
              <tr>
                <Th>Financial year</Th>
                <Th num>Operating cash flow</Th>
                <Th num>Profit</Th>
              </tr>
            </thead>
            <tbody>
              {h.cash_flow.map((y) => (
                <tr key={y.year_end}>
                  <Td label="Financial year">FY{String(new Date(y.year_end).getFullYear()).slice(2)}</Td>
                  <Td label="Operating cash flow" num className={signTone(y.operating_cash_flow)}>
                    {crore(y.operating_cash_flow)}
                  </Td>
                  <Td label="Profit" num className={signTone(y.profit)}>
                    {crore(y.profit)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {h.notes.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-muted">
          {h.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
