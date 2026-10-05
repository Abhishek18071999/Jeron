import Link from "next/link";

import type { MarketMood } from "@/lib/api";

import { pctText } from "./ui";

type Sector = MarketMood["sectors"][number];

// Gains tint green, losses red, stronger for bigger moves; flat is the plain surface.
function tint(ret: number | null, max: number) {
  if (ret === null) return "var(--surface-2)";
  const strength = Math.round(8 + Math.min(1, Math.abs(ret) / max) * 40);
  return `color-mix(in oklab, var(${ret >= 0 ? "--good" : "--bad"}) ${strength}%, var(--surface))`;
}

// NSE industries coloured by median 6-month return; a tile opens its stocks below.
export function SectorHeatmap({
  sectors,
  selected,
  hrefFor,
}: {
  sectors: Sector[];
  selected?: string;
  hrefFor: (sector: string) => string;
}) {
  const max = Math.max(0.05, ...sectors.map((s) => Math.abs(s.median_return_6m ?? 0)));
  return (
    <ul className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-5" aria-label="Industries by median 6-month return">
      {sectors.map((s) => {
        const ret = s.median_return_6m;
        const active = s.sector === selected;
        return (
          <li key={s.sector}>
            <Link
              href={hrefFor(s.sector)}
              aria-current={active ? "true" : undefined}
              title={`${s.sector}: median 6-month return ${ret === null ? "unknown" : pctText(ret * 100, 1, true)}, ${s.stocks} stocks, ${pctText(s.pct_above_ema200, 0)} above their 200-day EMA`}
              className={`flex h-full min-h-[4.75rem] flex-col justify-between rounded-lg border px-2.5 py-2 transition-shadow hover:shadow-md ${
                active ? "border-accent ring-2 ring-accent" : "border-line"
              } ${s.stocks < 3 ? "opacity-70" : ""}`}
              style={{ background: tint(ret, max) }}
            >
              <span className="line-clamp-2 text-xs font-medium leading-snug">{s.sector}</span>
              <span className="mt-1 flex items-baseline justify-between gap-2">
                <span className="text-base font-semibold tracking-tight">
                  {ret === null ? "-" : pctText(ret * 100, 1, true)}
                </span>
                <span className="text-[0.7rem] text-muted">{s.stocks}</span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
