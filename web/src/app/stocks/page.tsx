import Link from "next/link";
import { redirect } from "next/navigation";

import { StockSearch } from "@/components/stock-search";
import { Card, EmptyState, LinkButton, Page, PageHeader, Table, Td, Th, cli, inr, inputClass } from "@/components/ui";
import { type Dashboard, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Stocks({ searchParams }: { searchParams: Promise<{ symbol?: string }> }) {
  const { symbol } = await searchParams;
  const clean = (symbol ?? "").trim().toUpperCase();
  if (clean) redirect(`/stocks/${encodeURIComponent(clean)}`);
  const result = await getJson<Dashboard>("/dashboard");
  const scan = result.ok ? result.data.scan : null;
  const top = scan?.status === "ok" ? scan.top : [];
  return (
    <Page>
      <PageHeader title="Stocks" subtitle="Find a stock by symbol, company name, short name or old symbol." />
      <Card>
        <StockSearch placeholder="Search: tata steel, RIL, ZOMATO" inputClassName={`${inputClass} py-2.5 text-base`} />
      </Card>
      <Card
        title="Top of the latest scan"
        subtitle={scan ? `Highest technical scores on ${scan.trade_date}` : undefined}
        action={
          <LinkButton href="/scanner" variant="ghost">
            Full scanner
          </LinkButton>
        }
      >
        {top.length === 0 ? (
          <EmptyState command={cli("daily")}>No completed scan yet.</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Stock</Th>
                <Th num help="Technical score, 0 to 100 (see the scanner for its parts)">
                  Score
                </Th>
                <Th num>Close</Th>
              </tr>
            </thead>
            <tbody>
              {top.map((t, i) => (
                <tr key={t.symbol}>
                  <Td className="text-muted">{i + 1}</Td>
                  <Td>
                    <Link href={`/stocks/${t.symbol}`} className="font-semibold hover:underline">
                      {t.symbol}
                    </Link>
                  </Td>
                  <Td num>{Number(t.score).toFixed(0)}</Td>
                  <Td num>{inr(t.close)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </Page>
  );
}
