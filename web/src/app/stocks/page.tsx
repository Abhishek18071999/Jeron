import Link from "next/link";
import { redirect } from "next/navigation";

import { SectorHeatmap } from "@/components/sector-heatmap";
import { StockSearch } from "@/components/stock-search";
import {
  Card,
  EmptyState,
  LinkButton,
  Page,
  PageHeader,
  Table,
  Td,
  Th,
  cli,
  inputClass,
  inr,
  pctText,
  shortDate,
  signTone,
} from "@/components/ui";
import { type MarketMood, type Ranked, getJson } from "@/lib/api";

export const dynamic = "force-dynamic";

const PAGE = 50;
const SORTS = [
  { key: "score", label: "Score" },
  { key: "rs", label: "Relative strength" },
  { key: "return", label: "6-month return" },
] as const;
type Sort = (typeof SORTS)[number]["key"];

type Search = { symbol?: string; sector?: string; sort?: string; page?: string };

function href(sp: { sector?: string; sort?: Sort; page?: number }) {
  const q = new URLSearchParams();
  if (sp.sector) q.set("sector", sp.sector);
  if (sp.sort && sp.sort !== "score") q.set("sort", sp.sort);
  if (sp.page && sp.page > 1) q.set("page", String(sp.page));
  const text = q.toString();
  return `/stocks${text ? `?${text}` : ""}#list`;
}

const pct = (v: number | null) => (v === null ? "-" : pctText(v * 100, 1, true));

