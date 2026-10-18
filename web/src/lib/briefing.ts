// The morning briefing on Today (docs/plans/ui-v2.md): one line per thing to do before
// the open, verb first, built from the pre-open exit plan and the signals waiting for a
// decision. Pure; the tick boxes live in components/briefing.tsx.
import type { Dashboard, Portfolio, SignalBrief } from "./api";

export type BriefKind = "sell" | "check" | "buy" | "record" | "cash";

export type BriefItem = {
  id: string;
  kind: BriefKind;
  title: string; // "Sell all 80 AZAD"
  detail: string; // why, in one line
  href: string;
};

const inr0 = (v: string | number) => `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

// The engine's reason up to the first ";" (the rest repeats the tier's rule).
export function plainReason(reason: string | null): string {
  if (!reason) return "";
  const first = reason.split(";")[0].trim();
  return first.charAt(0).toUpperCase() + first.slice(1);
}

function signalItem(s: SignalBrief, day: string | null): BriefItem {
  // Still valid for the coming session: place the order. Older: record what I did.
  const open = !day || s.valid_until >= day;
  return open
    ? {
        id: `buy:${s.signal_id}`,
        kind: "buy",
        title: `Buy ${s.shares.toLocaleString("en-IN")} ${s.ticker}`,
        detail: `09:00-09:07: limit at ${inr0(s.entry_high)} in the pre-open auction, cancel at 09:15 if not filled. Then a GTT stop at ${inr0(s.stop)}.`,
        href: `/plan/${s.ticker}?signal=${s.signal_id}`,
      }
    : {
        id: `record:${s.signal_id}`,
        kind: "record",
        title: `Record what you did with ${s.ticker}`,
        detail: `Signal of ${s.signal_date}: the fill, or why you skipped it.`,
        href: `/journal/signal/${s.signal_id}`,
      };
}

export function briefing(d: Dashboard, p: Portfolio | null): { items: BriefItem[]; events: string[]; headline: string } {
  const items: BriefItem[] = [];
  const holdings = p && !p.stale ? p.holdings : [];
  for (const h of holdings) {
    if (h.problem) {
      items.push({
        id: `check:${h.entry_id}`,
        kind: "check",
        title: `Check ${h.ticker} by hand`,
        detail: h.problem,
        href: `/journal/${h.entry_id}`,
      });
    } else if (h.action === "sell all") {
      items.push({
        id: `sell:${h.entry_id}`,
        kind: "sell",
        title: `Sell all ${h.shares.toLocaleString("en-IN")} ${h.ticker}`,
        detail: `At the open. ${plainReason(h.reason)}`,
        href: `/journal/${h.entry_id}`,
      });
    } else if (h.action === "sell half") {
      items.push({
        id: `half:${h.entry_id}`,
        kind: "sell",
        title: `Sell ${Math.floor(h.shares / 2).toLocaleString("en-IN")} of ${h.shares.toLocaleString("en-IN")} ${h.ticker}`,
        detail: `Book half at the open. ${plainReason(h.reason)}`,
        href: `/journal/${h.entry_id}`,
      });
    }
  }
  const sells = items.length;
  const day = p?.day ?? null;
  for (const s of d.pending) items.push(signalItem(s, day));
  if (p?.totals.cash_action) {
    items.push({
      id: "cash",
      kind: "cash",
      title: Number(p.totals.idle_cash) < 0 ? "Free up cash" : `Park ${inr0(Number(p.totals.idle_cash).toFixed(0))} of idle cash`,
      detail: p.totals.cash_action,
      href: "/portfolio",
    });
  }
  const events = holdings.flatMap((h) => h.events.map((e) => `${h.ticker}: ${e}`));
  const buys = items.filter((i) => i.kind === "buy").length;
  const parts = [
    sells ? `${sells} position${sells > 1 ? "s" : ""} to act on before 09:15` : null,
    buys ? `${buys} buy order${buys > 1 ? "s" : ""} to place` : null,
  ].filter(Boolean);
  const headline = parts.length
    ? `${parts.join(", ")}.`
    : items.length
      ? "Nothing to buy or sell at the open."
      : "Nothing to do before the open.";
  return { items, events, headline: headline.charAt(0).toUpperCase() + headline.slice(1) };
}
