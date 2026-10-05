import Link from "next/link";

import { StockSearch } from "@/components/stock-search";
import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  LinkButton,
  Page,
  PageHeader,
  Table,
  Td,
  Th,
  buttonClass,
  cli,
  inputClass,
  inr,
  pctText,
  shortDate,
  signTone,
} from "@/components/ui";
import { type WatchItem, type Watchlist, getJson } from "@/lib/api";

import { removeWatch, saveWatch } from "./actions";

export const dynamic = "force-dynamic";

function AlertCell({ w }: { w: WatchItem }) {
  if (!w.alert_price) return <span className="text-muted">-</span>;
  return (
    <span className="whitespace-nowrap">
      {w.alert_direction === "above" ? "↑" : "↓"} {inr(w.alert_price)}
      {w.hit ? (
        <span className="ml-1.5">
          <Badge tone="accent" title={`Reached on ${w.last_date}: high ${inr(w.day_high)}, low ${inr(w.day_low)}`}>
            Hit
          </Badge>
        </span>
      ) : null}
    </span>
  );
}

const toAlert = (w: WatchItem) =>
  w.pct_to_alert === null ? "-" : w.hit ? "reached" : pctText(w.pct_to_alert, 1, true);

function Remove({ w }: { w: WatchItem }) {
  return (
    <form action={removeWatch.bind(null, w.ticker, "/watchlist")} className="inline">
      <button className="text-xs text-muted hover:text-bad hover:underline" aria-label={`Remove ${w.ticker}`}>
        Remove
      </button>
    </form>
  );
}

// Phones: one card per stock.
function WatchCard({ w }: { w: WatchItem }) {
  return (
    <li className="border-t border-line py-3 first:border-t-0 first:pt-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/stocks/${w.ticker}`} className="font-semibold hover:underline">
            {w.ticker}
          </Link>
          <p className="truncate text-xs text-muted">{w.name ?? w.sector ?? ""}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-semibold">{inr(w.last_close)}</p>
          <p className={`text-xs ${signTone(w.change_pct)}`}>{pctText(w.change_pct, 1, true)}</p>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>
          Alert <span className="text-fg"><AlertCell w={w} /></span>
        </span>
        {w.alert_price && (
          <span>
            To alert <span className="text-fg">{toAlert(w)}</span>
          </span>
        )}
        <span>
          From 52w high <span className="text-fg">{w.below_52w_high_pct === null ? "-" : `-${Number(w.below_52w_high_pct).toFixed(1)}%`}</span>
        </span>
        <span>
          Score <span className="text-fg">{w.score === null ? "-" : Number(w.score).toFixed(0)}</span>
        </span>
      </div>
      {w.note && <p className="mt-1 text-xs">{w.note}</p>}
      <div className="mt-1.5 flex items-center gap-4">
        <Link href={`/plan/${w.ticker}`} className="text-xs font-medium text-accent hover:underline">
          Plan trade
        </Link>
        <Link href={`/watchlist?edit=${w.ticker}`} className="text-xs text-muted hover:text-fg hover:underline">
          Edit
        </Link>
        <Remove w={w} />
      </div>
    </li>
  );
}

