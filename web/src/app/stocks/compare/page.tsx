import Link from "next/link";

import { Badge, Card, EmptyState, Notice, Page, PageHeader, Table, Td, Th, buttonClass, inputClass, shortDate } from "@/components/ui";
import { type StockBrief, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

// The rows, by fact label (app/explain/facts.py); a label that starts with one of these.
const ROWS: { label: string; match: string }[] = [
  { label: "Last close", match: "Last close" },
  { label: "Technical score", match: "Technical score" },
  { label: "Rank in the scan", match: "Rank in the scan" },
  { label: "200-day EMA", match: "200-day EMA" },
  { label: "RSI(14)", match: "RSI(14)" },
  { label: "ADX(14)", match: "ADX(14)" },
  { label: "Below the 52-week high", match: "Below the 52-week high" },
  { label: "ATR(14)", match: "ATR(14)" },
  { label: "Vs Nifty 500, 3 months", match: "Return vs Nifty 500, 3 months" },
  { label: "Vs Nifty 500, 6 months", match: "Return vs Nifty 500, 6 months" },
  { label: "Fundamental score", match: "Fundamental score" },
  { label: "Sales growth", match: "Sales growth" },
  { label: "P/E (TTM)", match: "P/E (TTM)" },
  { label: "P/E vs its history", match: "P/E vs its own history" },
  { label: "Results", match: "Results" },
  { label: "Signal", match: "Signal" },
  { label: "Strategy's record", match: "Strategy's out-of-sample record" },
];

const stanceClass = { for: "text-good", against: "text-bad", neutral: "" } as const;

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ symbols?: string }> }) {
  const { symbols = "" } = await searchParams;
  const wanted = symbols
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 3);
  const result = wanted.length ? await getJson<StockBrief[]>(`/stocks/compare?symbols=${encodeURIComponent(wanted.join(","))}`) : null;
  const briefs = result?.ok ? result.data : [];

  return (
    <Page>
      <PageHeader
        title="Compare stocks"
        subtitle="Up to three stocks side by side, from Jeron's own numbers. Green supports a long trade, red argues against; nothing here is a forecast."
      />
      <form className="flex max-w-xl gap-2" action="/stocks/compare">
        <input name="symbols" defaultValue={wanted.join(", ")} placeholder="e.g. TCS, INFY, HCLTECH" className={inputClass} />
        <button type="submit" className={buttonClass}>
          Compare
        </button>
      </form>
      {result && !result.ok && <Notice tone="bad">{result.error}</Notice>}
      {!wanted.length && (
        <EmptyState>Type two or three symbols, separated by commas, or press Compare on a stock&apos;s page.</EmptyState>
      )}
      {briefs.length > 0 && (
        <Card>
          <Table>
            <thead>
              <tr>
                <Th>&nbsp;</Th>
                {briefs.map((b) => (
                  <Th key={b.symbol}>
                    <Link href={`/stocks/${b.symbol}`} className="underline">
                      {b.symbol}
                    </Link>
                    <span className="block text-xs font-normal text-muted">
                      {b.name ?? ""} {b.as_of ? `· ${shortDate(b.as_of)}` : ""}
                    </span>
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.label} className="border-t border-line">
                  <Td className="text-muted">{row.label}</Td>
                  {briefs.map((b) => {
                    const f = b.facts.find((x) => x.label.startsWith(row.match));
                    return (
                      <Td key={b.symbol} className={f ? stanceClass[f.stance] : "text-muted"}>
                        {f ? f.value : "—"}
                      </Td>
                    );
                  })}
                </tr>
              ))}
              <tr className="border-t border-line">
                <Td className="text-muted">Setup</Td>
                {briefs.map((b) => (
                  <Td key={b.symbol}>{b.setup ? <Badge tone={b.setup.still_valid ? "good" : "bad"}>{b.setup.state}</Badge> : "no signal"}</Td>
                ))}
              </tr>
              <tr className="border-t border-line">
                <Td className="text-muted">Pre-trade checks passed</Td>
                {briefs.map((b) => (
                  <Td key={b.symbol}>
                    {b.checklist.filter((c) => c.status === "pass").length} of {b.checklist.length}
                  </Td>
                ))}
              </tr>
              <tr className="border-t border-line">
                <Td className="text-muted">Facts for / against</Td>
                {briefs.map((b) => (
                  <Td key={b.symbol}>
                    <span className="text-good">{b.supporting.length}</span> / <span className="text-bad">{b.against.length}</span>
                  </Td>
                ))}
              </tr>
            </tbody>
          </Table>
          <p className="mt-3 text-xs text-muted">
            Counting facts for and against is a summary, not a score: one hard reject or a results blackout can matter more
            than several green lines. Open a stock for its sources and dates.
          </p>
        </Card>
      )}
    </Page>
  );
}
