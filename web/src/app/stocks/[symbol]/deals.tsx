// Who bought and sold this stock in size: bulk and block deals and insider trades.
// Information, not a signal (docs/decisions/0011).
import Link from "next/link";

import { Badge, Card, EmptyState, Help, Table, Td, Th, cli, shortDate, signTone } from "@/components/ui";
import type { DealParty, StockDeals } from "@/lib/api";

// ₹ in crore (1 crore = 10 million), or lakh below one crore.
export const crore = (value: number | string | null | undefined, signed = false) => {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  const sign = n < 0 ? "-" : signed && n > 0 ? "+" : "";
  const a = Math.abs(n);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 1 })} cr`;
  return `${sign}₹${(a / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 1 })} lakh`;
};

const shares = (n: number) => n.toLocaleString("en-IN");

function Parties({ title, rows, help }: { title: string; rows: DealParty[]; help: string }) {
  return (
    <div className="min-w-0">
      <h3 className="mb-1 text-sm font-medium">
        {title}
        <Help text={help} />
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">None in this period.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Who</Th>
              <Th num>Net</Th>
              <Th num>Last</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.name}>
                <Td>
                  {p.name}
                  <span className="block text-xs text-muted">
                    {p.deals} deal{p.deals === 1 ? "" : "s"} · {p.kinds.join(", ")} · net{" "}
                    {shares(Math.abs(p.bought_quantity - p.sold_quantity))} shares
                  </span>
                </Td>
                <Td num className={signTone(p.net_value)}>
                  {crore(p.net_value, true)}
                </Td>
                <Td num>{shortDate(p.last_day)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}

export function DealsPanel({ data, error }: { data: StockDeals | null; error?: string }) {
  if (!data) {
    return (
      <Card title="Big buyers and sellers">
        <p className="text-sm text-bad">{error ?? "Not available."}</p>
      </Card>
    );
  }
  const d = data;
  const cov = d.deals_coverage;
  const t = d.insider_totals;
  const gaps = cov.sessions !== null && cov.days < cov.sessions;
  return (
    <Card
      title="Big buyers and sellers"
      subtitle={`Bulk and block deals and insider trades since ${d.since}. Information, not a signal.`}
    >
      <div className="space-y-5 text-sm">
        {cov.first === null ? (
          <EmptyState command={cli("deals")}>
            No bulk or block deals stored yet. The daily job collects each day&apos;s; older ones load
            with <code>deals-import</code> from a CSV saved on nseindia.com.
          </EmptyState>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <Parties
                title="Net buyers"
                rows={d.buyers}
                help="Clients who bought more than they sold in bulk or block deals and kept the shares. Funds, promoters and investors show up here."
              />
              <Parties
                title="Net sellers"
                rows={d.sellers}
                help="Clients who sold more than they bought. A block sale by a promoter or private-equity fund is often a stake being exited."
              />
            </div>
            {d.day_traders.length > 0 && (
              <p className="text-muted">
                Same-day traders, left out above because they bought and sold on the same day (trading
                firms moving volume, not investors):{" "}
                {d.day_traders.map((p) => `${p.name} (${p.deals})`).join(", ")}.
              </p>
            )}
            {d.deals.length > 0 && (
              <details>
                <summary className="cursor-pointer text-muted">
                  All {d.deal_count} deal{d.deal_count === 1 ? "" : "s"}
                  {d.deal_count > d.deals.length ? ` (latest ${d.deals.length})` : ""}
                </summary>
                <Table className="mt-2">
                  <thead>
                    <tr>
                      <Th>Day</Th>
                      <Th>Client</Th>
                      <Th>Side</Th>
                      <Th num>Shares</Th>
                      <Th num>Price</Th>
                      <Th num>Value</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.deals.map((x) => (
                      <tr key={`${x.day}-${x.client}-${x.side}-${x.quantity}-${x.price}`}>
                        <Td className="whitespace-nowrap">
                          {x.day} <Badge>{x.kind}</Badge>
                        </Td>
                        <Td>{x.client}</Td>
                        <Td className={x.side === "buy" ? "text-good" : "text-bad"}>{x.side}</Td>
                        <Td num>{shares(x.quantity)}</Td>
                        <Td num>₹{Number(x.price).toLocaleString("en-IN")}</Td>
                        <Td num>{crore(x.value)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}
            <p className="text-xs text-muted">
              Deals stored from {cov.first} to {cov.last}
              {gaps
                ? `, on ${cov.days} of ${cov.sessions} trading days: the rest are missing, so this list is incomplete.`
                : "."}
            </p>
          </>
        )}

        <div>
          <h3 className="mb-1 font-medium">
            Insiders
            <Help text="Promoters, directors and employees must disclose their trades within 2 trading days to the company, which tells NSE within 2 more. Buys on the market, with their own money, say the most." />
          </h3>
          {d.insider_coverage.first === null ? (
            <EmptyState>
              No insider trades stored. Save the CSV from nseindia.com (Corporate filings, Insider
              trading) and upload it on <Link href="/setup" className="underline">Setup</Link>.
            </EmptyState>
          ) : d.insider_count === 0 ? (
            <p className="text-muted">
              No insider trades disclosed in this period (insider data held from {d.insider_coverage.first}{" "}
              to {d.insider_coverage.last}).
            </p>
          ) : (
            <div className="space-y-2">
              <p>
                On the market: promoters{" "}
                <span className={signTone(t.promoter_net)}>{crore(t.promoter_net, true)}</span> net, others{" "}
                <span className={signTone(t.others_net)}>{crore(t.others_net, true)}</span> net
                {t.other_modes > 0 &&
                  ` · ${t.other_modes} more by ESOP, gift, transfer or off-market, which say less`}
                .
              </p>
              <Table>
                <thead>
                  <tr>
                    <Th>Disclosed</Th>
                    <Th>Who</Th>
                    <Th>Side</Th>
                    <Th num>Shares</Th>
                    <Th num>Value</Th>
                    <Th num>Holding after</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.insider.map((x) => (
                    <tr key={`${x.disclosed}-${x.person}-${x.side}-${x.quantity}-${x.traded_from}`}>
                      <Td className="whitespace-nowrap">{x.disclosed}</Td>
                      <Td>
                        {x.person}
                        <span className="block text-xs text-muted">
                          {[x.category, x.mode].filter(Boolean).join(" · ")}
                        </span>
                      </Td>
                      <Td className={x.side === "buy" ? "text-good" : "text-bad"}>{x.side}</Td>
                      <Td num>{shares(x.quantity)}</Td>
                      <Td num>{crore(x.value)}</Td>
                      <Td num>{x.after_pct === null ? "-" : `${Number(x.after_pct).toFixed(2)}%`}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </div>

        <p className="text-xs text-muted">
          What this can tell you: who took or sold a big stake and at what price. What it can&apos;t: why,
          or what they do next. A bulk deal is published the evening it happens, an insider trade up to
          four trading days later, so the price has usually moved already. Jeron hasn&apos;t tested
          whether following these trades makes money, so they never change a signal.
        </p>
      </div>
    </Card>
  );
}