export default async function WatchlistPage({ searchParams }: { searchParams: Promise<{ error?: string; edit?: string }> }) {
  const { error, edit } = await searchParams;
  const result = await getJson<Watchlist>("/watchlist");
  const list = result.ok ? result.data : null;
  const editing = list?.items.find((i) => i.ticker === edit?.toUpperCase());
  return (
    <Page>
      <PageHeader
        title="Watchlist"
        subtitle={
          list && list.items.length > 0
            ? `${list.items.length} stock${list.items.length > 1 ? "s" : ""} · closes to ${shortDate(list.day)} · ${list.hits} at the alert price`
            : "Stocks you are waiting on, with a price that alerts you on Telegram"
        }
        action={
          <LinkButton href="/stocks" variant="ghost">
            Stocks
          </LinkButton>
        }
      />
      <ErrorNote error={error ?? (result.ok ? undefined : result.error)} />
      <Card title="Watching">
        {!list || list.items.length === 0 ? (
          <EmptyState>
            Nothing on the watchlist yet. Add a stock above, tap the star on a stock&apos;s page, or press Ctrl+K and
            type its name.
          </EmptyState>
        ) : (
          <>
            <ul className="md:hidden">
              {list.items.map((w) => (
                <WatchCard key={w.ticker} w={w} />
              ))}
            </ul>
            <div className="hidden md:block">
              <Table>
                <thead>
                  <tr>
                    <Th>Stock</Th>
                    <Th num>Close</Th>
                    <Th num>Day</Th>
                    <Th>Alert</Th>
                    <Th num help="How far the close must move to reach the alert price">
                      To alert
                    </Th>
                    <Th num help="How far the close is below the 52-week high (adjusted), from the latest scan">
                      From 52w high
                    </Th>
                    <Th num help="Technical score in the latest scan, 0 to 100, and rank">
                      Score
                    </Th>
                    <Th>Note</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((w) => (
                    <tr key={w.ticker} className={w.hit ? "bg-accent-bg/60" : ""}>
                      <Td>
                        <Link href={`/stocks/${w.ticker}`} className="font-semibold hover:underline">
                          {w.ticker}
                        </Link>
                        <span className="block max-w-[14rem] truncate text-xs text-muted">{w.name ?? ""}</span>
                      </Td>
                      <Td num>{inr(w.last_close)}</Td>
                      <Td num className={signTone(w.change_pct)}>
                        {pctText(w.change_pct, 1, true)}
                      </Td>
                      <Td>
                        <AlertCell w={w} />
                        {w.alerted_on && <span className="block text-xs text-muted">alerted {shortDate(w.alerted_on)}</span>}
                      </Td>
                      <Td num>{toAlert(w)}</Td>
                      <Td num>{w.below_52w_high_pct === null ? "-" : `-${Number(w.below_52w_high_pct).toFixed(1)}%`}</Td>
                      <Td num>
                        {w.score === null ? "-" : Number(w.score).toFixed(0)}
                        {w.rank !== null && <span className="ml-1 text-xs text-muted">#{w.rank}</span>}
                      </Td>
                      <Td className="max-w-[16rem] text-xs">{w.note}</Td>
                      <Td num>
                        <span className="inline-flex items-center gap-3">
                          <Link href={`/plan/${w.ticker}`} className="text-xs font-medium text-accent hover:underline">
                            Plan
                          </Link>
                          <Link href={`/watchlist?edit=${w.ticker}`} className="text-xs text-muted hover:text-fg hover:underline">
                            Edit
                          </Link>
                          <Remove w={w} />
                        </span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          </>
        )}
        {list && list.items.length > 0 && !list.day && (
          <p className="mt-3 text-xs text-muted">
            No prices yet: run <code>{cli("daily")}</code>
          </p>
        )}
      </Card>
      <Card
        title={editing ? `Change ${editing.ticker}` : "Watch a stock"}
        subtitle="The daily job checks the day's high (above) or low (below) against the alert price and sends one Telegram alert per price."
      >
        <form action={saveWatch} className="grid gap-3 text-sm sm:grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_auto_minmax(0,1.5fr)_auto]">
          <input type="hidden" name="back" value="/watchlist" />
          <label className="space-y-1">
            <span className="text-muted">Stock</span>
            <StockSearch name="ticker" placeholder="e.g. tata steel" required defaultValue={editing?.ticker ?? ""} />
          </label>
          <label className="space-y-1">
            <span className="text-muted">Alert price ₹ (optional)</span>
            <input name="alert_price" inputMode="decimal" defaultValue={editing?.alert_price ? String(Number(editing.alert_price)) : ""} className={inputClass} />
          </label>
          <label className="space-y-1">
            <span className="text-muted">When</span>
            <select name="alert_direction" defaultValue={editing?.alert_direction ?? "above"} className={inputClass}>
              <option value="above">Goes above</option>
              <option value="below">Goes below</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-muted">Note</span>
            <input name="note" defaultValue={editing?.note ?? ""} placeholder="What you are waiting for" className={inputClass} />
          </label>
          <div className="flex items-end">
            <button className={buttonClass}>{editing ? "Save" : "Watch"}</button>
          </div>
        </form>
      </Card>
    </Page>
  );
}
