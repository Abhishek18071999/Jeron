import Link from "next/link";

import type { Holding, Portfolio } from "@/lib/api";

import { Badge, Help, type Tone, inr, inrSigned, pctText, rMultiple, signTone } from "./ui";

export const actionTone = (action: Holding["action"]): Tone =>
  action === "sell all" || action === "sell half" ? "accent" : "neutral";

export function ActionBadge({ h }: { h: Holding }) {
  if (h.problem) {
    return (
      <Badge tone="warn" title={h.problem}>
        Check
      </Badge>
    );
  }
  if (!h.action) return <span className="text-muted">-</span>;
  return (
    <Badge tone={actionTone(h.action)} title={h.reason ?? undefined}>
      {h.action}
    </Badge>
  );
}

// Portfolio heat against the limits: a bar to the block level with a mark at the warning.
export function HeatMeter({ totals }: { totals: Portfolio["totals"] }) {
  const heat = Number(totals.heat_pct);
  const warn = Number(totals.heat_warn_pct);
  const block = Number(totals.heat_block_pct);
  const width = Math.min(100, (heat / block) * 100);
  const hot = heat >= warn;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs text-muted">
        <span>
          Heat <span className={`font-medium ${hot ? "text-warn" : "text-fg"}`}>{pctText(heat, 1)}</span> of capital
          <Help
            text={`Total open risk (entry minus today's stop, times shares) as a share of capital. Warning at ${warn}%, no new entries above ${block}%.`}
          />
        </span>
        <span>limit {pctText(block, 0)}</span>
      </div>
      <div className="relative mt-1.5 h-2 rounded-full bg-surface-2">
        <div className={`h-full rounded-full ${hot ? "bg-warn" : "bg-fg/70"}`} style={{ width: `${width}%` }} />
        <div
          className="absolute top-[-3px] h-[14px] w-px bg-line-strong"
          style={{ left: `${(warn / block) * 100}%` }}
          title={`Warning at ${warn}%`}
        />
      </div>
    </div>
  );
}

export function SectorBars({ totals, limit }: { totals: Portfolio["totals"]; limit?: number }) {
  const cap = Number(totals.sector_cap_pct);
  const rows = limit ? totals.sectors.slice(0, limit) : totals.sectors;
  const scale = Math.max(cap * 1.5, ...rows.map((s) => Number(s.pct_of_capital)));
  return (
    <ul className="space-y-2.5">
      {rows.map((s) => {
        const pct = Number(s.pct_of_capital);
        return (
          <li key={s.sector}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate" title={s.sector}>
                {s.sector}
                <span className="ml-1.5 text-xs text-muted">
                  {s.positions} {s.positions === 1 ? "stock" : "stocks"}
                </span>
              </span>
              <span className={`shrink-0 ${s.over_cap ? "font-medium text-warn" : ""}`}>
                {pctText(pct, 1)}
                <span className="ml-1.5 text-xs text-muted">{inr(s.value, 0)}</span>
              </span>
            </div>
            <div className="relative mt-1 h-1.5 rounded-full bg-surface-2">
              <div
                className={`h-full rounded-full ${s.over_cap ? "bg-warn" : "bg-fg/60"}`}
                style={{ width: `${Math.min(100, (pct / scale) * 100)}%` }}
              />
              <div
                className="absolute top-[-3px] h-[12px] w-px bg-line-strong"
                style={{ left: `${(cap / scale) * 100}%` }}
                title={`Sector cap ${cap}% of capital`}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const stopText = (h: Holding) =>
  h.stop_distance_pct === null ? "-" : `${pctText(h.stop_distance_pct, 1)}`;

const daysText = (h: Holding) => `${h.days_held}d`;

const daysTitle = (h: Holding) =>
  `${h.days_held} calendar days since the first buy on ${h.first_date}` +
  (h.sessions_held === null ? "" : ` (${h.sessions_held} sessions after the entry day)`);

// Phones: one card per position.
export function HoldingCard({ h }: { h: Holding }) {
  return (
    <li className="border-t border-line py-3 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/journal/${h.entry_id}`} className="font-semibold hover:underline">
            {h.ticker}
          </Link>
          <p className="truncate text-xs text-muted">
            {h.shares} sh @ {inr(h.avg_entry)} · {h.sector ?? "sector unknown"}
          </p>
        </div>
        <div className="shrink-0 whitespace-nowrap text-right">
          <p className={`font-semibold ${signTone(h.pnl)}`}>{inrSigned(h.pnl)}</p>
          <p className={`text-xs ${signTone(h.r_multiple)}`}>{rMultiple(h.r_multiple)}</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>
          Close <span className="text-fg">{inr(h.last_close)}</span>
        </span>
        <span title={h.stop ? `Stop ${inr(h.stop)}` : "No stop"}>
          To stop <span className="text-fg">{stopText(h)}</span>
        </span>
        <span title={daysTitle(h)}>
          Held <span className="text-fg">{daysText(h)}</span>
        </span>
        <ActionBadge h={h} />
      </div>
      {(h.problem || (h.action && h.action !== "hold")) && (
        <p className="mt-1 text-xs text-muted">{h.problem ?? h.reason}</p>
      )}
      {h.events.map((e) => (
        <p key={e} className="mt-1 text-xs text-warn">
          {e}
        </p>
      ))}
    </li>
  );
}