export default async function Stocks({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const clean = (sp.symbol ?? "").trim().toUpperCase();
  if (clean) redirect(`/stocks/${encodeURIComponent(clean)}`);
  const sector = sp.sector?.trim() || undefined;
  const sort: Sort = SORTS.some((s) => s.key === sp.sort) ? (sp.sort as Sort) : "score";
  const page = Math.max(1, Number.parseInt(sp.page ?? "1", 10) || 1);
  const query = new URLSearchParams({ sort, offset: String((page - 1) * PAGE), limit: String(PAGE) });
  if (sector) query.set("sector", sector);
  const [rankedResult, moodResult] = await Promise.all([
    getJson<Ranked>(`/stocks/ranked?${query}`),
    getJson<MarketMood>("/market/mood"),
  ]);
  const ranked = rankedResult.ok ? rankedResult.data : null;
  const sectors = moodResult.ok ? moodResult.data.sectors : [];
  const pages = ranked ? Math.max(1, Math.ceil(ranked.total / PAGE)) : 1;
  const first = ranked && ranked.total ? ranked.offset + 1 : 0;
  const last = ranked ? ranked.offset + ranked.items.length : 0;

  return (
    <Page>
      <PageHeader
        title="Stocks"
        subtitle="Find a stock, see which industries lead, and browse the latest scan."
        action={
          <LinkButton href="/watchlist" variant="secondary">
            Watchlist
          </LinkButton>
        }
      />
      <Card>
        <StockSearch placeholder="Search: tata steel, RIL, ZOMATO" inputClassName={`${inputClass} py-2.5 text-base`} />
      </Card>

      <Card
        title="Sector heatmap"
        subtitle={
          moodResult.ok
            ? `NSE industries by median 6-month return, scan of ${shortDate(moodResult.data.day)}; the number is the stocks in each. Tap one to list its stocks.`
            : undefined
        }
        action={
          sector ? (
            <Link href={href({ sort })} className="text-muted hover:text-fg hover:underline">
              All industries
            </Link>
          ) : undefined
        }
      >
        {sectors.length === 0 ? (
          <EmptyState command={`${cli("lists")} && ${cli("scan")}`}>
            No industries yet: they come from the Nifty 500 list, returns from the scan.
          </EmptyState>
        ) : (
          <SectorHeatmap sectors={sectors} selected={sector} hrefFor={(s) => href({ sector: s === sector ? undefined : s, sort })} />
        )}
      </Card>

      <section id="list" className="scroll-mt-20">
        <Card
          title={sector ? `${sector}` : "The latest scan, ranked"}
          subtitle={
            ranked?.trade_date
              ? `${ranked.total.toLocaleString("en-IN")} stocks scored on ${shortDate(ranked.trade_date)}${sector ? " in this industry" : ""}`
              : undefined
          }
          action={
            <LinkButton href="/scanner" variant="ghost">
              Scanner
            </LinkButton>
          }
        >
          <nav aria-label="Sort" className="mb-3 flex flex-wrap gap-1 text-sm">
            {SORTS.map((s) => (
              <Link
                key={s.key}
                href={href({ sector, sort: s.key })}
                aria-current={s.key === sort ? "true" : undefined}
                className={`rounded-lg px-2.5 py-1 font-medium ${s.key === sort ? "bg-surface-2 text-fg" : "text-muted hover:text-fg"}`}
              >
                {s.label}
              </Link>
            ))}
          </nav>
          {!ranked || ranked.items.length === 0 ? (
            <EmptyState command={cli("daily")}>
              {rankedResult.ok ? "No completed scan yet." : rankedResult.error}
            </EmptyState>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>#</Th>
                    <Th>Stock</Th>
                    {!sector && <Th className="hidden lg:table-cell">Industry</Th>}
                    <Th num help="Technical score, 0 to 100 (see the scanner for its parts)">
                      Score
                    </Th>
                    <Th num className="hidden sm:table-cell" help="Return over the last 126 sessions, adjusted for splits and bonuses">
                      6m
                    </Th>
                    <Th num help="6-month return relative to the Nifty 500 over the same dates">
                      RS
                    </Th>
                    <Th num className="hidden md:table-cell" help="How far the close is below the 52-week high">
                      From high
                    </Th>
                    <Th num className="hidden sm:table-cell">
                      Close
                    </Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {ranked.items.map((t, i) => (
                    <tr key={t.symbol}>
                      <Td className="text-muted">{sort === "score" ? t.rank : ranked.offset + i + 1}</Td>
                      <Td>
                        <Link href={`/stocks/${t.symbol}`} className="font-semibold hover:underline">
                          {t.symbol}
                        </Link>
                        {t.watched && (
                          <span className="ml-1 text-xs text-muted" title="On the watchlist">
                            ★
                          </span>
                        )}
                        <span className="block max-w-[10rem] truncate text-xs text-muted sm:max-w-[16rem]">{t.name ?? ""}</span>
                      </Td>
                      {!sector && <Td className="hidden max-w-[12rem] truncate text-xs text-muted lg:table-cell">{t.sector ?? "-"}</Td>}
                      <Td num>{Number(t.score).toFixed(0)}</Td>
                      <Td num className={`hidden sm:table-cell ${signTone(t.return_6m)}`}>
                        {pct(t.return_6m)}
                      </Td>
                      <Td num className={signTone(t.rs_6m)}>
                        {pct(t.rs_6m)}
                      </Td>
                      <Td num className="hidden text-muted md:table-cell">
                        {t.below_52w_high_pct === null ? "-" : `-${t.below_52w_high_pct.toFixed(1)}%`}
                      </Td>
                      <Td num className="hidden sm:table-cell">
                        {inr(t.close)}
                      </Td>
                      <Td num>
                        <Link href={`/plan/${t.symbol}`} className="text-xs font-medium text-accent hover:underline">
                          Plan
                        </Link>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <div className="mt-3 flex items-center justify-between gap-3 text-sm">
                <span className="text-xs text-muted">
                  {first}–{last} of {ranked.total.toLocaleString("en-IN")}
                </span>
                <span className="flex gap-2">
                  {page > 1 && (
                    <LinkButton href={href({ sector, sort, page: page - 1 })} variant="secondary">
                      Previous
                    </LinkButton>
                  )}
                  {page < pages && (
                    <LinkButton href={href({ sector, sort, page: page + 1 })} variant="secondary">
                      Next
                    </LinkButton>
                  )}
                </span>
              </div>
            </>
          )}
        </Card>
      </section>
    </Page>
  );
}
